"""Per-connection principal registry for Socket.IO (BUG-0156).

A Socket.IO connection authenticates once, at the handshake. After that the flask request
context is gone, so the principal has to be remembered against the connection's sid for the
handlers that run later (`send_message`, `approve`, `join_session`, …).

Kept deliberately small and in one place: the alternative is each namespace re-deriving who
the caller is, which is the duplication that produced BUG-0154.
"""

from typing import Optional

from flask import request

# sid -> principal dict, as returned by authorize_socket_connection().
_CONNECTIONS: dict = {}


def remember(sid: str, principal: dict) -> None:
    _CONNECTIONS[sid] = principal


def forget(sid: str) -> None:
    _CONNECTIONS.pop(sid, None)


def principal(sid: Optional[str] = None) -> Optional[dict]:
    """The principal behind the current (or named) socket connection."""
    if sid is None:
        sid = getattr(request, 'sid', None)
    return _CONNECTIONS.get(sid) if sid else None


def current_user_id(sid: Optional[str] = None) -> Optional[str]:
    found = principal(sid)
    return found.get('user_id') if found else None


def is_shared_principal(sid: Optional[str] = None) -> bool:
    """True when the connection is not one identifiable person.

    The service key, open mode, auto-sign and the published server key all resolve to the
    same user_id for everybody, so ownership comparisons against them are meaningless —
    every caller would look like the owner, or nobody would.
    """
    found = principal(sid)
    return bool(found and found.get('shared'))


def connection_count() -> int:
    """Live connections. Exposed for tests and for a leak check in the logs."""
    return len(_CONNECTIONS)
