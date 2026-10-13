"""
TASK-42 — shared route-test helpers.

``make_task42_app`` builds a bare Flask app with the blueprints under test and
a before_request that mirrors the production /server/* guard (principal from
JWT-like claims, viewer write floor, team scope) with real permission
resolution against the fresh-install role catalog.

Two fake service-role clients:
  - ``FakeSupabaseClient`` / ``FakeChain``: records the fluent calls and returns
    preloaded data regardless of filters (call-shape assertions);
  - ``MemorySupabase``: really filters rows, enforces the unique keys of the
    run-management tables and dispatches RPCs to Python handlers (behaviour
    assertions: scope, pagination after aggregation, idempotency).

Not pytest-discoverable (no ``test_`` prefix).
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest
from flask import Flask, request


_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_TEST_DIR, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


TEAM_A = "00000000-0000-0000-0000-00000000000a"
TEAM_B = "00000000-0000-0000-0000-00000000000b"

# ---------------------------------------------------------------------------
# Module-loading utilities
# ---------------------------------------------------------------------------


def load_route_module(module_name: str):
    """Import a route module by absolute path under `backend_server.src.routes`."""
    return importlib.import_module(f'backend_server.src.routes.{module_name}')


# ---------------------------------------------------------------------------
# Fake client for the route layer
# ---------------------------------------------------------------------------


class FakeChain:
    """Mock for the postgrest fluent chain used by the data layer.

    Each call records its verb + kwargs so a test can introspect the filter
    order. Returns the data that the caller pre-loaded via ``_data``.
    """

    def __init__(self, data: Optional[List[Dict[str, Any]]] = None) -> None:
        self._data: List[Dict[str, Any]] = list(data or [])
        self.calls: List[Dict[str, Any]] = []

    # builder verbs ------------------------------------------------------------
    def select(self, *args: Any, **kwargs: Any) -> 'FakeChain':
        self.calls.append({'verb': 'select', 'args': args, 'kwargs': kwargs})
        return self

    def insert(self, payload: Any, *args: Any, **kwargs: Any) -> 'FakeChain':
        self.calls.append({'verb': 'insert', 'args': (payload,) + args, 'kwargs': kwargs})
        if isinstance(payload, dict):
            self._data = [payload]
        elif isinstance(payload, list):
            self._data = list(payload)
        return self

    def update(self, payload: Any, *args: Any, **kwargs: Any) -> 'FakeChain':
        self.calls.append({'verb': 'update', 'args': (payload,) + args, 'kwargs': kwargs})
        return self

    def upsert(self, payload: Any, *args: Any, **kwargs: Any) -> 'FakeChain':
        self.calls.append({'verb': 'upsert', 'args': (payload,) + args, 'kwargs': kwargs})
        if isinstance(payload, dict):
            self._data = [payload]
        elif isinstance(payload, list):
            self._data = list(payload)
        return self

    def delete(self, *args: Any, **kwargs: Any) -> 'FakeChain':
        self.calls.append({'verb': 'delete', 'args': args, 'kwargs': kwargs})
        return self

    def eq(self, col: str, val: Any) -> 'FakeChain':
        self.calls.append({'verb': 'eq', 'column': col, 'value': val})
        return self

    def in_(self, col: str, values: Iterable[Any]) -> 'FakeChain':
        self.calls.append({'verb': 'in_', 'column': col, 'values': list(values)})
        return self

    def order(self, col: str, desc: bool = False) -> 'FakeChain':
        self.calls.append({'verb': 'order', 'column': col, 'desc': bool(desc)})
        return self

    def limit(self, n: int) -> 'FakeChain':
        self.calls.append({'verb': 'limit', 'n': int(n)})
        return self

    def gte(self, col: str, val: Any) -> 'FakeChain':
        self.calls.append({'verb': 'gte', 'column': col, 'value': val})
        return self

    def is_(self, col: str, val: Any) -> 'FakeChain':
        self.calls.append({'verb': 'is_', 'column': col, 'value': val})
        return self

    def single(self) -> 'FakeChain':
        self.calls.append({'verb': 'single'})
        return self

    def range(self, start: int, end: int) -> 'FakeChain':
        self.calls.append({'verb': 'range', 'start': int(start), 'end': int(end)})
        return self

    def neq(self, col: str, val: Any) -> 'FakeChain':
        self.calls.append({'verb': 'neq', 'column': col, 'value': val})
        return self

    def lte(self, col: str, val: Any) -> 'FakeChain':
        self.calls.append({'verb': 'lte', 'column': col, 'value': val})
        return self

    def lt(self, col: str, val: Any) -> 'FakeChain':
        self.calls.append({'verb': 'lt', 'column': col, 'value': val})
        return self

    def gt(self, col: str, val: Any) -> 'FakeChain':
        self.calls.append({'verb': 'gt', 'column': col, 'value': val})
        return self

    def ilike(self, col: str, pattern: str) -> 'FakeChain':
        self.calls.append({'verb': 'ilike', 'column': col, 'value': pattern})
        return self

    # terminator ---------------------------------------------------------------
    def execute(self) -> Any:
        self.calls.append({'verb': 'execute'})
        result = MagicMock()
        result.data = self._data
        result.count = len(self._data)
        return result


class FakeSupabaseClient:
    """Tracks tables by name; each table is its own FakeChain."""

    def __init__(self) -> None:
        self.tables: Dict[str, FakeChain] = {}

    def table(self, name: str) -> FakeChain:
        if name not in self.tables:
            self.tables[name] = FakeChain()
        return self.tables[name]

    def rpc(self, name: str, params: Dict[str, Any]) -> FakeChain:
        chain = self.tables.setdefault(f'rpc:{name}', FakeChain())
        chain.calls.append({'verb': 'rpc', 'name': name, 'params': params})
        return chain


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


class MemoryQuery:
    """A PostgREST-like query over MemorySupabase rows that really filters.

    Supports the verbs the run-management data layer uses: select (with
    ``count='exact'`` and the known embeds), eq/neq/in_/is_/gte/gt/lte/lt/ilike,
    order, range/limit, insert/update/delete. Embedded filters
    (``script_result_labels.run_label_id``) apply as an inner join.
    """

    def __init__(self, db: 'MemorySupabase', table: str) -> None:
        self.db = db
        self.table = table
        self.op = 'select'
        self.payload: Any = None
        self.filters: List[Callable[[Dict[str, Any]], bool]] = []
        self.orders: List[Tuple[str, bool]] = []
        self.window: Optional[Tuple[int, int]] = None
        self.embeds: str = ''

    # verbs ------------------------------------------------------------------
    def select(self, columns: str = '*', count: Optional[str] = None) -> 'MemoryQuery':
        self.embeds = columns
        return self

    def insert(self, payload: Any) -> 'MemoryQuery':
        self.op, self.payload = 'insert', payload
        return self

    def update(self, payload: Dict[str, Any]) -> 'MemoryQuery':
        self.op, self.payload = 'update', payload
        return self

    def delete(self) -> 'MemoryQuery':
        self.op = 'delete'
        return self

    def _value(self, row: Dict[str, Any], col: str) -> Any:
        return row.get(col)

    def eq(self, col: str, val: Any) -> 'MemoryQuery':
        if '.' in col:
            embed, field = col.split('.', 1)
            self.filters.append(lambda r, e=embed, f=field, v=val: any(
                str(x.get(f)) == str(v) for x in self.db.embedded(self.table, e, r)))
        else:
            self.filters.append(lambda r, c=col, v=val: str(r.get(c)) == str(v) if v is not None else r.get(c) is None)
        return self

    def neq(self, col: str, val: Any) -> 'MemoryQuery':
        self.filters.append(lambda r, c=col, v=val: str(r.get(c)) != str(v))
        return self

    def in_(self, col: str, values: Iterable[Any]) -> 'MemoryQuery':
        wanted = {str(v) for v in values}
        self.filters.append(lambda r, c=col: str(r.get(c)) in wanted)
        return self

    def is_(self, col: str, val: Any) -> 'MemoryQuery':
        self.filters.append(lambda r, c=col: r.get(c) is None)
        return self

    _AND_CLAUSE = re.compile(r'and\(((?:[^()"]|"(?:[^"\\]|\\.)*")*)\)')
    _EQ_TERM = re.compile(r'(\w+)\.eq\.("(?:[^"\\]|\\.)*"|[^,]*)')

    def or_(self, expression: str) -> 'MemoryQuery':
        """The ``or=(and(col.eq."v",...),...)`` form the data layer emits for
        the workspace device filter (quoted values, backslash escapes)."""
        alternatives = []
        for clause in self._AND_CLAUSE.findall(expression):
            terms = {}
            for col, raw in self._EQ_TERM.findall(clause):
                if raw.startswith('"'):
                    raw = re.sub(r'\\(.)', r'\1', raw[1:-1])
                terms[col] = raw
            alternatives.append(terms)
        if not alternatives:
            raise AssertionError(f'unsupported or_ expression: {expression}')
        self.filters.append(lambda r, alts=alternatives: any(
            all(str(r.get(c)) == v for c, v in alt.items()) for alt in alts))
        return self

    def gte(self, col: str, val: Any) -> 'MemoryQuery':
        self.filters.append(lambda r, c=col, v=val: r.get(c) is not None and str(r.get(c)) >= str(v))
        return self

    def gt(self, col: str, val: Any) -> 'MemoryQuery':
        self.filters.append(lambda r, c=col, v=val: r.get(c) is not None and str(r.get(c)) > str(v))
        return self

    def lte(self, col: str, val: Any) -> 'MemoryQuery':
        self.filters.append(lambda r, c=col, v=val: r.get(c) is not None and str(r.get(c)) <= str(v))
        return self

    def lt(self, col: str, val: Any) -> 'MemoryQuery':
        self.filters.append(lambda r, c=col, v=val: r.get(c) is not None and str(r.get(c)) < str(v))
        return self

    def ilike(self, col: str, pattern: str) -> 'MemoryQuery':
        needle = pattern.strip('%').replace('\\%', '%').replace('\\_', '_').lower()
        self.filters.append(lambda r, c=col: needle in str(r.get(c) or '').lower())
        return self

    def order(self, col: str, desc: bool = False) -> 'MemoryQuery':
        self.orders.append((col, bool(desc)))
        return self

    def range(self, start: int, end: int) -> 'MemoryQuery':
        self.window = (int(start), int(end) + 1)
        return self

    def limit(self, n: int) -> 'MemoryQuery':
        start = self.window[0] if self.window else 0
        self.window = (start, start + int(n))
        return self

    # execution ----------------------------------------------------------------
    def _matching(self) -> List[Dict[str, Any]]:
        return [r for r in self.db.rows(self.table) if all(f(r) for f in self.filters)]

    def execute(self) -> Any:
        result = MagicMock()
        if self.op == 'insert':
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            result.data = [self.db.insert(self.table, dict(r)) for r in rows]
        elif self.op == 'update':
            matched = self._matching()
            for row in matched:
                self.db.check_unique(self.table, {**row, **self.payload}, exclude=row)
                row.update(self.payload)
            result.data = [dict(r) for r in matched]
        elif self.op == 'delete':
            matched = self._matching()
            self.db.delete(self.table, matched)
            result.data = [dict(r) for r in matched]
        else:
            rows = self._matching()
            for col, desc in reversed(self.orders):
                rows.sort(key=lambda r, c=col: (r.get(c) is None, str(r.get(c) or '')), reverse=desc)
            total = len(rows)
            if self.window:
                rows = rows[self.window[0]:self.window[1]]
            result.data = [self.db.with_embeds(self.table, dict(r), self.embeds) for r in rows]
            result.count = total
            return result
        result.count = len(result.data)
        return result


class MemoryRpc:
    def __init__(self, handler: Callable[[Dict[str, Any]], Any], params: Dict[str, Any]) -> None:
        self.handler, self.params = handler, params

    def execute(self) -> Any:
        result = MagicMock()
        result.data = self.handler(self.params)
        return result


class MemoryDuplicate(Exception):
    """Mimics postgrest's APIError for a unique violation."""
    code = '23505'


class MemorySupabase:
    """In-memory stand-in for the service-role client: real filtering, unique
    keys and the embeds the run-management module uses. RPCs are Python
    handlers registered by the test (the SQL bodies are covered by the
    Postgres acceptance test)."""

    UNIQUE = {
        'run_groups': lambda r: (str(r.get('team_id')), str(r.get('name') or '').lower()),
        'run_milestones': lambda r: (str(r.get('team_id')), str(r.get('name') or '').lower()),
        'run_label_definitions': lambda r: (str(r.get('team_id')), str(r.get('name') or '').lower()),
        'run_group_rerun_requests': lambda r: (str(r.get('team_id')), r.get('idempotency_key')),
    }

    def __init__(self) -> None:
        self.data: Dict[str, List[Dict[str, Any]]] = {}
        self.rpc_handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {}
        self.rpc_calls: List[Tuple[str, Dict[str, Any]]] = []

    def rows(self, table: str) -> List[Dict[str, Any]]:
        return self.data.setdefault(table, [])

    def seed(self, table: str, *rows: Dict[str, Any]) -> None:
        self.rows(table).extend(dict(r) for r in rows)

    def check_unique(self, table: str, row: Dict[str, Any], exclude: Optional[Dict[str, Any]] = None) -> None:
        key_of = self.UNIQUE.get(table)
        if not key_of:
            return
        key = key_of(row)
        for existing in self.rows(table):
            if existing is not exclude and key_of(existing) == key:
                raise MemoryDuplicate(f'duplicate key value violates unique constraint on {table}')

    def insert(self, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        row.setdefault('id', str(uuid.uuid4()))
        row.setdefault('created_at', '2026-10-03T00:00:00+00:00')
        if table in ('run_groups', 'run_milestones'):
            row.setdefault('archived', False)
            row.setdefault('pinned', False)
        self.check_unique(table, row)
        self.rows(table).append(row)
        return dict(row)

    def delete(self, table: str, matched: List[Dict[str, Any]]) -> None:
        ids = {id(r) for r in matched}
        self.data[table] = [r for r in self.rows(table) if id(r) not in ids]
        if table == 'run_label_definitions':
            gone = {str(r['id']) for r in matched}
            for join in ('script_result_labels', 'testcase_labels'):
                self.data[join] = [r for r in self.rows(join) if str(r.get('run_label_id')) not in gone]

    def embedded(self, table: str, embed: str, row: Dict[str, Any]) -> List[Dict[str, Any]]:
        if table == 'script_results' and embed == 'script_result_labels':
            return [j for j in self.rows('script_result_labels')
                    if str(j.get('script_result_id')) == str(row.get('id'))
                    and str(j.get('team_id')) == str(row.get('team_id'))]
        return []

    def with_embeds(self, table: str, row: Dict[str, Any], columns: str) -> Dict[str, Any]:
        if 'run_label_definitions(' in columns:
            row['run_label_definitions'] = next(
                (dict(d) for d in self.rows('run_label_definitions')
                 if str(d.get('id')) == str(row.get('run_label_id'))), None)
        if 'deployment_executions(' in columns:
            row['deployment_executions'] = [
                {'deployments': {'rerun_payload': d.get('rerun_payload')}}
                for d in self.rows('deployment_executions_view')
                if str(d.get('script_result_id')) == str(row.get('id'))]
        if 'script_result_labels!inner' in columns:
            row['script_result_labels'] = [{'run_label_id': j.get('run_label_id')}
                                           for j in self.embedded(table, 'script_result_labels', row)]
        return row

    def table(self, name: str) -> MemoryQuery:
        return MemoryQuery(self, name)

    def rpc(self, name: str, params: Dict[str, Any]) -> MemoryRpc:
        self.rpc_calls.append((name, dict(params)))
        if name not in self.rpc_handlers:
            raise AssertionError(f'unexpected rpc {name}')
        return MemoryRpc(self.rpc_handlers[name], params)


class FakeHostManager:
    """``host_names`` is an iterable of names, or ``{host: [(device_id, device_name), ...]}``."""

    def __init__(self, host_names: Any) -> None:
        if isinstance(host_names, dict):
            self._hosts = {h: {'host_name': h, 'devices': [{'device_id': d, 'device_name': n} for d, n in devices]}
                           for h, devices in host_names.items()}
        else:
            self._hosts = {h: {'host_name': h} for h in host_names}

    def get_all_hosts(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._hosts)

    def get_host(self, name: str) -> Optional[Dict[str, Any]]:
        return self._hosts.get(name)


def schema_role_defaults() -> Dict[str, List[str]]:
    """Role defaults exactly as a fresh install seeds them: 053_role_catalog.sql
    plus the additions in 062_run_management_permissions.sql."""
    schema_dir = os.path.join(_REPO_ROOT, 'setup', 'db', 'schema')
    with open(os.path.join(schema_dir, '053_role_catalog.sql')) as fh:
        catalog = fh.read()
    roles: Dict[str, List[str]] = {}
    for role, body in re.findall(r"\('(\w+)', '\[(.*?)\]'::jsonb\)", catalog, flags=re.S):
        roles[role] = json.loads('[' + body + ']')
    with open(os.path.join(schema_dir, '062_run_management_permissions.sql')) as fh:
        additions = fh.read()
    for role, body in re.findall(r"WHEN '(\w+)' THEN ARRAY\[(.*?)\]", additions, flags=re.S):
        roles.setdefault(role, [])
        roles[role] = sorted(set(roles[role]) | set(re.findall(r"'([^']+)'", body)))
    return roles


def make_task42_app(
    monkeypatch,
    *,
    blueprints: Iterable[Any],
    data_layer: Optional[Any] = None,
    actor_id: str = 'user-a',
    role: str = 'admin',
    supabase_client: Optional[Any] = None,
    extra_fakes: Optional[Dict[str, Callable[..., Any]]] = None,
    team_ids: Iterable[str] = (TEAM_A,),
    permissions: Iterable[str] = (),
    denied_permissions: Iterable[str] = (),
    team_ceiling: Optional[Iterable[str]] = None,
    role_defaults: Optional[Dict[str, Iterable[str]]] = None,
    registered_hosts: Optional[Iterable[str]] = None,
    host_manager_modules: Iterable[Any] = (),
) -> Tuple[Flask, Any, Dict[str, Any]]:
    """Build a Flask app for a TASK-42 route test.

    Returns ``(app, supabase_client, state)``.

    The before_request mirrors the production /server/* guard in app.py: it
    sets the principal the way auth_middleware does from a JWT (role,
    individual grants/denials, team ceiling, ``team_ids`` claim), then runs the
    real ``enforce_viewer_read_only`` and ``enforce_team_scope``. Permission
    checks run the real ``principal_holds_permission`` against
    ``role_defaults`` (default: the fresh-install role catalog).

    `data_layer` is the patched data module (its ``get_supabase`` returns the
    fake client). `registered_hosts` installs a FakeHostManager on every module
    in `host_manager_modules`. `extra_fakes` maps ``"module:attr"`` or a plain
    attribute of `data_layer` to a replacement.
    """
    from backend_server.src.lib import auth_middleware

    app = Flask(__name__)
    defaults = schema_role_defaults() if role_defaults is None else role_defaults
    monkeypatch.setattr(auth_middleware, '_load_role_defaults',
                        lambda: {r: list(p) for r, p in defaults.items()})
    monkeypatch.setitem(auth_middleware._role_defaults_cache, 'loaded_at', None)

    teams = [str(t) for t in team_ids]

    @app.before_request
    def _principal():
        request.user_id = actor_id
        request.user_email = f'{actor_id}@test.local'
        request.user_role = role
        request.user_permissions = list(permissions)
        request.user_denied_permissions = list(denied_permissions)
        request.user_team_ceiling = None if team_ceiling is None else list(team_ceiling)
        request.user_app_metadata = {'team_ids': teams, 'is_platform_admin': False}
        if not (request.path or '').startswith('/server/'):
            return None
        denied = auth_middleware.enforce_viewer_read_only()
        if denied is not None:
            return denied
        return auth_middleware.enforce_team_scope()

    supabase_client = supabase_client or FakeSupabaseClient()

    if data_layer is not None and monkeypatch is not None:
        monkeypatch.setattr(data_layer, 'get_supabase', lambda: supabase_client)

    if registered_hosts is not None:
        manager = FakeHostManager(registered_hosts)
        for module in host_manager_modules:
            monkeypatch.setattr(module, 'get_host_manager', lambda: manager)

    for name, fake in (extra_fakes or {}).items():
        if ':' in name:
            module_name, attr = name.split(':', 1)
            monkeypatch.setattr(importlib.import_module(module_name), attr, fake)
        elif data_layer is not None:
            monkeypatch.setattr(data_layer, name, fake)

    state: Dict[str, Any] = {
        'supabase': supabase_client,
        'data_layer': data_layer,
        'data_layer_calls': [],
        'extra_fakes': extra_fakes or {},
    }

    for bp in blueprints:
        app.register_blueprint(bp)

    return app, supabase_client, state


@pytest.fixture
def task42_app(monkeypatch):
    """Return a builder with a per-test monkeypatch.

    Tests call::

        def test_x(task42_app):
            app, supabase, state = task42_app.blueprints(server_run_management_bp)
            ...
    """
    class _Builder:
        def blueprints(self, *bps: Any) -> Tuple[Flask, FakeSupabaseClient, Dict[str, Any]]:
            return make_task42_app(monkeypatch, blueprints=bps, extra_fakes={})

    return _Builder()


# Convenience alias — the route test files call it `make_task_app`.
make_task_app = make_task42_app


# Convenience re-exports for legacy call sites in the tests below.

__all__ = [
    'task42_app',
    'FakeChain',
    'FakeSupabaseClient',
    'make_task42_app',
    'make_task_app',
    'load_route_module',
    'TEAM_A',
    'TEAM_B',
    'MemorySupabase',
    'MemoryDuplicate',
    'FakeHostManager',
    'schema_role_defaults',
]