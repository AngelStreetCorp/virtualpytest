"""Shared fixtures for the TASK-42 run-services route tests (not collected by pytest).

* ``FakeSupabase`` — a small in-memory PostgREST stand-in: tables are lists of
  dicts; ``eq / neq / in_ / is_ / gte / lt / order / limit / range`` filter
  them, ``insert / update / delete / upsert`` mutate them, and ``rpc`` calls
  a registered Python handler. It records every rpc call for assertions.
* ``make_app`` — a bare Flask app with the blueprints under test and a
  principal installed the way the global guard does it (role, user id,
  explicit permission grants; role defaults stubbed to empty).
* ``FakeHosts`` — the registered-host registry of "this server".
"""

from __future__ import annotations

import copy
import os
import sys
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional

from flask import Flask, request

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

TEAM_A = '00000000-0000-0000-0000-00000000000a'
TEAM_B = '00000000-0000-0000-0000-00000000000b'
USER_A = 'user-a'
USER_B = 'user-b'


def new_id() -> str:
    return str(uuid.uuid4())


class _Result:
    def __init__(self, data: Any, count: Optional[int] = None) -> None:
        self.data = data
        self.count = count


class FakeQuery:
    def __init__(self, db: 'FakeSupabase', table: str) -> None:
        self.db = db
        self.table_name = table
        self.op = 'select'
        self.payload: Any = None
        self.filters: List[Callable[[Dict[str, Any]], bool]] = []
        self._order: List[tuple] = []
        self._limit: Optional[int] = None
        self._range: Optional[tuple] = None
        self._count = False
        self._on_conflict: Optional[str] = None
        self.columns: Optional[str] = None

    # verbs
    def select(self, columns: str = '*', count: Optional[str] = None) -> 'FakeQuery':
        self.columns = columns
        self._count = count == 'exact'
        return self

    def insert(self, payload: Any) -> 'FakeQuery':
        self.op, self.payload = 'insert', payload
        return self

    def update(self, payload: Dict[str, Any]) -> 'FakeQuery':
        self.op, self.payload = 'update', payload
        return self

    def upsert(self, payload: Any, on_conflict: str = '', ignore_duplicates: bool = False) -> 'FakeQuery':
        self.op, self.payload, self._on_conflict = 'upsert', payload, on_conflict
        return self

    def delete(self) -> 'FakeQuery':
        self.op = 'delete'
        return self

    # filters
    def eq(self, col: str, val: Any) -> 'FakeQuery':
        self.filters.append(lambda r, c=col, v=val: str(r.get(c)) == str(v) if v is not None else r.get(c) is None)
        return self

    def in_(self, col: str, values: Iterable[Any]) -> 'FakeQuery':
        allowed = {str(v) for v in values}
        if '.' in col:  # embedded resource filter: script_results.host_name
            rel, field = col.split('.', 1)
            self.filters.append(lambda r, rel=rel, f=field: str((r.get(rel) or {}).get(f)) in allowed)
        else:
            self.filters.append(lambda r, c=col: str(r.get(c)) in allowed)
        return self

    def is_(self, col: str, val: Any) -> 'FakeQuery':
        self.filters.append(lambda r, c=col: r.get(c) is None)
        return self

    def or_(self, expression: str) -> 'FakeQuery':
        self.db.or_expressions.append(expression)
        return self

    def order(self, col: str, desc: bool = False) -> 'FakeQuery':
        self._order.append((col, desc))
        return self

    def limit(self, n: int) -> 'FakeQuery':
        self._limit = n
        return self

    def range(self, start: int, end: int) -> 'FakeQuery':
        self._range = (start, end)
        return self

    def _matches(self) -> List[Dict[str, Any]]:
        rows = self.db.tables.setdefault(self.table_name, [])
        return [r for r in rows if all(f(r) for f in self.filters)]

    def execute(self) -> _Result:
        rows = self.db.tables.setdefault(self.table_name, [])
        if self.op == 'insert':
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            created = []
            for item in items:
                row = {'id': new_id(), 'created_at': '2026-10-03T00:00:00+00:00',
                       'updated_at': '2026-10-03T00:00:00+00:00', **copy.deepcopy(item)}
                rows.append(row)
                created.append(copy.deepcopy(row))
            return _Result(created)
        if self.op == 'upsert':
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            keys = [k.strip() for k in (self._on_conflict or '').split(',') if k.strip()]
            created = []
            for item in items:
                if keys and any(all(str(r.get(k)) == str(item.get(k)) for k in keys) for r in rows):
                    continue
                rows.append(copy.deepcopy(item))
                created.append(copy.deepcopy(item))
            return _Result(created)
        matched = self._matches()
        if self.op == 'update':
            for r in matched:
                r.update(copy.deepcopy(self.payload))
            return _Result([copy.deepcopy(r) for r in matched])
        if self.op == 'delete':
            for r in matched:
                rows.remove(r)
            return _Result([copy.deepcopy(r) for r in matched])
        for col, desc in reversed(self._order):
            matched.sort(key=lambda r, c=col: (r.get(c) is None, str(r.get(c))), reverse=desc)
        total = len(matched)
        if self._range:
            matched = matched[self._range[0]:self._range[1] + 1]
        if self._limit is not None:
            matched = matched[:self._limit]
        return _Result([self._project(copy.deepcopy(r)) for r in matched], total if self._count else None)

    def _project(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Return only the selected columns, like PostgREST (plain column lists only)."""
        if not self.columns or self.columns.strip() == '*' or '(' in self.columns:
            return row
        wanted = [c.strip() for c in self.columns.split(',') if c.strip()]
        return {c: row.get(c) for c in wanted}


class _Rpc:
    def __init__(self, data: Any) -> None:
        self._data = data

    def execute(self) -> _Result:
        if isinstance(self._data, Exception):
            raise self._data
        return _Result(self._data)


class FakeSupabase:
    def __init__(self) -> None:
        self.tables: Dict[str, List[Dict[str, Any]]] = {}
        self.rpc_handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {}
        self.rpc_calls: List[tuple] = []
        self.or_expressions: List[str] = []

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)

    def rpc(self, name: str, params: Dict[str, Any]) -> _Rpc:
        self.rpc_calls.append((name, copy.deepcopy(params)))
        handler = self.rpc_handlers.get(name)
        if handler is None:
            raise AssertionError(f'unexpected rpc {name}')
        try:
            return _Rpc(handler(params))
        except Exception as e:  # surfaced at execute(), like postgrest
            return _Rpc(e)


class FakeHosts:
    def __init__(self, hosts: Dict[str, List[str]]) -> None:
        # A device is a device_id string, or a (device_id, device_name) pair.
        self._hosts = {name: {'host_name': name, 'devices': [
            {'device_id': d[0], 'device_name': d[1]} if isinstance(d, tuple) else {'device_id': d}
            for d in devices]} for name, devices in hosts.items()}

    def get_all_hosts(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._hosts)

    def get_host(self, name: str) -> Optional[Dict[str, Any]]:
        return self._hosts.get(name)


def install(monkeypatch, *, hosts: Optional[Dict[str, List[Any]]] = None) -> FakeSupabase:
    """Point every run-services data module at one FakeSupabase and the host registry at FakeHosts."""
    from backend_server.src.lib import auth_middleware
    from backend_server.src.services.analytics import scope
    from shared.src.lib.database import run_rpc

    fake = FakeSupabase()
    monkeypatch.setattr(run_rpc, 'get_supabase', lambda: fake)
    for module_name in ('run_defects_db', 'run_share_db', 'custom_reports_db', 'manual_sessions_db'):
        module = __import__(f'shared.src.lib.database.{module_name}', fromlist=['x'])
        monkeypatch.setattr(module, 'get_supabase', lambda: fake)
    for module_name in ('backend_server.src.services.sharing.snapshot',
                        'backend_server.src.services.analytics.report_query',
                        'backend_server.src.services.live.adapter',
                        'backend_server.src.routes.server_defects_routes'):
        module = __import__(module_name, fromlist=['x'])
        monkeypatch.setattr(module, 'get_supabase', lambda: fake)
    registry = FakeHosts(hosts if hosts is not None else {'host-1': ['device1', 'device2'], 'host-2': ['device1']})
    monkeypatch.setattr(scope, 'get_host_manager', lambda: registry)
    monkeypatch.setattr(auth_middleware, 'role_default_permissions', lambda role: set())
    fake.registry = registry
    return fake


def make_app(*blueprints: Any, role: str = 'tester', user_id: str = USER_A,
             permissions: Iterable[str] = ()) -> Flask:
    app = Flask(__name__)
    app.config['TESTING'] = True
    perms = list(permissions)

    @app.before_request
    def _principal() -> None:
        request.user_id = user_id
        request.user_role = role
        request.user_permissions = perms
        request.user_denied_permissions = []
        request.user_team_ceiling = None

    for bp in blueprints:
        app.register_blueprint(bp)
    return app


def script_result(team_id: str = TEAM_A, *, host: str = 'host-1', device: str = 'device1',
                  name: str = 'goto_live', success: bool = True, duration: Optional[int] = 1000,
                  **extra: Any) -> Dict[str, Any]:
    row = {
        'id': new_id(), 'team_id': team_id, 'script_name': name, 'script_type': name,
        'userinterface_name': 'ui_a', 'environment': 'prod', 'host_name': host, 'device_name': device,
        'success': success, 'execution_time_ms': duration, 'started_at': '2026-10-02T10:00:00+00:00',
        'completed_at': '2026-10-02T10:01:00+00:00', 'discard': False, 'run_group_id': None,
        'milestone_id': None,
    }
    row.update(extra)
    return row
