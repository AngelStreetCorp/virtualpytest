"""
The Atlas chat turn's identity and server scope (TASK-179 P4).

The browser adds its login to each ``send_message``; the socket handler binds it here for the length of that turn
(``bind_turn`` ... ``reset_turn`` in a ``finally``). ``MCPAPIClient`` then sends **the user's credential instead of the
service key**, and ``use_target`` points the client at the server that owns a host for one tool call.

Why a ``ContextVar``: one gevent process runs every chat, and the MCP client is a shared singleton. A ``ContextVar`` is
per greenlet (greenlet >= 0.4.17 gives each greenlet its own ``contextvars.Context``), so two chats never see each
other's credential. ``bind_turn`` is called inside the turn's own coroutine, never on a thread pool (BUG-0700).

Rules:
- The credential lives only in this ``ContextVar``: never in the session store, a log, the database or the prompt.
  ``TurnContext.headers`` is excluded from ``repr`` so an accidental ``%s`` of the turn prints nothing secret.
- Only ``Authorization: Bearer`` and ``X-Auto-Sign`` are kept (the same two ``fanout.credential_headers`` forwards).
  The service ``X-API-Key`` is never sent to another server.
- No credential (an external MCP client, Slack, a background job): ``current()`` is None and everything behaves as
  before, local and with the service key.
"""

import contextlib
import hashlib
import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, Mapping, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Cloudflare 403s the default python-requests UA on *.angelstreet.io (same string as fanout.USER_AGENT).
USER_AGENT = 'Mozilla/5.0 (compatible; VirtualPyTest-server/1.0; +atlas-turn)'
SCOPE_ALL = 'all'
_MAX_CREDENTIAL_LENGTH = 4096


@dataclass(frozen=True)
class TurnContext:
    """What one chat turn carries. ``headers`` is the user's credential and never printed."""
    headers: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)
    scope: str = ''                  # 'all' | a server name | '' (unknown: behave as before)
    selected_host: str = ''          # the host chosen in the page, if any
    selected_host_server: str = ''   # the server that host belongs to, if the page knew it

    @property
    def is_all(self) -> bool:
        return self.scope.lower() == SCOPE_ALL

    def fingerprint(self) -> str:
        """A one-way tag of the credential, to key per-user caches without keeping the secret in a key."""
        blob = '\n'.join(f'{k}={v}' for k, v in sorted(self.headers.items()))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Target:
    """The server one tool call is pointed at."""
    name: str
    url: str


_turn: ContextVar[Optional[TurnContext]] = ContextVar('atlas_turn', default=None)
_target: ContextVar[Optional[Target]] = ContextVar('atlas_target', default=None)


def _clean_credential(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ''
    if not text or len(text) > _MAX_CREDENTIAL_LENGTH or any(ch in text for ch in '\r\n\x00'):
        return ''
    return text


def credential_headers(token: Any = None, auto_sign: Any = None) -> Dict[str, str]:
    """The two headers a user can be known by. A malformed value (CR/LF, too long) is dropped, not truncated."""
    headers: Dict[str, str] = {}
    bearer = _clean_credential(token)
    if bearer:
        headers['Authorization'] = bearer if bearer.lower().startswith('bearer ') else f'Bearer {bearer}'
    signed = _clean_credential(auto_sign)
    if signed:
        headers['X-Auto-Sign'] = signed
    return headers


def bind_turn(token: Any = None, auto_sign: Any = None, scope: Any = '', selected_host: Any = '',
              selected_host_server: Any = '') -> Token:
    """Start a turn on this greenlet. Always pair with ``reset_turn`` in a ``finally``."""
    return _turn.set(TurnContext(
        headers=credential_headers(token, auto_sign),
        scope=str(scope or '').strip(),
        selected_host=str(selected_host or '').strip(),
        selected_host_server=str(selected_host_server or '').strip(),
    ))


def reset_turn(token: Token) -> None:
    try:
        _turn.reset(token)
    except ValueError:  # token made in another context (greenlet hop): just clear this one
        _turn.set(None)


def current() -> Optional[TurnContext]:
    """The turn of this greenlet, only when it carries a user credential."""
    turn = _turn.get()
    return turn if turn is not None and turn.headers else None


def target() -> Optional[Target]:
    return _target.get()


def target_url() -> Optional[str]:
    found = _target.get()
    return found.url.rstrip('/') if found else None


@contextlib.contextmanager
def use_target(name: str, url: str) -> Iterator[Target]:
    """Point the MCP client at another server for one tool call. Needs a user credential: the service key must never
    be sent to a server that is not this one."""
    if current() is None:
        raise RuntimeError('a remote target needs a signed-in user turn')
    found = Target(name=name, url=url.rstrip('/'))
    token = _target.set(found)
    try:
        yield found
    finally:
        try:
            _target.reset(token)
        except ValueError:
            _target.set(None)


def scope_tag() -> str:
    """Non-secret scope marker for result caches (a cached list_hosts from All mode is not one for rpitest)."""
    turn = current()
    if turn is None:
        return ''
    return f'{turn.scope}|{turn.selected_host_server}'


def scope_line(scope: str, server_names: list) -> str:
    """The one prompt line that tells the model which servers a question covers."""
    scope = (scope or '').strip()
    if not scope:
        return ''
    if scope.lower() == SCOPE_ALL:
        names = ', '.join(server_names)
        return f"Scope: all servers ({names})" if names else 'Scope: all servers'
    return f'Scope: server {scope}'


def request_headers(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Headers for a server call made for this turn: ``base`` (caller attribution) minus the service key, plus the
    user's credential. Outside a turn, returns ``base`` untouched."""
    headers = dict(base or {})
    turn = current()
    if turn is None:
        return headers
    headers.pop('X-API-Key', None)
    headers.update(turn.headers)
    headers['User-Agent'] = USER_AGENT
    return headers


# ---- plain HTTP helpers for code that does not go through MCPAPIClient (the section 6 places) -------------------

def _local_base() -> str:
    import os
    return os.getenv('SERVER_BASE_URL', 'http://localhost:5109').rstrip('/')


def _base_for_turn() -> str:
    return target_url() or _local_base()


def get_json(path: str, params: Optional[Dict[str, Any]] = None, timeout: float = 5) -> Optional[Dict[str, Any]]:
    """GET ``path`` on the server this call is pointed at (the target, else this server) with the user's credential.
    None on any failure. Only for a turn: without one the caller should use its local path."""
    if current() is None:
        return None
    try:
        resp = requests.get(_base_for_turn() + path, params=params or {}, headers=request_headers(),
                            timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except (requests.RequestException, ValueError):
        return None


def get_bytes(path: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10) -> Tuple[Optional[bytes], Optional[str]]:
    """GET raw bytes from the server this call is pointed at. ``(bytes, None)`` or ``(None, reason)``."""
    if current() is None:
        return None, 'no signed-in user for this call'
    try:
        resp = requests.get(_base_for_turn() + path, params=params or {}, headers=request_headers(),
                            timeout=timeout)
    except requests.RequestException as exc:
        return None, f'{type(exc).__name__} reaching the owner server'
    if resp.status_code == 200 and resp.content:
        return resp.content, None
    return None, f'HTTP {resp.status_code} from the owner server'
