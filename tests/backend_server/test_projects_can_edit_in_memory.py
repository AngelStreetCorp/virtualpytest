"""
In-memory tests for BUG-0577 — the public `caller_project_role` and
`can_edit_project` helpers in `server_projects_routes.py`, plus the new
`permissions: { my_role, can_edit }` block on the project overview endpoint.

The bug
-------
`/projects/<id>` had no Rename / Delete buttons. The PATCH / DELETE routes
were already enforcing admin-or-owner, but the frontend couldn't mirror that
gating because the overview endpoint never returned the caller's edit rights.
This slice:
  * adds public `caller_project_role(project_id)` and `can_edit_project(project_id)`
    in `server_projects_routes.py` so the overview module can share the verdict,
  * surfaces the verdict as `permissions.my_role` + `permissions.can_edit` in
    the overview JSON.

These tests exercise the helper directly (no Flask) and confirm the four
caller profiles the UI cares about — admin, owner, viewer, non-member — land
on the expected `(my_role, can_edit)` pair. They're the same shape as the
`test_projects_g6_audit_in_memory.py` suite: a `fake_request` shim, an
in-memory `_supabase` swap, no live DB.
"""

from __future__ import annotations

import os
import sys
import logging

import pytest

from backend_server.src.lib import project_permissions as perms


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # for `_supabase_mock`
sys.path.insert(0, '/home/jndoye/vpt-task65')


# ---------------------------------------------------------------------------
# Fixtures — same pattern as test_projects_g6_audit_in_memory.py
# ---------------------------------------------------------------------------
class _Req:
    """A minimal `flask.request` shim. `user_id` drives `_caller_team_member_ids`;
    `user_role` drives `caller_is_admin`."""

    def __init__(self, user_id: str | None = None, user_role: str | None = None):
        self.user_id = user_id
        self.user_role = user_role


@pytest.fixture
def routes_module(monkeypatch):
    """Reload `server_projects_routes` with the real `_supabase` factory
    monkey-patched to the in-memory mock. We need to patch `_supabase` on
    the module object because `projects_db.list_project_members` calls it.
    """
    import importlib
    import uuid as _uuid
    from _supabase_mock import SupabaseMock, make_projects_seed, get_meta
    from backend_server.src.routes import server_projects_routes as routes

    seed = make_projects_seed()
    mock = SupabaseMock(initial=seed)
    meta = get_meta(seed)

    # Add an "outsider" team_member that exists in the same team but is not
    # attached to p1 — this is the canonical non-member case we want to test.
    outsider_tm_id = str(_uuid.uuid4())
    mock.get_table('team_members').append({
        'id': outsider_tm_id,
        'user_id': 'user-3',
        'team_id': meta['team_id'],
        'profile': {'id': 'user-3', 'display_name': 'Out Sider', 'email': 'out@example.com'},
    })
    meta['outsider_tm_id'] = outsider_tm_id

    # Reload so the helper closures see the patched `_supabase` factory.
    importlib.reload(routes)

    import shared.src.lib.database.projects_db as pdb
    monkeypatch.setattr(pdb, '_supabase', lambda: mock)
    # Re-bind the route module's local alias to projects_db (which now uses
    # the in-memory mock). `server_projects_routes` doesn't define its own
    # `_supabase` factory — every DB call funnels through `projects_db`.
    monkeypatch.setattr(routes, 'projects_db', pdb)

    return routes, mock, seed


# ---------------------------------------------------------------------------
# Direct helper tests — no Flask app needed
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCallerProjectRole:
    """The public helper that the overview endpoint calls."""

    def test_admin_returns_none_for_my_role_but_true_for_can_edit(self, routes_module, monkeypatch):
        routes, _mock, seed = routes_module
        meta = seed['_meta'][0]
        proj_id = meta['p1']

        # Admin path: caller_is_admin() returns True → bypass.
        monkeypatch.setattr(routes, 'request', _Req(user_id='admin-uuid', user_role='admin'))
        monkeypatch.setattr(perms, 'caller_is_admin', lambda: True)
        monkeypatch.setattr(perms, '_caller_team_member_ids', lambda: [])

        assert routes.caller_project_role(proj_id) is None
        assert routes.can_edit_project(proj_id) is True

    def test_project_owner_returns_owner_and_true(self, routes_module, monkeypatch):
        routes, _mock, seed = routes_module
        meta = seed['_meta'][0]
        proj_id = meta['p1']
        owner_tm_id = meta['owner_tm_id']  # already on `p1` as `role='owner'`

        monkeypatch.setattr(routes, 'request', _Req(user_id='owner-uuid', user_role=None))
        monkeypatch.setattr(perms, 'caller_is_admin', lambda: False)
        monkeypatch.setattr(perms, '_caller_team_member_ids', lambda: [owner_tm_id])

        assert routes.caller_project_role(proj_id) == 'owner'
        assert routes.can_edit_project(proj_id) is True

    def test_project_viewer_returns_viewer_and_false(self, routes_module, monkeypatch):
        routes, _mock, seed = routes_module
        meta = seed['_meta'][0]
        proj_id = meta['p1']
        viewer_tm_id = meta['viewer_tm_id']  # on `p1` as `role='viewer'` only

        monkeypatch.setattr(routes, 'request', _Req(user_id='viewer-uuid', user_role=None))
        monkeypatch.setattr(perms, 'caller_is_admin', lambda: False)
        monkeypatch.setattr(perms, '_caller_team_member_ids', lambda: [viewer_tm_id])

        assert routes.caller_project_role(proj_id) == 'viewer'
        assert routes.can_edit_project(proj_id) is False

    def test_non_member_returns_none_and_false(self, routes_module, monkeypatch):
        routes, _mock, seed = routes_module
        meta = seed['_meta'][0]
        proj_id = meta['p1']

        # The fixture plants an `outsider_tm_id` that has no row in
        # `projects_members` for `p1`.
        outsider_tm_id = meta['outsider_tm_id']

        monkeypatch.setattr(routes, 'request', _Req(user_id='outsider-uuid', user_role=None))
        monkeypatch.setattr(perms, 'caller_is_admin', lambda: False)
        monkeypatch.setattr(perms, '_caller_team_member_ids', lambda: [outsider_tm_id])

        assert routes.caller_project_role(proj_id) is None
        assert routes.can_edit_project(proj_id) is False

    def test_owner_role_wins_when_caller_is_both_owner_and_viewer(self, routes_module, monkeypatch):
        """Defensive — a caller whose `team_member_id` shows up twice in the
        `projects_members` rows (shouldn't happen, but the data model doesn't
        forbid it) must surface as `owner`, the higher-privileged role, not
        `viewer`. Otherwise `can_edit` flips to False and the buttons
        mysteriously vanish.
        """
        routes, mock, seed = routes_module
        meta = seed['_meta'][0]
        proj_id = meta['p1']
        owner_tm_id = meta['owner_tm_id']

        monkeypatch.setattr(routes, 'request', _Req(user_id='owner-uuid', user_role=None))
        monkeypatch.setattr(perms, 'caller_is_admin', lambda: False)
        monkeypatch.setattr(perms, '_caller_team_member_ids', lambda: [owner_tm_id])

        # Add a duplicate viewer row for the same caller — the data model
        # doesn't forbid this (no UNIQUE constraint on (project_id,
        # team_member_id) in the blueprint migration).
        mock.get_table('projects_members').append({
            'project_id': proj_id,
            'team_member_id': owner_tm_id,
            'role': 'viewer',
            'created_at': '2026-09-04T00:00:00+00:00',
        })

        assert routes.caller_project_role(proj_id) == 'owner'
        assert routes.can_edit_project(proj_id) is True

    def test_empty_caller_team_member_ids_returns_none(self, routes_module, monkeypatch):
        """Defensive — `caller_project_role` returns None (not raises) when
        the caller has no team_member row at all (auth-disabled / open-mode
        principals, or a freshly-created user before the team_members
        heartbeat runs). The `_caller_team_member_ids` helper already
        returns `[]` for these cases — make sure the new helper handles it
        without exploding.
        """
        routes, _mock, seed = routes_module
        meta = seed['_meta'][0]
        proj_id = meta['p1']

        monkeypatch.setattr(routes, 'request', _Req(user_id='open-mode', user_role='viewer'))
        monkeypatch.setattr(perms, 'caller_is_admin', lambda: False)
        monkeypatch.setattr(perms, '_caller_team_member_ids', lambda: [])

        assert routes.caller_project_role(proj_id) is None
        # Plain non-member → can_edit is False. (An admin in this scenario
        # would have hit the admin branch above.)
        assert routes.can_edit_project(proj_id) is False


# ---------------------------------------------------------------------------
# Smoke test — make sure the helpers do NOT emit audit lines on read.
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_helpers_do_not_emit_audit_logs(routes_module, monkeypatch, caplog):
    """`can_edit_project` / `caller_project_role` are pure read helpers; they
    must not emit `[PROJECT_AUDIT]` lines (those are reserved for actual
    write operations — create / update / delete / add_member / etc.). If
    this test ever fails, somebody snuck a write into the helper, which
    would double-log every page load.
    """
    routes, _mock, seed = routes_module
    meta = seed['_meta'][0]

    monkeypatch.setattr(routes, 'request', _Req(user_id='owner-uuid', user_role=None))
    monkeypatch.setattr(perms, 'caller_is_admin', lambda: False)
    monkeypatch.setattr(perms, '_caller_team_member_ids', lambda: [meta['owner_tm_id']])

    caplog.set_level(logging.INFO, logger='backend_server.src.routes.server_projects_routes')
    _ = routes.caller_project_role(meta['p1'])
    _ = routes.can_edit_project(meta['p1'])
    audit = [r for r in caplog.records if '[PROJECT_AUDIT]' in r.getMessage()]
    assert audit == []