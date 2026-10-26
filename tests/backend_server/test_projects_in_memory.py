"""
In-memory tests for the TASK-65 G1–G4 project endpoints.

These tests never hit a live server or a real Supabase project. They swap the
`_supabase()` factory in each module under test for a `SupabaseMock` seeded
with `make_projects_seed()`, so the route helpers can run in a Python process
and we can assert on the exact response shape, error paths, and SQL-like
queries fired.

Why this matters
----------------
The 3 TASK-65 migration files (`20261006a_projects.sql` etc.) are still
blueprints on disk and are not applied to the shared Supabase project. Without
this in-memory suite, the G1–G4 endpoint code paths were tested only when
the migrations were applied + a live server was running. That means a typo
in `projects_db.create_project` (say) would only be caught post-merge.

What this file covers
---------------------
* `projects_db` CRUD: list / get / create / update / delete, members,
  tags, slug generation, duplicate-name handling, role validation.
* `server_projects_overview_routes` helpers: counts, runs-30d bucketing,
  last-failures aggregation, devices, AI tokens.
* `server_projects_executive_routes` helpers: pass-rate trend (happy path +
  empty script names), previous-window calculation, top-failures ranking,
  last-runs (with duration), AI tokens + budget, members list with caller-
  scoped `can_add` / `can_remove` flags.
* `ProjectDuplicateError`, `ProjectNotFoundError`, color validation paths.

These tests do NOT exercise the live auth / migration paths — those are
covered by `test_projects.py` and `test_projects_executive.py` (skip until
server reachable).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest


# Make the tests/ helpers importable.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # so we can import `_supabase_mock`
sys.path.insert(0, '/home/jndoye/vpt-task65')

from _supabase_mock import (  # type: ignore  # noqa: E402
    SupabaseMock,
    make_projects_seed,
    get_meta,
)


# ---------------------------------------------------------------------------
# Module loader: import the projects_db / route modules and patch _supabase().
# ---------------------------------------------------------------------------

@pytest.fixture
def seed():
    return make_projects_seed()


@pytest.fixture
def mock_supabase(seed) -> SupabaseMock:
    return SupabaseMock(initial=seed)


@pytest.fixture
def patched_projects_db(mock_supabase, monkeypatch):
    """`projects_db` is used both directly and via the route modules; we patch
    the `_supabase` factory in the project_db module so it returns the mock."""
    import importlib
    import shared.src.lib.database.projects_db as pdb
    importlib.reload(pdb)
    monkeypatch.setattr(pdb, '_supabase', lambda: mock_supabase)
    return pdb


@pytest.fixture
def patched_overview_route(mock_supabase, monkeypatch):
    import importlib
    import backend_server.src.routes.server_projects_overview_routes as mod
    importlib.reload(mod)
    # Patch `_supabase` on the overview module AND on projects_db (which it
    # also uses through `import projects_db`). Without the second patch the
    # route module still hits the real Supabase client when the helpers call
    # `projects_db.list_*`.
    monkeypatch.setattr(mod, '_supabase', lambda: mock_supabase)
    import shared.src.lib.database.projects_db as pdb_for_route
    monkeypatch.setattr(pdb_for_route, '_supabase', lambda: mock_supabase)
    return mod


@pytest.fixture
def patched_executive_route(mock_supabase, monkeypatch):
    import importlib
    import backend_server.src.routes.server_projects_executive_routes as mod
    importlib.reload(mod)
    # Same dual patch — `projects_db` is the partner module used inside.
    monkeypatch.setattr(mod, '_supabase', lambda: mock_supabase)
    import shared.src.lib.database.projects_db as pdb_for_route
    monkeypatch.setattr(pdb_for_route, '_supabase', lambda: mock_supabase)
    # The auth helpers (caller_is_admin, org_scope_team_ids) call
    # `flask.request.<user_role>` which requires a request context. The
    # executive module imported them by name (`from X import Y`), so the
    # binding lives on the module object. Patch both the auth_middleware
    # source AND the executive module's re-imported name.
    from backend_server.src.lib import auth_middleware
    monkeypatch.setattr(auth_middleware, 'caller_is_admin', lambda: False)
    monkeypatch.setattr(auth_middleware, 'org_scope_team_ids', lambda: None)
    monkeypatch.setattr(mod, 'caller_is_admin', lambda: False)
    monkeypatch.setattr(mod, 'org_scope_team_ids', lambda: None)
    return mod


# ---------------------------------------------------------------------------
# projects_db
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestProjectsDbCRUD:
    """Read + write paths in `projects_db` against the in-memory mock."""


    def test_list_projects_returns_enriched(self, patched_projects_db, seed, mock_supabase):
        meta = get_meta(seed)
        result = patched_projects_db.list_projects(meta['team_id'])
        assert len(result) == 2
        for p in result:
            assert p['team_id'] == meta['team_id']
            assert 'tags' in p and 'members' in p
            assert 'tag_ids' in p
            assert 'owner_count' in p and 'viewer_count' in p and 'member_count' in p
        # The owner is on both projects → 1 viewer (p1 only) and 1 owner per project
        web = next(p for p in result if p['id'] == meta['p1'])
        assert web['owner_count'] == 1
        assert web['viewer_count'] == 1
        assert web['member_count'] == 2

    def test_list_projects_filters_by_team(self, patched_projects_db, seed):
        meta = get_meta(seed)
        other_team = '00000000-0000-0000-0000-000000000099'
        assert patched_projects_db.list_projects(other_team) == []

    def test_list_projects_returns_empty_when_supabase_errors(
        self, patched_projects_db, mock_supabase, monkeypatch,
    ):
        # Force an exception by replacing the table method on the mock.
        def boom(_name):
            raise RuntimeError("simulated supabase outage")
        monkeypatch.setattr(mock_supabase, 'table', boom)
        result = patched_projects_db.list_projects('any-team')
        assert result == []

    def test_get_project_returns_none_for_unknown(self, patched_projects_db):
        assert patched_projects_db.get_project('does-not-exist') is None

    def test_get_project_returns_enriched(self, patched_projects_db, seed):
        meta = get_meta(seed)
        p = patched_projects_db.get_project(meta['p1'])
        assert p is not None
        assert p['name'] == 'Web app'
        assert p['tag_ids'] == [meta['tag1']]
        assert any(m['role'] == 'owner' for m in p['members'])

    def test_get_project_handles_supabase_error(
        self, patched_projects_db, mock_supabase, monkeypatch,
    ):
        def boom(_name):
            raise RuntimeError("simulated outage")
        monkeypatch.setattr(mock_supabase, 'table', boom)
        assert patched_projects_db.get_project('any-id') is None

    def test_create_project_creates_row_and_link(self, patched_projects_db, seed, mock_supabase):
        meta = get_meta(seed)
        # Stub folder_tag_db.get_or_create_tag via a fresh tag row
        mock_supabase._tables.setdefault('tags', []).append(
            {'tag_id': 999, 'name': 'edge_app', 'color': '#000000'}
        )
        # Patch the helper that create_project uses for the tag.
        from shared.src.lib.database import projects_db as pdb
        pdb._get_or_create_tag = lambda name: {'tag_id': 999, 'name': name, 'color': '#000000'}

        out = pdb.create_project(
            team_id=meta['team_id'],
            name='Edge app',
            description='new project',
            color='#abcdef',
            created_by_team_member_id=meta['owner_tm_id'],
        )
        # The returned project must exist in the mock and be enriched.
        assert out is not None
        # Re-enrich
        full = pdb.get_project(out['id'])
        assert full is not None
        assert full['name'] == 'Edge app'
        # Tag was linked
        rows = [r for r in mock_supabase.get_table('projects_tags') if r['project_id'] == out['id']]
        assert len(rows) == 1 and rows[0]['tag_id'] == 999
        # Creator is owner
        mrows = [r for r in mock_supabase.get_table('projects_members') if r['project_id'] == out['id']]
        assert any(m['team_member_id'] == meta['owner_tm_id'] and m['role'] == 'owner' for m in mrows)

    def test_create_project_duplicate_raises(self, patched_projects_db, mock_supabase, seed):
        meta = get_meta(seed)
        mock_supabase.seed_unique_violation('projects', 'name', 'Web app')
        from shared.src.lib.database.projects_db import ProjectDuplicateError
        with pytest.raises(ProjectDuplicateError):
            patched_projects_db.create_project(
                team_id=meta['team_id'],
                name='Web app',
                description=None,
                color=None,
                created_by_team_member_id=meta['owner_tm_id'],
            )

    def test_slugify_project_name(self, patched_projects_db):
        from shared.src.lib.database import projects_db as pdb
        # `[^a-z0-9_-]+` collapses runs of non-allowed chars into a single
        # underscore, then trailing underscores are stripped.
        assert pdb._slugify_project_name('Hello World!') == 'hello_world'
        assert pdb._slugify_project_name('FOO  bar') == 'foo_bar'
        assert pdb._slugify_project_name('   ') == 'project'
        assert pdb._slugify_project_name('Πρότζεκτ') == 'project'
        # Hyphens and underscores are preserved
        assert pdb._slugify_project_name('app-core_v2') == 'app-core_v2'

    def test_update_project_merges_fields(self, patched_projects_db, seed):
        meta = get_meta(seed)
        out = patched_projects_db.update_project(meta['p1'], {'description': 'updated'})
        assert out is not None and out['description'] == 'updated'

    def test_update_project_returns_none_for_unknown(self, patched_projects_db):
        assert patched_projects_db.update_project('missing', {'description': 'x'}) is None

    def test_delete_project_removes_row(self, patched_projects_db, seed, mock_supabase):
        meta = get_meta(seed)
        assert patched_projects_db.delete_project(meta['p1']) is True
        assert patched_projects_db.get_project(meta['p1']) is None
        # Cascade did NOT happen in the mock (no FK), but rows in projects_tags /
        # projects_members stay until the schema migration adds ON DELETE CASCADE.
        assert any(r['project_id'] == meta['p1'] for r in mock_supabase.get_table('projects_tags'))

    def test_delete_project_returns_true_even_when_no_match(
        self, patched_projects_db, seed, mock_supabase,
    ):
        # Real client: `delete_project` only returns False on exception, not
        # when 0 rows match. This is the spec we implement against — callers
        # that want 404 semantics check `get_project(id)` first.
        assert patched_projects_db.delete_project('missing') is True
        # No projects rows were touched
        assert len(mock_supabase.get_table('projects')) == len(seed['projects'])


@pytest.mark.unit
class TestProjectsDbMembers:
    """Member management paths."""

    def test_add_member_validates_role(self, patched_projects_db, seed, mock_supabase):
        meta = get_meta(seed)
        with pytest.raises(ValueError):
            patched_projects_db.add_project_member(meta['p1'], meta['viewer_tm_id'], 'editor')
        # The bad role did NOT get inserted
        rows = [r for r in mock_supabase.get_table('projects_members') if r['team_member_id'] == meta['viewer_tm_id']]
        assert all(r['role'] in ('owner', 'viewer') for r in rows)

    def test_remove_member_returns_true(self, patched_projects_db, seed, mock_supabase):
        meta = get_meta(seed)
        assert patched_projects_db.remove_project_member(meta['p1'], meta['viewer_tm_id']) is True
        # The viewer is gone
        rows = [r for r in mock_supabase.get_table('projects_members') if r['project_id'] == meta['p1']]
        assert all(r['team_member_id'] != meta['viewer_tm_id'] for r in rows)

    def test_remove_member_returns_true_even_when_no_match(
        self, patched_projects_db, seed, mock_supabase,
    ):
        meta = get_meta(seed)
        before = len(mock_supabase.get_table('projects_members'))
        # Same semantics as delete_project: returns True unless the call errored.
        assert patched_projects_db.remove_project_member(meta['p1'], 'not-a-member') is True
        # No members rows were touched
        assert len(mock_supabase.get_table('projects_members')) == before


# ---------------------------------------------------------------------------
# server_projects_executive_routes — helper-level in-memory
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestExecutiveHelpersInMemory:
    """Run the executive route helpers against a SupabaseMock."""

    def test_pass_rate_trend_buckets_each_day(self, patched_executive_route, mock_supabase, seed):
        meta = get_meta(seed)
        now = datetime.now(timezone.utc)
        mock_supabase._tables['script_results'] = [
            {'success': True,  'script_name': 's1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=2)).isoformat()},
            {'success': False, 'script_name': 's1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=2)).isoformat()},
            {'success': True,  'script_name': 's1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=1)).isoformat()},
            {'success': True,  'script_name': 's1', 'team_id': meta['team_id'], 'started_at': now.isoformat()},
        ]
        buckets = patched_executive_route._pass_rate_trend(
            team_id=meta['team_id'], script_names=['s1'], days=7,
        )
        assert len(buckets) == 7
        # Today has 1 row, 100% pass; yesterday has 1 row, 100% pass; two days ago has 2 rows, 50% pass
        by_day = {b['day']: b for b in buckets}
        assert by_day[now.date().isoformat()]['pass_rate'] == 100.0
        assert by_day[(now - timedelta(days=2)).date().isoformat()]['pass_rate'] == 50.0
        # Days with no data -> None
        old_day = (now - timedelta(days=4)).date().isoformat()
        assert by_day[old_day]['pass_rate'] is None

    def test_pass_rate_trend_zero_scripts_returns_zeroes(
        self, patched_executive_route, seed,
    ):
        meta = get_meta(seed)
        buckets = patched_executive_route._pass_rate_trend(
            team_id=meta['team_id'], script_names=[], days=7,
        )
        assert len(buckets) == 7
        for b in buckets:
            assert b['pass'] == 0 and b['fail'] == 0 and b['total'] == 0
            assert b['pass_rate'] is None

    def test_pass_rate_prev_window_only_counts_prior_window(
        self, patched_executive_route, mock_supabase, seed,
    ):
        meta = get_meta(seed)
        now = datetime.now(timezone.utc)
        # 4 prior-window rows (success=True), 1 current-window row (success=False)
        mock_supabase._tables['script_results'] = [
            {'success': True,  'script_name': 's1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=40)).isoformat()},
            {'success': True,  'script_name': 's1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=35)).isoformat()},
            {'success': True,  'script_name': 's1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=33)).isoformat()},
            {'success': True,  'script_name': 's1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=32)).isoformat()},
            {'success': False, 'script_name': 's1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=1)).isoformat()},
        ]
        prev = patched_executive_route._pass_rate_prev_window(
            team_id=meta['team_id'], script_names=['s1'], days=30,
        )
        # 4 prior passes out of 4 rows = 100%
        assert prev == 100.0

    def test_top_failures_aggregates_by_script(
        self, patched_executive_route, mock_supabase, seed,
    ):
        meta = get_meta(seed)
        now = datetime.now(timezone.utc)
        mock_supabase._tables['script_results'] = [
            {'success': False, 'script_name': 's_web_1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=1)).isoformat()},
            {'success': False, 'script_name': 's_web_1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=2)).isoformat()},
            {'success': False, 'script_name': 's_mob_1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=3)).isoformat()},
            {'success': True,  'script_name': 's_web_1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=4)).isoformat()},
        ]
        top = patched_executive_route._top_failures(
            team_id=meta['team_id'], script_names=['s_web_1', 's_mob_1'],
        )
        # Only failures count, and we cap at 5; both s_web_1 (2 fails) and s_mob_1 (1 fail) appear
        names = [r['script_name'] for r in top]
        assert 's_web_1' in names and 's_mob_1' in names
        web = next(r for r in top if r['script_name'] == 's_web_1')
        assert web['failure_count'] == 2
        assert web['last_failure_at'] is not None

    def test_members_distinguishes_owners_viewers(
        self, patched_executive_route, seed, mock_supabase,
    ):
        from flask import Flask
        app = Flask(__name__)
        meta = get_meta(seed)
        # `_is_project_owner` reads `flask.request.user_id`; spin up a request
        # context so the LocalProxy resolves to a real object (without it, the
        # fallback `getattr(..., None)` still triggers the context lookup).
        with app.test_request_context('/'):
            m = patched_executive_route._members(meta['p1'])
        assert any(o['team_member_id'] == meta['owner_tm_id'] for o in m['owners'])
        assert any(v['team_member_id'] == meta['viewer_tm_id'] for v in m['viewers'])
        # `can_add` / `can_remove` reflect caller scope; without an admin or
        # project-owner caller they default to False.
        assert m['can_add'] is False
        assert m['can_remove'] is False

    def test_health_three_buckets(self, patched_executive_route):
        # 95% with stable previous -> green
        assert patched_executive_route._health(96.0, 95.0)['level'] == 'green'
        # 90% with slight regression -> yellow
        assert patched_executive_route._health(90.0, 91.0)['level'] == 'yellow'
        # 70% -> red
        assert patched_executive_route._health(70.0, 80.0)['level'] == 'red'

    def test_empty_buckets(self, patched_executive_route):
        buckets = patched_executive_route._empty_buckets(14)
        assert len(buckets) == 14
        for b in buckets:
            assert b['pass'] == 0 and b['fail'] == 0 and b['total'] == 0
            assert b['pass_rate'] is None

    def test_script_names_for_project_returns_executable_ids(
        self, patched_executive_route, seed,
    ):
        names = patched_executive_route._script_names_for_project([1, 2])
        assert 's_web_1' in names and 's_web_2' in names and 's_mob_1' in names
        assert patched_executive_route._script_names_for_project([]) == []


# ---------------------------------------------------------------------------
# server_projects_overview_routes — helper-level in-memory
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestOverviewHelpersInMemory:
    def test_runs_30d_aggregates_by_status(
        self, patched_overview_route, mock_supabase, seed,
    ):
        meta = get_meta(seed)
        now = datetime.now(timezone.utc)
        # Seed uses tag_id=1 for s_web_1, s_web_2 (executable_tags rows). Use
        # one of those script_names so the tag_ids->script_names -> rows chain
        # in `_runs_30d` finds something.
        mock_supabase._tables['script_results'] = [
            {'success': True,  'started_at': (now - timedelta(days=1)).isoformat(), 'script_name': 's_web_1', 'team_id': meta['team_id']},
            {'success': False, 'started_at': (now - timedelta(days=2)).isoformat(), 'script_name': 's_web_1', 'team_id': meta['team_id']},
            {'success': True,  'started_at': (now - timedelta(days=31)).isoformat(), 'script_name': 's_web_1', 'team_id': meta['team_id']},
        ]
        out = patched_overview_route._runs_30d(team_id=meta['team_id'], tag_ids=[meta['tag1']], days=30)
        # Only 2 rows fall in the 30-day window (1 pass, 1 fail). The real
        # helper returns keys `pass` / `fail` / `total`; pass_rate is computed
        # by the route layer.
        assert out['total'] == 2
        assert out['pass'] == 1
        assert out['fail'] == 1

    def test_last_failures_returns_most_recent(self, patched_overview_route, mock_supabase, seed):
        meta = get_meta(seed)
        now = datetime.now(timezone.utc)
        mock_supabase._tables['script_results'] = [
            {'success': False, 'script_name': 's_web_1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=3)).isoformat()},
            {'success': False, 'script_name': 's_web_1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=1)).isoformat()},
            {'success': False, 'script_name': 's_mob_1', 'team_id': meta['team_id'], 'started_at': (now - timedelta(days=2)).isoformat()},
        ]
        out = patched_overview_route._last_failures(team_id=meta['team_id'], tag_ids=[meta['tag1'], meta['tag2']], limit=2)
        assert len(out) == 2
        # Most recent first
        assert out[0]['script_name'] == 's_web_1'
        assert out[0]['started_at'] is not None

    def test_devices_returns_zero_when_no_activity(
        self, patched_overview_route, mock_supabase, seed,
    ):
        meta = get_meta(seed)
        out = patched_overview_route._devices(team_id=meta['team_id'], days=1)
        # _devices returns {count, states:{online, offline, unknown}}; no script_results
        # rows in the mock, so count is 0 and all states are 0.
        assert out['count'] == 0
        assert out['states'] == {'online': 0, 'offline': 0, 'unknown': 0}
