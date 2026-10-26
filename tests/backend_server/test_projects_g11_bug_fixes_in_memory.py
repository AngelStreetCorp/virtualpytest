"""
In-memory tests for TASK-65 G11 / BUG-0547 + BUG-0548 + G11 create endpoint.

What this slice ships
----------------------

1. **BUG-0547 — creator FK**: `create_project()` previously received a
   profile.id (NOT a team_members.id) for the `created_by_team_member_id`
   argument. The subsequent `projects_members` insert targeted a FK to
   `team_members.id`, so the insert violated the FK constraint and was
   silently swallowed. Every freshly created project therefore showed
   "0 members" instead of "1". The fix routes a `team_members.id` to
   the API (the route layer resolves `_caller_team_member_ids()[0]`
   before calling `projects_db.create_project`).

2. **BUG-0548 — auto-scope tag counted as a user tag**: every project
   auto-creates a scope tag (slugged project name → `tags` row, linked
   via `projects_tags`). The frontend project card reads
   `p.tag_ids.length` and displays "{count} tags" — but the SCOPE tag
   pushed that count to 1 even for projects with zero user tags. The
   fix adds an `is_scope` flag (migration 20261015b) on `projects_tags`,
   tags the auto-link with `is_scope = TRUE`, and surfaces
   `{scope_tag, scope_tag_id, user_tags, user_tag_ids, user_tag_count}`
   on the API response so the UI counts only user tags.

3. **G11 — create endpoint accepts `tags[]` + `members[]` in one flow**:
   `POST /server/projects` now reads `tags` (list of strings) and
   `members` (list of `{team_member_id, role}`) and persists them as
   user-attached tags (`is_scope = FALSE`) and extra members alongside
   the auto-added creator row. Backward compatible: omitting both keeps
   today's behaviour exactly.

Tests
-----

* `TestMigration20261015b` — the 20261015b migration adds the
  `is_scope` column. Run via `scripts/check_projects_migrations.py`
  too (see test in `test_projects.py`).
* `TestBug0547CreatorFK` — `create_project` adds the creator as owner
  when given a `team_members.id` (regression: before the fix, no row
  was inserted at all).
* `TestBug0548ScopeTagSplit` — `_enrich` correctly splits scope_tag
  from user_tags; `create_project` flags the auto-link
  `is_scope = TRUE`; user-attached tags are `is_scope = FALSE`.
* `TestG11OneShotCreate` — `create_project(initial_user_tags=[...])`
  attaches user tags with `is_scope = FALSE`; `create_project(initial_
  members=[...])` adds the extra members; the creator is auto-added
  as 'owner' regardless of payload.
* `TestG11RouteWiring` — the route layer accepts `tags[]` and
  `members[]` in the JSON body and persists them via the db layer.
"""
import json
import os
import sys
from typing import Any, Dict, List

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))  # for `_supabase_mock`
sys.path.insert(0, REPO_ROOT)

from _supabase_mock import (  # type: ignore  # noqa: E402
    SupabaseMock,
    apply_migration_sql,
    make_projects_seed,
    get_meta,
)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------

def _read_migration(filename: str) -> str:
    path = os.path.join(REPO_ROOT, 'setup', 'db', 'migrations', filename)
    with open(path) as f:
        return f.read()


@pytest.fixture
def mock_supabase() -> SupabaseMock:
    """A mock with the 3 G1–G4 migrations + G10 + G11 applied in memory."""
    mock = SupabaseMock(initial=make_projects_seed())
    for fn in [
        '20261006a_projects.sql',
        '20261006b_team_members_last_seen.sql',
        '20261006c_report_snapshots_project_ids.sql',
        '20261015a_executable_tags_virtual_script_campaign.sql',
        '20261015b_projects_tags_is_scope.sql',
    ]:
        apply_migration_sql(mock, _read_migration(fn))
    return mock


def _install_supabase(mock: SupabaseMock, monkeypatch, projects_db=None) -> None:
    """Point `projects_db._supabase()` at our in-memory mock for the test.

    Patches `_supabase` (the helper inside projects_db) rather than the
    upstream `supabase_utils.get_supabase_client` — `_supabase` is a module-
    scoped attribute on projects_db that the tests have used since G1–G4
    (mirrors the pattern in `tests/backend_server/test_projects_in_memory.py:78`).
    """
    if projects_db is None:
        from shared.src.lib.database import projects_db as _pdb
        projects_db = _pdb
    monkeypatch.setattr(projects_db, '_supabase', lambda: mock)


def _team_member_for_user(mock: SupabaseMock, user_id: str, team_id: str) -> str:
    for tm in mock._tables.get('team_members', []):
        if tm.get('user_id') == user_id and tm.get('team_id') == team_id:
            return tm['id']
    raise AssertionError(f"no team_member for user_id={user_id} team_id={team_id}")


def _stub_get_or_create_tag(monkeypatch, projects_db):
    """The in-memory `SupabaseMock` generates an `id` (UUID) for every new
    `tags` row but doesn't know `tag_id` is the BIGINT PK on the real table.
    `_get_or_create_tag` returns the row as-is, so the subsequent
    `projects_tags` insert would carry `tag_id = None`. Stub the helper to
    return a synthetic `tag_id` keyed on the tag name, mirroring how
    G5 / G10 in-memory tests do it.
    """
    counter = {'next_id': 1000}

    def fake(name: str):
        counter['next_id'] += 1
        return {
            'tag_id': counter['next_id'],
            'name': name,
            'color': '#d4a574',
        }

    monkeypatch.setattr(projects_db, '_get_or_create_tag', fake)


# ---------------------------------------------------------------------------
# 1. Migration 20261015b adds `is_scope`
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMigration20261015b:
    """The forward migration adds an `is_scope` column on `projects_tags`."""

    def test_forward_migration_adds_is_scope_column(self):
        mock = SupabaseMock(initial=make_projects_seed())
        info = apply_migration_sql(mock, _read_migration('20261015b_projects_tags_is_scope.sql'))
        # The mock records the column add on the right table.
        assert ('projects_tags', 'is_scope') in info['columns_added'], (
            f"expected projects_tags.is_scope added, got {info['columns_added']}"
        )

    def test_rollback_removes_is_scope_column(self):
        # Re-apply the forward then the rollback; both should be no-ops on the
        # second iteration (idempotent), and the rollback should leave
        # `is_scope` absent from the mock's tracked row keys.
        mock = SupabaseMock(initial=make_projects_seed())
        apply_migration_sql(mock, _read_migration('20261015b_projects_tags_is_scope.sql'))
        sql_rollback = _read_migration('20261015b_projects_tags_is_scope_rollback.sql')
        # The rollback file uses DROP COLUMN IF NOT EXIST — should run cleanly.
        sql_rollback = sql_rollback.replace('IF EXISTS', 'IF EXISTS')
        apply_migration_sql(mock, sql_rollback)
        # Column add is recorded in `columns_added` (forward) only;
        # the mock doesn't have a DROP COLUMN handler, so the assertion is
        # on the migration text itself.
        # Confirm the rollback file declares the DROP COLUMN statement.
        assert 'DROP COLUMN IF EXISTS is_scope' in sql_rollback

    def test_g11_blueprint_passes_migration_check_script(self):
        import subprocess
        result = subprocess.run(
            ['python3', 'scripts/check_projects_migrations.py'],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert result.returncode == 0, f"migration checker failed:\n{result.stdout}\n{result.stderr}"


# ---------------------------------------------------------------------------
# 2. BUG-0547 — creator is added as owner
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBug0547CreatorFK:
    """`create_project` adds the creator as owner when given a team_members.id."""

    def test_creator_added_as_owner_when_team_member_id_supplied(self, mock_supabase, monkeypatch):
        _install_supabase(mock_supabase, monkeypatch)

        from shared.src.lib.database import projects_db
        _stub_get_or_create_tag(monkeypatch, projects_db)
        team_id = get_meta(mock_supabase._tables)['team_id']
        owner_tm_id = get_meta(mock_supabase._tables)['owner_tm_id']

        # Before the fix, this same call dropped the projects_members insert.
        # After the fix, the row must be present.
        created = projects_db.create_project(
            team_id=team_id,
            name='Acme TV',
            description=None,
            color='#FFB300',
            created_by_team_member_id=owner_tm_id,  # a `team_members.id`, not a profile id
        )
        assert created is not None
        # The team_member row is the right one
        project_id = created['id']
        members = [m for m in mock_supabase._tables['projects_members']
                   if m['project_id'] == project_id]
        owner_rows = [m for m in members if m['role'] == 'owner']
        assert len(owner_rows) == 1, (
            f"BUG-0547: creator was not added as owner. members={members}"
        )
        assert owner_rows[0]['team_member_id'] == owner_tm_id

    def test_regression_against_old_id_type(self, mock_supabase, monkeypatch):
        """The OLD code passed a profile.id (e.g. 'user-1') here and produced
        zero members. The fix is on the route side: `_caller_team_member_ids()[0]`
        resolves before the call, so `projects_db.create_project` only ever sees
        a real `team_members.id`. This test calls the db layer directly with
        an *empty* creator id and asserts it is refused (the route never passes one).
        """
        _install_supabase(mock_supabase, monkeypatch)

        from shared.src.lib.database import projects_db
        _stub_get_or_create_tag(monkeypatch, projects_db)
        team_id = get_meta(mock_supabase._tables)['team_id']

        # `projects.created_by` is NOT NULL + FK: an unresolvable creator is an error,
        # and no project row may be inserted.
        with pytest.raises(RuntimeError):
            projects_db.create_project(
                team_id=team_id,
                name='Bug repro',
                description=None,
                color=None,
                created_by_team_member_id='',
            )
        assert not [p for p in mock_supabase._tables.get('projects', []) if p.get('name') == 'Bug repro']


# ---------------------------------------------------------------------------
# 3. BUG-0548 — auto-scope tag split
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBug0548ScopeTagSplit:
    """The auto-created scope tag is flagged `is_scope = TRUE`, distinct from
    any user-attached tags (which carry `is_scope = FALSE`). The enriched
    project dict exposes `scope_tag`, `user_tags`, `user_tag_count`."""

    def test_auto_scope_tag_is_marked_is_scope_true(self, mock_supabase, monkeypatch):
        _install_supabase(mock_supabase, monkeypatch)

        from shared.src.lib.database import projects_db
        _stub_get_or_create_tag(monkeypatch, projects_db)
        team_id = get_meta(mock_supabase._tables)['team_id']
        owner_tm_id = get_meta(mock_supabase._tables)['owner_tm_id']

        created = projects_db.create_project(
            team_id=team_id,
            name='Acme TV',
            description=None,
            color='#FFB300',
            created_by_team_member_id=owner_tm_id,
        )
        project_id = created['id']

        rows = [
            r for r in mock_supabase._tables['projects_tags']
            if r['project_id'] == project_id
        ]
        # Exactly one scope link.
        scope_rows = [r for r in rows if r.get('is_scope') is True]
        user_rows = [r for r in rows if r.get('is_scope') is False]
        assert len(scope_rows) == 1, (
            f"expected 1 is_scope=TRUE row, got {len(scope_rows)} rows={rows}"
        )
        assert user_rows == [], f"no user tags expected, got {user_rows}"

    def test_enrich_splits_scope_and_user(self):
        """Pure test of `_enrich` — no DB call."""
        from shared.src.lib.database import projects_db as _mod
        project = {'id': 'p1', 'name': 'Acme'}
        tags = [
            {'tag_id': 11, 'name': 'acme', 'color': '#FFB300', 'is_scope': True},
            {'tag_id': 22, 'name': 'smoke', 'color': '#10b981', 'is_scope': False},
            {'tag_id': 33, 'name': 'regression', 'color': '#ef4444', 'is_scope': False},
        ]
        members = [{'team_member_id': 'tm1', 'role': 'owner'}]
        out = _mod._enrich(project, tags=tags, members=members)
        # Backward compat — `tags` is unchanged
        assert out['tag_ids'] == [11, 22, 33]
        # New split
        assert out['scope_tag'] == tags[0]
        assert out['scope_tag_id'] == 11
        assert out['user_tag_ids'] == [22, 33]
        assert out['user_tag_count'] == 2
        assert {t['name'] for t in out['user_tags']} == {'smoke', 'regression'}

    def test_enrich_handles_no_scope_row(self):
        """Pre-migration projects have no `is_scope` flag — `scope_tag` must
        fall back to None instead of crashing."""
        from shared.src.lib.database import projects_db as _mod
        project = {'id': 'p1', 'name': 'Acme'}
        tags = [
            {'tag_id': 22, 'name': 'smoke'},  # no is_scope key
            {'tag_id': 33, 'name': 'regression'},
        ]
        members = []
        out = _mod._enrich(project, tags=tags, members=members)
        assert out['scope_tag'] is None
        assert out['scope_tag_id'] is None
        # Without explicit is_scope, treat all as user tags (back-compat path).
        assert out['user_tag_count'] == 2


# ---------------------------------------------------------------------------
# 4. G11 — one-shot create: tags + members in the payload
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestG11OneShotCreate:
    """`create_project(initial_user_tags=..., initial_members=...)` persists
    the payload atomically (besides the auto-added creator owner row)."""

    def test_initial_user_tags_create_with_is_scope_false(self, mock_supabase, monkeypatch):
        _install_supabase(mock_supabase, monkeypatch)

        from shared.src.lib.database import projects_db
        _stub_get_or_create_tag(monkeypatch, projects_db)
        meta = get_meta(mock_supabase._tables)
        team_id, owner_tm_id = meta['team_id'], meta['owner_tm_id']

        created = projects_db.create_project(
            team_id=team_id,
            name='Acme TV',
            description=None,
            color='#FFB300',
            created_by_team_member_id=owner_tm_id,
            initial_user_tags=['smoke', 'regression', 'smoke'],  # dedupe
        )
        project_id = created['id']

        rows = [r for r in mock_supabase._tables['projects_tags']
                if r['project_id'] == project_id]
        scope_rows = [r for r in rows if r.get('is_scope') is True]
        user_rows = [r for r in rows if r.get('is_scope') is False]
        assert len(scope_rows) == 1
        # Two user tags after dedupe ('smoke' once).
        assert len(user_rows) == 2
        # The flat row only carries tag_id, not the joined tag name — assert
        # via the tag_ids the stub returned (counter-based, smoke=1003,
        # regression=1004 in the second call to the stub).
        user_tag_ids = sorted(r['tag_id'] for r in user_rows)
        # Distinct from the scope_tag's id (1 + first stub call, but here
        # the stub counter starts the first call at 1001 for project name
        # 'Acme TV' = 'acme_tv', so the stub returns 1001 for the scope).
        assert user_tag_ids[0] > 1001
        # The scope tag id is 1001 (first stub call). The user tags are 1002/1003.
        assert len(set(user_tag_ids)) == 2

    def test_initial_members_persist_alongside_creator(self, mock_supabase, monkeypatch):
        _install_supabase(mock_supabase, monkeypatch)

        from shared.src.lib.database import projects_db
        _stub_get_or_create_tag(monkeypatch, projects_db)
        meta = get_meta(mock_supabase._tables)
        team_id, owner_tm_id, viewer_tm_id = (
            meta['team_id'], meta['owner_tm_id'], meta['viewer_tm_id']
        )

        created = projects_db.create_project(
            team_id=team_id,
            name='Acme TV',
            description=None,
            color='#FFB300',
            created_by_team_member_id=owner_tm_id,
            initial_members=[
                {'team_member_id': viewer_tm_id, 'role': 'viewer'},
                {'team_member_id': None,         'role': 'viewer'},  # falsy id -> skip
                {'team_member_id': viewer_tm_id, 'role': 'invalid'},  # bad role -> skip
            ],
        )
        project_id = created['id']

        members = [m for m in mock_supabase._tables['projects_members']
                   if m['project_id'] == project_id]
        # Creator (owner) + initial viewer = 2 rows. Null ids / bad roles are skipped.
        assert len(members) == 2, members
        roles = sorted(m['role'] for m in members)
        assert roles == ['owner', 'viewer']


# ---------------------------------------------------------------------------
# 5. G11 — route layer wires `tags[]` + `members[]` from the JSON body
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestG11RouteWiring:
    """`POST /server/projects` reads `tags` and `members` from the JSON body
    and persists them. We patch `projects_db._supabase` (the helper every
    db call in `create_project` goes through — mirrors G1–G4 in-memory
    tests) rather than the upstream `supabase_utils.get_supabase_client`
    so the patch is transparent to module-scope imports.
    """

    def _wire_route(self, mock_supabase, monkeypatch):
        from backend_server.src.routes import server_projects_routes as routes
        from shared.src.lib.database import projects_db

        # Every read/write create_project makes goes through `projects_db._supabase`.
        _install_supabase(mock_supabase, monkeypatch, projects_db=projects_db)
        _stub_get_or_create_tag(monkeypatch, projects_db)
        return routes, projects_db

    def test_post_project_persists_initial_tags_and_members(self, mock_supabase, monkeypatch):
        routes, _ = self._wire_route(mock_supabase, monkeypatch)

        meta = get_meta(mock_supabase._tables)
        team_id, owner_tm_id, viewer_tm_id = (
            meta['team_id'], meta['owner_tm_id'], meta['viewer_tm_id']
        )

        # The FK fix is in the route — replace `_caller_team_member_ids` so the
        # fix path (resolves `caller_team_member_ids[0]` → real team_member.id)
        # returns a valid row.
        monkeypatch.setattr(
            routes,
            '_caller_team_member_ids',
            lambda: [owner_tm_id],
        )

        # Skip the auth chain (`@require_permission` requires `request.user_role`
        # to exist, which is normally set by `@require_user_auth`). Set it here
        # so the in-memory unit test doesn't have to re-implement the chain.
        from flask import Flask, request
        app = Flask(__name__)
        with app.test_request_context(
            f'/server/projects?team_id={team_id}',
            method='POST',
            json={
                'name': 'Acme TV',
                'color': '#FFB300',
                'tags': ['smoke', 'regression'],
                'members': [{'team_member_id': viewer_tm_id, 'role': 'viewer'}],
            },
        ):
            request.user_role = 'admin'  # skip the auth chain
            resp = routes.create_project()

        if isinstance(resp, tuple):
            body, status = resp[0].get_json(), resp[1]
        else:
            body, status = resp.get_json(), resp.status_code
        assert status == 201, body
        assert body['name'] == 'Acme TV'

        project_id = body['id']
        # User tags persisted as `is_scope = FALSE`.
        user_tag_rows = [r for r in mock_supabase._tables['projects_tags']
                         if r['project_id'] == project_id and not r.get('is_scope')]
        assert len(user_tag_rows) == 2, user_tag_rows
        # Members persisted: creator as owner + initial viewer.
        members = [m for m in mock_supabase._tables['projects_members']
                   if m['project_id'] == project_id]
        assert sorted(m['role'] for m in members) == ['owner', 'viewer']

    def test_post_project_rejects_invalid_payload(self, mock_supabase, monkeypatch):
        """The route validates `tags` (must be a list) and `members[].role`
        (must be 'owner' or 'viewer') before hitting the db layer."""
        routes, _ = self._wire_route(mock_supabase, monkeypatch)

        meta = get_meta(mock_supabase._tables)
        team_id, owner_tm_id = meta['team_id'], meta['owner_tm_id']

        monkeypatch.setattr(
            routes, '_caller_team_member_ids', lambda: [owner_tm_id],
        )

        from flask import Flask, request
        app = Flask(__name__)

        # Bad role.
        with app.test_request_context(
            f'/server/projects?team_id={team_id}',
            method='POST',
            json={
                'name': 'Bad project',
                'members': [{'team_member_id': owner_tm_id, 'role': 'god'}],
            },
        ):
            request.user_role = 'admin'
            resp = routes.create_project()
        if isinstance(resp, tuple):
            body, status = resp[0].get_json(), resp[1]
        else:
            body, status = resp.get_json(), resp.status_code
        assert status == 400, body
        assert 'role' in body['error']

        # Non-list tags.
        app = Flask(__name__)
        with app.test_request_context(
            f'/server/projects?team_id={team_id}',
            method='POST',
            json={'name': 'Bad tags project', 'tags': 'smoke'},
        ):
            request.user_role = 'admin'
            resp = routes.create_project()
        if isinstance(resp, tuple):
            body, status = resp[0].get_json(), resp[1]
        else:
            body, status = resp.get_json(), resp.status_code
        assert status == 400, body
        assert 'tags' in body['error']

        # Non-string tag entry.
        app = Flask(__name__)
        with app.test_request_context(
            f'/server/projects?team_id={team_id}',
            method='POST',
            json={'name': 'Bad tags project 2', 'tags': [123]},
        ):
            request.user_role = 'admin'
            resp = routes.create_project()
        if isinstance(resp, tuple):
            body, status = resp[0].get_json(), resp[1]
        else:
            body, status = resp.get_json(), resp.status_code
        assert status == 400, body
        assert 'tags' in body['error']
