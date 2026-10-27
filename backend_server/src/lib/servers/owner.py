"""
Which server owns a host (TASK-179 P4).

A tool that takes ``host_name`` must run against the server that holds that host: its registry, its trees, its locks.
``route_for_call`` finds the owner and, when it is not this server, points the MCP client at it for that one call
(``turn.use_target``). Order, first answer wins:

1. an explicit ``server`` argument of the tool call;
2. the chat's scope, when it names one server (picker on a single server);
3. the page's selected host, when it is the host being asked about (its server came with the message);
4. the merged host list of all servers (cached 30 s per user).

Two servers with the same host name: ``OwnerError`` asking which one (G8), never a silent pick. No server has it:
``OwnerError`` saying so, naming any server that could not be asked. Names match case-insensitively.
Outside a turn (no user credential) nothing changes: the tool runs locally with the service key.
"""

import contextlib
import logging
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

from backend_server.src.lib.servers import registry, turn
from backend_server.src.lib.servers.fanout import all_servers

logger = logging.getLogger(__name__)

HOST_LIST_TTL_SECONDS = 30
# user fingerprint -> (monotonic time, {server name: [host names]}, [unreachable "name: reason"])
_host_cache: Dict[str, Tuple[float, Dict[str, List[str]], List[str]]] = {}


class OwnerError(Exception):
    """The owner cannot be decided; the message is for the model and the user."""


def invalidate() -> None:
    _host_cache.clear()


def _local_host_names() -> List[str]:
    from backend_server.src.lib.utils.server_utils import get_host_manager
    return [h.get('host_name') or name for name, h in get_host_manager().get_all_hosts().items()]


def _self_label() -> str:
    return registry.self_name() or 'this server'


def _servers_by_name() -> Dict[str, Dict[str, Any]]:
    return {row['name'].lower(): row for row in registry.servers(include_disabled=False)}


def _is_self(name: str) -> bool:
    me = registry.self_name()
    return bool(me) and name.lower() == me.lower()


def _host_map(user: turn.TurnContext) -> Tuple[Dict[str, List[str]], List[str]]:
    """{server name: host names} for every server that answered, plus the ones that did not."""
    key = user.fingerprint()
    cached = _host_cache.get(key)
    if cached and time.monotonic() - cached[0] < HOST_LIST_TTL_SECONDS:
        return cached[1], cached[2]
    hosts: Dict[str, List[str]] = {_self_label(): _local_host_names()}
    failed: List[str] = []
    for result in all_servers('/server/system/getAllHosts', {}, headers=dict(user.headers)):
        if not result.ok:
            failed.append(f'{result.server}: {result.error}')
            continue
        rows = result.data.get('hosts') if isinstance(result.data, dict) else None
        if not isinstance(rows, list):
            failed.append(f'{result.server}: bad response')
            continue
        hosts[result.server] = [h.get('host_name') for h in rows if isinstance(h, dict) and h.get('host_name')]
    _host_cache[key] = (time.monotonic(), hosts, failed)
    return hosts, failed


def _row_for(name: str, strict: bool = True) -> Optional[Dict[str, Any]]:
    """The list row of server ``name``. ``strict`` (the model named it): an unknown name is an error. Not strict (the
    page's picker sent it): an unknown name is ignored, so a picker label that differs from the list never blocks."""
    if _is_self(name):
        return {'name': name, 'url': ''}
    row = _servers_by_name().get(name.lower())
    if row is None:
        if not strict:
            return None
        known = ', '.join(r['name'] for r in registry.servers(include_disabled=False)) or 'none listed'
        raise OwnerError(f"Unknown server '{name}'. Servers: {known}.")
    return row


def resolve(host_name: str, explicit_server: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The owning server's list row (``name``, ``url``), or None when this server owns it (or there is no turn)."""
    user = turn.current()
    if user is None:
        return None
    host_key = (host_name or '').strip().lower()

    explicit = (explicit_server or '').strip()
    if explicit:
        row = _row_for(explicit)
        return None if _is_self(row['name']) else row
    picked = ''
    if user.scope and not user.is_all:
        picked = user.scope
    elif host_key and user.selected_host.lower() == host_key and user.selected_host_server:
        picked = user.selected_host_server
    if picked:
        row = _row_for(picked, strict=False)
        if row is not None:
            return None if _is_self(row['name']) else row

    if not host_key:
        return None
    hosts, failed = _host_map(user)
    owners = [server for server, names in hosts.items() if host_key in {n.lower() for n in names}]
    if len(owners) > 1:
        raise OwnerError(f"Host '{host_name}' exists on {len(owners)} servers ({', '.join(sorted(owners))}). "
                         f"Ask the user which server, then call again with server='<name>'.")
    if not owners:
        tail = f" Could not ask: {'; '.join(failed)}." if failed else ''
        raise OwnerError(f"Host '{host_name}' not found on any server.{tail}")
    return None if _is_self(owners[0]) or owners[0] == _self_label() else _row_for(owners[0])


@contextlib.contextmanager
def route_for_call(host_name: Optional[str], explicit_server: Optional[str] = None) -> Iterator[Optional[Dict[str, Any]]]:
    """Run one tool call against the server that owns ``host_name``. Raises ``OwnerError`` when it cannot be decided.
    A call with no host follows the chat's scope when that names another server; otherwise it stays here."""
    row = resolve(host_name or '', explicit_server)
    if row is None:
        yield None
        return
    with turn.use_target(row['name'], row['url']):
        yield row
