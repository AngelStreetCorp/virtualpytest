"""Request scope for run-services endpoints (TASK-42 §4.1).

Every authenticated read, mutation and aggregate is limited to:

* the validated ``team_id`` — read with the same precedence as the global
  team-scope guard (query string first, then the JSON body for writes); a body
  naming a different team than the query string is refused;
* the hosts registered on THIS backend_server (multi-server isolation, the
  same rule as ``/server/script-results/getAllScriptResults``);
* the active workspace filter when the client sends one: ``host_filter`` (JSON
  array of host names) and/or ``device_filter`` (JSON array of
  ``host_name:device_id`` keys, the workspace format). ``script_results``
  stores the device DISPLAY name (``selected_device.device_name``), so
  ``resolve_scope`` translates each key to ``host_name:device_name`` with the
  registered hosts' device lists before matching rows.

The scope is applied inside the queries (before limits and aggregation).
Opaque ids (defect, result, snapshot, task, session) are re-checked against it.
"""

from __future__ import annotations

import functools
import json
import uuid
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Optional, Tuple

from flask import jsonify, request

from backend_server.src.lib.utils.server_utils import get_host_manager


class ScopeError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def error_json(message: str, status: int, **extra: Any):
    body = {'error': message}
    body.update(extra)
    return jsonify(body), status


def scope_error_response(error: ScopeError):
    return error_json(error.message, error.status)


def handle_scope_errors(f):
    """Turn a ScopeError raised anywhere in the handler into its HTTP response."""
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ScopeError as e:
            return scope_error_response(e)
    return wrapped


def json_body() -> Dict[str, Any]:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def resolve_team_id() -> str:
    from_args = (request.args.get('team_id') or '').strip()
    from_body = ''
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        raw = json_body().get('team_id')
        from_body = str(raw).strip() if raw else ''
    if from_args and from_body and from_args != from_body:
        raise ScopeError('team_id in the query string and the body disagree', 400)
    team_id = from_args or from_body
    if not team_id:
        raise ScopeError('team_id is required', 400)
    if not is_uuid(team_id):
        raise ScopeError('team_id must be a UUID', 400)
    return team_id


def actor_id() -> str:
    actor = getattr(request, 'user_id', None)
    if not actor:
        raise ScopeError('an authenticated principal is required', 401)
    return str(actor)


def is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def require_uuid(value: Any, name: str) -> str:
    if not is_uuid(value):
        raise ScopeError(f'{name} must be a UUID', 400)
    return str(value)


def _raw_list(name: str) -> Optional[List[str]]:
    raw: Any = request.args.get(name)
    if raw is None and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        raw = json_body().get(name)
    if raw is None or raw == '':
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise ScopeError(f'{name} must be a JSON array of strings', 400)
    if not isinstance(raw, list):
        raise ScopeError(f'{name} must be a JSON array of strings', 400)
    return [str(item).strip() for item in raw if str(item or '').strip()]


@dataclass(frozen=True)
class RunScope:
    team_id: str
    host_names: Tuple[str, ...]
    device_keys: Optional[Tuple[str, ...]]
    # The workspace's raw ``host:device_id`` keys. Rows that record the device
    # id rather than its display name (campaign_executions.device_name) match
    # either form.
    device_id_keys: Optional[Tuple[str, ...]] = None

    @property
    def campaign_device_keys(self) -> Optional[Tuple[str, ...]]:
        if self.device_keys is None:
            return None
        return tuple(sorted(set(self.device_keys) | set(self.device_id_keys or ())))

    def allows_host(self, host_name: Optional[str]) -> bool:
        return bool(host_name) and host_name in self.host_names

    def allows_device(self, host_name: Optional[str], device_name: Optional[str]) -> bool:
        if not self.allows_host(host_name):
            return False
        if self.device_keys is None:
            return True
        return f'{host_name}:{device_name}' in self.device_keys

    def allows_result(self, row: Optional[Dict[str, Any]]) -> bool:
        if not row:
            return False
        if str(row.get('team_id') or self.team_id) != self.team_id:
            return False
        return self.allows_device(row.get('host_name'), row.get('device_name'))

    def describe(self) -> Dict[str, Any]:
        return {
            'host_count': len(self.host_names),
            'device_filter_applied': self.device_keys is not None,
        }


def build_scope(team_id: str, registered_hosts: Iterable[str], host_filter: Optional[List[str]],
                device_filter: Optional[List[str]]) -> RunScope:
    hosts = sorted(set(h for h in registered_hosts if h))
    if host_filter is not None:
        allowed = set(host_filter)
        hosts = [h for h in hosts if h in allowed]
    device_keys: Optional[Tuple[str, ...]] = None
    if device_filter is not None:
        keys = []
        for key in device_filter:
            host, sep, device = key.partition(':')
            if not sep or not host or not device:
                raise ScopeError(f"device_filter entry '{key}' is not a 'host_name:device_id' key", 400)
            if host in hosts:
                keys.append(key)
        device_keys = tuple(sorted(set(keys)))
        hosts = [h for h in hosts if any(k.startswith(f'{h}:') for k in device_keys)]
    return RunScope(team_id=team_id, host_names=tuple(hosts), device_keys=device_keys)


def device_keys_to_names(device_filter: Optional[List[str]],
                         hosts: Dict[str, Dict[str, Any]]) -> Optional[List[str]]:
    """Map workspace ``host:device_id`` keys to the ``host:device_name`` form rows carry.

    A key whose device is not registered (or has no display name) is kept as is,
    so a decommissioned device still matches rows recorded under its id.
    """
    if device_filter is None:
        return None
    names: Dict[str, str] = {}
    for host_name, host in (hosts or {}).items():
        for device in (host or {}).get('devices') or []:
            if isinstance(device, dict) and device.get('device_id') and device.get('device_name'):
                names[f"{host_name}:{device['device_id']}"] = f"{host_name}:{device['device_name']}"
    return [names.get(key, key) for key in device_filter]


def device_display_name(hosts: Dict[str, Dict[str, Any]], host_name: Optional[str],
                        device_id: Optional[str]) -> Optional[str]:
    """Display name of a registered device (what script_results stores), else the id."""
    for device in ((hosts or {}).get(host_name or '') or {}).get('devices') or []:
        if isinstance(device, dict) and device.get('device_id') == device_id and device.get('device_name'):
            return device['device_name']
    return device_id


def registered_hosts() -> Dict[str, Dict[str, Any]]:
    """The hosts registered on this server (one snapshot per request)."""
    return get_host_manager().get_all_hosts()


def scope_from_request(team_id: str, hosts: Dict[str, Dict[str, Any]]) -> RunScope:
    """Team + registered hosts + the request's workspace host/device filters."""
    raw_devices = _raw_list('device_filter')
    scope = build_scope(team_id, list(hosts.keys()), _raw_list('host_filter'),
                        device_keys_to_names(raw_devices, hosts))
    if raw_devices is None:
        return scope
    id_keys = tuple(sorted({k for k in raw_devices if k.partition(':')[0] in scope.host_names}))
    return replace(scope, device_id_keys=id_keys)


def resolve_scope(team_id: Optional[str] = None,
                  hosts: Optional[Dict[str, Dict[str, Any]]] = None) -> RunScope:
    team = team_id or resolve_team_id()
    return scope_from_request(team, registered_hosts() if hosts is None else hosts)


def bounded_int(raw: Any, *, default: int, minimum: int, maximum: int, name: str) -> int:
    if raw is None or raw == '':
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ScopeError(f'{name} must be an integer', 400)
    if value < minimum or value > maximum:
        raise ScopeError(f'{name} must be between {minimum} and {maximum}', 400)
    return value


def derive_status(row: Optional[Dict[str, Any]]) -> str:
    """Execution verdict of one script_results row, from persisted evidence only.

    The single status rule for every run-management reader (summary, group
    rollup and report, rerun selection, share snapshot); ``rm_run_query`` and
    ``rm_eligible_attempts`` apply the same rule in SQL.

    ``script_results`` rows are inserted at start with ``success=false`` and no
    duration; a row is terminal once it passed or recorded an execution time.
    Anything else has no terminal evidence and is ``unknown`` (never failed).
    """
    if not row:
        return 'unknown'
    if row.get('success') is True:
        return 'passed'
    if row.get('execution_time_ms') is not None:
        return 'failed'
    return 'unknown'
