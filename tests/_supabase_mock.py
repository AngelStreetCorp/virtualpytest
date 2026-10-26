"""
Minimal in-memory Supabase client mock for unit tests (TASK-65 G1–G4).

Supports the chainable query interface used by `projects_db` and the project
overview / executive route modules:

  sb.table('foo')                    -> table handle
       .select('*') / .select('col,col') -> projection
       .eq('col', val)                -> equality filter
       .in_('col', [...])             -> IN filter
       .order('col', desc=True/False) -> order
       .limit(n)                      -> head limit
       .single()                      -> expects exactly one row
       .insert({...})                 -> row insert
       .update({...})                 -> row update (chained with .eq())
       .upsert({...})                 -> row upsert
       .delete()                      -> row delete (chained with .eq() / .in_())
       .execute()                     -> returns _Result(data, count)

Use the `make_supabase_mock(initial)` helper to bootstrap a mock with seed data
shaped like the real tables, then call `mod._supabase = lambda: mock` (or
monkey-patch the right import) inside a test.

The mock mirrors the real Supabase client's behaviour for the operators we use
in `projects_db`, `server_projects_overview_routes`, and
`server_projects_executive_routes`. It's intentionally NOT a full ORM — just
enough to make those modules work in tests.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import re


def _coerce(val: str) -> Any:
    if val == 'null':
        return None
    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    return val


class _NotBuilder:
    """Returned by `_Query.not_(col, op, val)`. Exposes `is_()` which is the
    only operator we need in the overview / executive modules today.

    Example real-world usage in our code:
        sb.table('script_results').select('...').not_.is_('device_name', 'null')
    """

    def __init__(self, query: '_Query', col: str, op: str, val: Any) -> None:
        self._query = query
        self._col = col
        self._op = op
        self._val = val

    def is_(self, col: str, val: Any) -> '_Query':
        # In real supabase-py this is `is_(col, val)` where val is the target
        # value (or 'null' string). We treat the `_col / _op / _val` from the
        # outer `.not_(...)` as documentation only and apply the IS filter.
        if val == 'null':
            self._query._filters.append(('is', (col, None)))
        else:
            self._query._filters.append(('is', (col, val)))
        return self._query

    def ilike(self, col: str, pattern: str) -> '_Query':
        # No real client users in the modules under test; just route to ilike.
        self._query._filters.append(('ilike', (col, pattern)))
        return self._query


class _Result:
    def __init__(self, data: List[Dict[str, Any]], count: Optional[int] = None) -> None:
        self.data = data
        self.count = count


class _Query:
    """Single fluent query handle. Build a SELECT, then run .execute()."""

    def __init__(self, client: 'SupabaseMock', table: str) -> None:
        self.client = client
        self.table = table
        self._op: str = 'select'
        self._payload: Optional[Dict[str, Any]] = None
        self._filters: List[Tuple[str, Any]] = []  # (op, [args])
        self._order: Optional[Tuple[str, bool]] = None
        self._limit: Optional[int] = None
        self._range: Optional[Tuple[int, int]] = None
        self._want_single: bool = False
        self._want_count: bool = False
        self._projection: str = '*'
        # When the previous `.not_` property was accessed, the next filter
        # operator should be wrapped in a `not` (IS NOT, NOT IN, etc.). This
        # mirrors `BaseFilterRequestBuilder.not_` in supabase-py 2.x.
        self._negate_next: bool = False

    @property
    def not_(self) -> '_Query':
        """Mirror of supabase-py's `BaseFilterRequestBuilder.not_` property:
        sets `negate_next = True` and returns the same query handle so that
        `.not_.is_(col, val)` works as a chainable."""
        self._negate_next = True
        return self

    # -- chainable operators ----------------------------------------------
    def select(self, cols: str = '*', count: Optional[str] = None) -> '_Query':
        self._op = 'select'
        self._projection = cols
        if count == 'exact':
            self._want_count = True
        return self

    def eq(self, col: str, val: Any) -> '_Query':
        self._filters.append(('eq', (col, val)))
        return self

    def neq(self, col: str, val: Any) -> '_Query':
        self._filters.append(('neq', (col, val)))
        return self

    def in_(self, col: str, vals: List[Any]) -> '_Query':
        self._filters.append(('in', (col, list(vals))))
        return self

    def gte(self, col: str, val: Any) -> '_Query':
        self._filters.append(('gte', (col, val)))
        return self

    def gt(self, col: str, val: Any) -> '_Query':
        self._filters.append(('gt', (col, val)))
        return self

    def lt(self, col: str, val: Any) -> '_Query':
        self._filters.append(('lt', (col, val)))
        return self

    def lte(self, col: str, val: Any) -> '_Query':
        self._filters.append(('lte', (col, val)))
        return self

    def is_(self, col: str, val: Any) -> '_Query':
        """Mock for the supabase-py `.is_('col', 'null')` chainable. When
        preceded by `.not_`, the filter is recorded as `is_not`."""
        if self._negate_next:
            self._negate_next = False
            self._filters.append(('is_not', (col, None if val == 'null' else val)))
            return self
        if val == 'null':
            self._filters.append(('is', (col, None)))
        else:
            self._filters.append(('is', (col, val)))
        return self

    def or_(self, filters: str) -> '_Query':
        """Naive mock for `.or_('col1.eq.val,col2.eq.val')`. The overview /
        executive modules don't use it today, but the chainable is here so we
        can add tests later without a mock upgrade."""
        for f in filters.split(','):
            f = f.strip()
            # `col.op.val` form
            if '.eq.' in f:
                col, _, val = f.partition('.eq.')
                self._filters.append(('eq', (col, _coerce(val))))
        return self

    def order(self, col: str, desc: bool = False) -> '_Query':
        self._order = (col, desc)
        return self

    def limit(self, n: int) -> '_Query':
        self._limit = n
        return self

    def range(self, start: int, end: int) -> '_Query':
        """Mirror of supabase-py's `.range(start, end)` chainable (used by
        `chunked_in` to page through > MAX_ROWS_PER_REQUEST rows). The mock
        is in-memory and the test data is tiny, so we just record the slice
        bounds; `_exec_select` honours `_limit` only today. Future tests can
        extend the slicing logic if they exceed the small limit.
        """
        self._range = (start, end)
        if self._limit is None:
            self._limit = end - start + 1
        return self

    def single(self) -> '_Query':
        self._want_single = True
        return self

    def insert(self, payload: Dict[str, Any]) -> '_Query':
        self._op = 'insert'
        self._payload = payload
        return self

    def upsert(self, payload: Dict[str, Any]) -> '_Query':
        self._op = 'upsert'
        self._payload = payload
        return self

    def update(self, payload: Dict[str, Any]) -> '_Query':
        self._op = 'update'
        self._payload = payload
        return self

    def delete(self) -> '_Query':
        self._op = 'delete'
        return self

    # -- terminal ---------------------------------------------------------
    def execute(self) -> _Result:
        if self._op == 'select':
            return self._exec_select()
        if self._op == 'insert':
            return self._exec_insert()
        if self._op == 'upsert':
            return self._exec_upsert()
        if self._op == 'update':
            return self._exec_update()
        if self._op == 'delete':
            return self._exec_delete()
        raise RuntimeError(f"unknown op: {self._op}")

    # -- helpers ----------------------------------------------------------
    def _matches(self, row: Dict[str, Any]) -> bool:
        for op, args in self._filters:
            if op == 'eq' and row.get(args[0]) != args[1]:
                return False
            if op == 'neq' and row.get(args[0]) == args[1]:
                return False
            if op == 'in' and row.get(args[0]) not in args[1]:
                return False
            if op == 'gte' and not (row.get(args[0]) is not None and row.get(args[0]) >= args[1]):
                return False
            if op == 'gt' and not (row.get(args[0]) is not None and row.get(args[0]) > args[1]):
                return False
            if op == 'lt' and not (row.get(args[0]) is not None and row.get(args[0]) < args[1]):
                return False
            if op == 'lte' and not (row.get(args[0]) is not None and row.get(args[0]) <= args[1]):
                return False
            if op == 'is' and row.get(args[0]) is not args[1]:
                return False
            if op == 'is_not' and row.get(args[0]) is args[1]:
                return False
        return True

    def _project(self, columns: str) -> List[str]:
        """Split a projection string on commas, respecting parens.

        Naive `s.split(',')` breaks `tags(name, color)` into three pieces.
        Real Supabase splits at the top-level commas only; we walk char-by-char
        to honor one level of parens. Single quoted strings aren't needed
        today — column and relation names are bare identifiers.
        """
        cols: List[str] = []
        depth = 0
        buf: List[str] = []
        for ch in columns or '':
            if ch == ',' and depth == 0:
                token = ''.join(buf).strip()
                if token:
                    cols.append(token)
                buf = []
                continue
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth = max(0, depth - 1)
            buf.append(ch)
        tail = ''.join(buf).strip()
        if tail:
            cols.append(tail)
        return cols

    def _project_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        if self._projection == '*':
            return row
        cols = self._project(self._projection)
        out: Dict[str, Any] = {}
        for c in cols:
            is_embed = '.' in c or '(' in c
            if is_embed:
                # Embedded relation: `tags(name, color)` / `profile:profiles(id, display_name)`.
                # Real Supabase returns the joined object under the relation
                # NAME (the part before the optional `:` alias or `(`), so put
                # it under both: the relation name (so `row.get('tags')`
                # works) and the literal key (so older tests that key off the
                # full projection string still find it).
                relation = c.split(':', 1)[0].split('(', 1)[0].strip()
                if relation in row:
                    embedded = row[relation]
                elif c in row:
                    embedded = row[c]
                else:
                    embedded = None
                out[relation] = embedded
                if c != relation:
                    out[c] = embedded
            else:
                out[c] = row.get(c)
        return out

    def _exec_select(self) -> _Result:
        rows = [r for r in self.client._tables.get(self.table, []) if self._matches(r)]
        # Order
        if self._order:
            col, desc = self._order
            rows.sort(key=lambda r, c=col: r.get(c) or '', reverse=desc)
        # Limit
        if self._limit is not None:
            rows = rows[: self._limit]
        # Range (.range(start, end) is inclusive on both ends in PostgREST;
        # slice is end-exclusive so we add 1)
        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1]
        # Project
        rows = [self._project_row(r) for r in rows]
        # Single
        if self._want_single:
            if not rows:
                return _Result(data=[])
            if len(rows) > 1:
                # Real Supabase raises here; tests shouldn't hit this without
                # setting it up deliberately.
                return _Result(data=rows[0], count=1)
            return _Result(data=rows[0], count=1)
        if self._want_count:
            return _Result(data=rows, count=len(rows))
        return _Result(data=rows)

    def _exec_insert(self) -> _Result:
        if self._payload is None:
            raise RuntimeError("insert without payload")
        # honour unique-violation simulation via client._unique_violations
        uvs = self.client._unique_violations.get(self.table, [])
        for col, val in uvs:
            for existing in self.client._tables.get(self.table, []):
                if existing.get(col) == val:
                    raise RuntimeError(
                        f"duplicate key value violates unique constraint "
                        f"(simulated) table={self.table} col={col}"
                    )
        # Auto-generate `id` if the payload didn't supply one (real Supabase
        # does this server-side via the `id uuid default gen_random_uuid()`
        # default declared in the migrations).
        row = dict(self._payload)
        if row.get('id') is None:
            import uuid as _uuid
            row['id'] = str(_uuid.uuid4())
        self.client._tables.setdefault(self.table, []).append(row)
        return _Result(data=[row])

    def _exec_upsert(self) -> _Result:
        # naive upsert: look for matching row by primary key / all cols; insert if absent
        if self._payload is None:
            raise RuntimeError("upsert without payload")
        target = self.client._tables.setdefault(self.table, [])
        if 'id' in self._payload and self._payload['id'] is not None:
            for i, row in enumerate(target):
                if row.get('id') == self._payload['id']:
                    target[i] = dict(self._payload)
                    return _Result(data=[dict(self._payload)])
        target.append(dict(self._payload))
        return _Result(data=[dict(self._payload)])

    def _exec_update(self) -> _Result:
        if self._payload is None:
            raise RuntimeError("update without payload")
        out: List[Dict[str, Any]] = []
        for i, row in enumerate(self.client._tables.get(self.table, [])):
            if self._matches(row):
                row.update(self._payload)
                out.append(dict(row))
        return _Result(data=out)

    def _exec_delete(self) -> _Result:
        out: List[Dict[str, Any]] = []
        keep: List[Dict[str, Any]] = []
        for row in self.client._tables.get(self.table, []):
            if self._matches(row):
                out.append(dict(row))
            else:
                keep.append(row)
        self.client._tables[self.table] = keep
        return _Result(data=out)


class SupabaseMock:
    """In-memory Supabase client for unit tests."""

    def __init__(self, initial: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> None:
        # Deep copy the seed so each test starts from a clean state.
        import copy
        self._tables: Dict[str, List[Dict[str, Any]]] = {
            k: [copy.deepcopy(r) for r in rows]
            for k, rows in (initial or {}).items()
        }
        # Columns that should raise a unique-violation on insert (for tests
        # of the duplicate-name path in create_project).
        self._unique_violations: Dict[str, List[Tuple[str, Any]]] = {}
        # Index names observed during `apply_migration_sql` (informational; the
        # mock doesn't model index lookups separately from column filters).
        self._indexes: Dict[str, List[str]] = {}

    def table(self, name: str) -> _Query:
        if name not in self._tables:
            # The real client would error; we lazily create an empty table so
            # SELECTs return [] and INSERTs work.
            self._tables[name] = []
        return _Query(self, name)

    def seed_unique_violation(self, table: str, col: str, val: Any) -> None:
        """Simulate a UNIQUE constraint violation on the next insert into
        `table` that has `col == val`."""
        self._unique_violations.setdefault(table, []).append((col, val))

    def get_table(self, name: str) -> List[Dict[str, Any]]:
        """Test-only: read the current rows of a table."""
        return list(self._tables.get(name, []))


# ---------------------------------------------------------------------------
# Seed builders for the projects / projects_tags / projects_members /
# script_results / team_members / profiles / tags / ai_usage_stats /
# executable_tags tables that G1-G4 endpoints read.
# ---------------------------------------------------------------------------
def make_projects_seed() -> Dict[str, List[Dict[str, Any]]]:
    """Return a seed that mirrors the state the 3 migration SQLs create.

    Each row is intentionally minimal — the G1-G4 helpers only read the
    columns they need. Tests can add their own rows on top.
    """
    import uuid
    team_id = str(uuid.uuid4())
    owner_tm_id = str(uuid.uuid4())
    viewer_tm_id = str(uuid.uuid4())
    p1 = str(uuid.uuid4())
    p2 = str(uuid.uuid4())
    tag1 = 1
    tag2 = 2
    return {
        'projects': [
            {
                'id': p1,
                'team_id': team_id,
                'name': 'Web app',
                'description': 'main web product',
                'color': '#d4a574',
                'created_by': owner_tm_id,
                'created_at': '2026-09-01T00:00:00+00:00',
            },
            {
                'id': p2,
                'team_id': team_id,
                'name': 'Mobile app',
                'description': None,
                'color': '#22c55e',
                'created_by': owner_tm_id,
                'created_at': '2026-09-02T00:00:00+00:00',
            },
        ],
        'projects_tags': [
            {'project_id': p1, 'tag_id': tag1},
            {'project_id': p2, 'tag_id': tag2},
        ],
        'projects_members': [
            {'project_id': p1, 'team_member_id': owner_tm_id, 'role': 'owner', 'created_at': '2026-09-01T00:00:00+00:00'},
            {'project_id': p1, 'team_member_id': viewer_tm_id, 'role': 'viewer', 'created_at': '2026-09-02T00:00:00+00:00'},
            {'project_id': p2, 'team_member_id': owner_tm_id, 'role': 'owner', 'created_at': '2026-09-03T00:00:00+00:00'},
        ],
        'team_members': [
            {
                'id': owner_tm_id,
                'user_id': 'user-1',
                'team_id': team_id,
                'profile': {'id': 'user-1', 'display_name': 'Owner One', 'email': 'owner1@example.com'},
            },
            {
                'id': viewer_tm_id,
                'user_id': 'user-2',
                'team_id': team_id,
                'profile': {'id': 'user-2', 'display_name': 'Viewer Two', 'email': 'viewer2@example.com'},
            },
        ],
        'tags': [
            {'tag_id': tag1, 'name': 'web_app', 'color': '#d4a574'},
            {'tag_id': tag2, 'name': 'mobile_app', 'color': '#22c55e'},
        ],
        # script_results rows are added per test
        'script_results': [],
        # ai_usage_stats rows are added per test
        'ai_usage_stats': [],
        'executable_tags': [
            {'executable_type': 'script', 'executable_id': 's_web_1', 'tag_id': tag1},
            {'executable_type': 'script', 'executable_id': 's_web_2', 'tag_id': tag1},
            {'executable_type': 'script', 'executable_id': 's_mob_1', 'tag_id': tag2},
        ],
        # Convenience handle: tests can look up the canonical ids
        '_meta': [
            {'team_id': team_id, 'p1': p1, 'p2': p2, 'owner_tm_id': owner_tm_id, 'viewer_tm_id': viewer_tm_id, 'tag1': tag1, 'tag2': tag2},
        ],
    }


def get_meta(seed: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    return seed['_meta'][0]


# ---------------------------------------------------------------------------
# Migration SQL applier (TASK-65 G5 in-memory)
# ---------------------------------------------------------------------------
#
# This applier is the "in-memory equivalent" of running the 3 blueprint
# migrations on a real Supabase project. It parses each file with the same
# strip-comments pass `scripts/check_projects_migrations.py` uses, then walks
# the SQL statement-by-statement and applies the operators the G1–G5 code
# actually depends on:
#
#   CREATE TABLE          -> create an empty list under `client._tables[name]`
#   ALTER TABLE ADD COLUMN-> extend every row in the existing table with the
#                            new column (default = None) so reads don't KeyError
#   CREATE INDEX          -> no-op (the mock's row scans honour the equivalent
#                            filters; we record the name in client._indexes for
#                            the migration check to verify presence)
#   CREATE OR REPLACE FUNCTION -> no-op (functions aren't exercised in memory)
#   GRANT / POLICY        -> no-op (RLS isn't enforced in the in-memory mock)
#
# Anything we don't understand is logged and skipped — the goal is to verify
# the G1–G5 helpers run correctly against a state that mirrors the live DB
# after apply, not to re-implement Postgres.
def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r'--[^\n]*', '', sql)
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    return sql


def apply_migration_sql(client: 'SupabaseMock', sql: str) -> dict:
    """Apply a TASK-65 migration file to a `SupabaseMock` in memory.

    Returns a dict with `tables_created`, `columns_added`, `indexes_created`,
    `statements_seen`, `statements_skipped` for tests to assert on.
    """
    sql = _strip_sql_comments(sql)
    out = {
        'tables_created': [],
        'columns_added': [],
        'indexes_created': [],
        'statements_seen': 0,
        'statements_skipped': 0,
    }
    # Split on `;` at statement level; ignore empty trailing pieces.
    # The mock doesn't model the full Postgres grammar, so we look for the
    # specific operators we care about and skip the rest (BEGIN/COMMIT,
    # COMMENT ON, ALTER TABLE ... ADD CONSTRAINT, GRANT, etc.).
    for raw_stmt in sql.split(';'):
        stmt = raw_stmt.strip()
        if not stmt:
            continue
        out['statements_seen'] += 1
        upper = stmt.upper()
        # CREATE TABLE
        m = re.match(
            r'CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+(?:public\.)?(\w+)\s*\((.*)\)\s*$',
            stmt, re.IGNORECASE | re.DOTALL,
        )
        if m:
            table = m.group(1)
            body = m.group(2)
            client._tables.setdefault(table, [])
            if table not in out['tables_created']:
                out['tables_created'].append(table)
            # Capture declared columns so the test can verify what was added.
            for col_m in re.finditer(
                r'\b(\w+)\s+(?:UUID|TEXT|INTEGER|BIGINT|TIMESTAMPTZ|BOOLEAN|JSONB|'
                r'UUID\[\]|TIMESTAMP(?:\s+WITH(?:OUT)?\s+TIME\s+ZONE)?)\b',
                body, re.IGNORECASE,
            ):
                col = col_m.group(1).lower()
                if col.upper() in ('CONSTRAINT', 'PRIMARY', 'FOREIGN', 'CHECK', 'UNIQUE'):
                    continue
                if (table, col) not in out['columns_added']:
                    out['columns_added'].append((table, col))
            continue
        # ALTER TABLE ... ADD COLUMN
        m = re.match(
            r'ALTER\s+TABLE\s+(?:public\.)?(\w+)\s+(?:ADD\s+COLUMN(?:\s+IF\s+NOT\s+EXISTS)?|'
            r'ALTER\s+COLUMN)\s+(\w+)\b',
            stmt, re.IGNORECASE,
        )
        if m:
            table = m.group(1)
            col = m.group(2).lower()
            # Mirror the real DB's behaviour: an ALTER TABLE on a non-existent
            # table would error. In the in-memory mock we lazily create the
            # table so the apply_migration path is permissive for blueprints
            # (this is a test-time convenience, not a runtime invariant).
            client._tables.setdefault(table, [])
            for row in client._tables.get(table, []):
                row.setdefault(col, None)
            if (table, col) not in out['columns_added']:
                out['columns_added'].append((table, col))
            continue
        # CREATE INDEX
        m = re.match(
            r'CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+'
            r'(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?(\w+)\s+ON\b',
            stmt, re.IGNORECASE,
        )
        if m:
            idx_name = m.group(1)
            client._indexes.setdefault(m.group(0), []).append(idx_name)
            if idx_name not in out['indexes_created']:
                out['indexes_created'].append(idx_name)
            continue
        # Unknown operator -> skip. Most of these are BEGIN/COMMIT, COMMENT,
        # GRANT, CREATE OR REPLACE FUNCTION, ALTER TABLE ADD CONSTRAINT,
        # CREATE TRIGGER — none of which the in-memory helpers care about.
        out['statements_skipped'] += 1
    return out
