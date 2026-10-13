"""Unit tests: holding an org.* permission must not be a path to more permissions.

Once org.users:edit / org.teams:* / org.roles:edit are permission gates instead of
admin-only, a non-admin holding one could otherwise hand themselves anything: grant it on
their own profile, lift their own denial, add it to their own team or role, join a more
powerful team, or promote themselves to admin. forbid_escalation() refuses every change
that would give out a permission the caller does not hold; admins are never limited.

Runs offline in a Flask request context; the database is stubbed.
"""

import pytest
from flask import Flask, request

from backend_server.src.lib import auth_middleware
from backend_server.src.routes import server_permissions_routes, server_teams_routes, server_users_routes

pytestmark = pytest.mark.unit

# A manager of team t-qa who was also given the org permissions. `_vpt_team_ids` is the
# request cache _caller_team_ids() reads, i.e. the team_ids claim. Every account is also in
# the default team, which org scoping leaves out (TASK-31, decision 5).
MANAGER = {
    'user_role': 'manager',
    'user_id': 'auto_signed',
    'user_permissions': ['org.users:view', 'org.users:edit', 'org.users:delete',
                         'org.teams:view', 'org.teams:edit', 'org.teams:manage_members', 'org.roles:edit'],
    '_vpt_team_ids': {'t-qa', 'strong', 'weak', 'default'},
}
ADMIN = {'user_role': 'admin', 'user_id': 'auto_signed'}

TESTER_DEFAULTS = ['testcases:view', 'testcases:create']


@pytest.fixture(autouse=True)
def role_table(monkeypatch):
    monkeypatch.setattr(auth_middleware, '_load_role_defaults',
                        lambda: {'manager': TESTER_DEFAULTS, 'developer': [], 'tester': TESTER_DEFAULTS,
                                 'viewer': ['dashboard:view']})
    monkeypatch.setitem(auth_middleware._role_defaults_cache, 'value', None)
    auth_middleware.invalidate_role_defaults_cache()


@pytest.fixture
def db(monkeypatch):
    """Stub the user/team/role tables; records writes in db['writes']."""
    state = {
        'users': {
            'u-tester': {'id': 'u-tester', 'role': 'tester', 'permissions': [],
                         'denied_permissions': ['testcases:delete'], 'team_ids': ['default', 't-qa']},
            'u-admin': {'id': 'u-admin', 'role': 'admin', 'permissions': [], 'denied_permissions': [],
                        'team_ids': ['default', 't-qa']},
            'u-manager': {'id': 'u-manager', 'role': 'manager', 'permissions': [], 'denied_permissions': [],
                          'team_ids': ['default', 't-qa']},
            'u-outsider': {'id': 'u-outsider', 'role': 'tester', 'permissions': [], 'denied_permissions': [],
                           'team_ids': ['default', 't-other']},
        },
        'teams': {
            'strong': {'id': 'strong', 'permissions': ['system.hosts:run_command']},
            'weak': {'id': 'weak', 'permissions': ['testcases:view']},
        },
        'writes': [],
    }
    users, teams = server_users_routes.users_db, server_teams_routes.teams_db
    monkeypatch.setattr(users, 'get_user', lambda uid: state['users'].get(uid))
    monkeypatch.setattr(users, 'update_user', lambda uid, data: state['writes'].append(('update_user', uid)) or {'id': uid})
    monkeypatch.setattr(users, 'delete_user', lambda uid: state['writes'].append(('delete_user', uid)) or True)
    monkeypatch.setattr(users, 'resolve_user_id', lambda uid: uid)
    monkeypatch.setattr(users, 'assign_user_to_team', lambda *a: state['writes'].append(('assign', a[1])) or True)
    monkeypatch.setattr(teams, 'get_team', lambda tid: state['teams'].get(tid))
    monkeypatch.setattr(teams, 'get_default_team_ids', lambda: {'default'})
    monkeypatch.setattr(teams, 'update_team', lambda tid, data: state['writes'].append(('update_team', tid)) or {'id': tid})
    monkeypatch.setattr(teams, 'add_team_member', lambda tid, *a: state['writes'].append(('add_member', tid)) or {'id': 'm'})
    monkeypatch.setattr(server_permissions_routes.role_permissions_db, 'update_role_permissions',
                        lambda role, perms, by: state['writes'].append(('update_role', role)) or perms)
    return state


def _call(view, principal, *args, method='PUT', json=None):
    app = Flask(__name__)
    with app.test_request_context('/server/x', method=method, json=json):
        for key, value in principal.items():
            setattr(request, key, value)
        response = view(*args)
        resp, status = response if isinstance(response, tuple) else (response, 200)
        return status


class TestUngrantable:

    def test_admin_can_grant_anything(self):
        app = Flask(__name__)
        with app.test_request_context('/'):
            request.user_role = 'admin'
            assert auth_middleware.ungrantable_permissions(['system.hosts:run_command']) == []

    def test_non_admin_can_only_grant_what_they_hold(self):
        app = Flask(__name__)
        with app.test_request_context('/'):
            request.user_role = 'tester'
            assert auth_middleware.ungrantable_permissions(['testcases:view', 'testcases:delete']) == ['testcases:delete']


class TestUserEdits:

    def test_grant_held_permission(self, db):
        assert _call(server_users_routes.update_user, MANAGER, 'u-tester',
                     json={'permissions': ['org.users:view']}) == 200

    def test_grant_unheld_permission(self, db):
        assert _call(server_users_routes.update_user, MANAGER, 'u-tester',
                     json={'permissions': ['system.hosts:run_command']}) == 403
        assert db['writes'] == []

    def test_lifting_a_denial_is_a_grant(self, db):
        # u-tester is denied testcases:delete; the manager does not hold it.
        assert _call(server_users_routes.update_user, MANAGER, 'u-tester',
                     json={'denied_permissions': []}) == 403

    def test_cannot_promote_to_admin(self, db):
        assert _call(server_users_routes.update_user, MANAGER, 'u-tester', json={'role': 'admin'}) == 403

    def test_cannot_promote_to_own_rank(self, db):
        assert _call(server_users_routes.update_user, MANAGER, 'u-tester', json={'role': 'manager'}) == 403

    def test_can_set_a_lower_role(self, db):
        # developer's defaults are empty in this table, so the change grants nothing.
        assert _call(server_users_routes.update_user, MANAGER, 'u-tester', json={'role': 'developer'}) == 200

    def test_cannot_edit_another_manager(self, db):
        assert _call(server_users_routes.update_user, MANAGER, 'u-manager', json={'permissions': []}) == 403

    def test_unknown_role_rejected(self, db):
        assert _call(server_users_routes.update_user, ADMIN, 'u-tester', json={'role': 'overlord'}) == 400

    def test_cannot_edit_an_admin(self, db):
        assert _call(server_users_routes.update_user, MANAGER, 'u-admin', json={'permissions': []}) == 403

    def test_cannot_delete_an_admin(self, db):
        assert _call(server_users_routes.delete_user, MANAGER, 'u-admin', method='DELETE') == 403
        assert db['writes'] == []

    def test_can_delete_a_tester(self, db):
        assert _call(server_users_routes.delete_user, MANAGER, 'u-tester', method='DELETE') == 200

    def test_user_outside_own_teams_is_not_found(self, db):
        # Sharing only the default team does not count.
        assert _call(server_users_routes.update_user, MANAGER, 'u-outsider', json={'permissions': []}) == 404
        assert _call(server_users_routes.get_user, MANAGER, 'u-outsider', method='GET') == 404
        assert _call(server_users_routes.delete_user, MANAGER, 'u-outsider', method='DELETE') == 404
        assert db['writes'] == []

    def test_admin_is_not_limited(self, db):
        assert _call(server_users_routes.update_user, ADMIN, 'u-tester',
                     json={'role': 'admin', 'permissions': ['system.hosts:run_command']}) == 200


class TestTeamEdits:

    def test_joining_any_team_is_allowed_a_team_grants_nothing(self, db):
        # TASK-31: teams are ceilings, so joining one can never raise anyone's access.
        assert _call(server_teams_routes.add_team_member, MANAGER, 'strong', method='POST',
                     json={'user_id': 'u-tester'}) == 201
        assert _call(server_users_routes.assign_user_to_team, MANAGER, 'u-tester', method='POST',
                     json={'team_id': 'strong'}) == 200

    def test_can_join_a_team_within_own_permissions(self, db):
        assert _call(server_teams_routes.add_team_member, MANAGER, 'weak', method='POST',
                     json={'user_id': 'u-tester'}) == 201

    def test_cannot_pull_an_admin_into_own_team(self, db):
        assert _call(server_teams_routes.add_team_member, MANAGER, 'weak', method='POST',
                     json={'user_id': 'u-admin'}) == 403
        assert _call(server_users_routes.assign_user_to_team, MANAGER, 'u-admin', method='POST',
                     json={'team_id': 'weak'}) == 403
        assert db['writes'] == []

    def test_cannot_set_a_primary_team_outside_own_teams(self, db):
        assert _call(server_users_routes.update_user, MANAGER, 'u-tester',
                     json={'team_id': 't-other'}) == 403
        assert db['writes'] == []

    def test_cannot_add_unheld_permission_to_a_team(self, db):
        assert _call(server_teams_routes.update_team, MANAGER, 'weak',
                     json={'permissions': ['testcases:view', 'system.hosts:run_command']}) == 403

    def test_keeping_existing_team_permissions_is_allowed(self, db):
        # 'strong' already has a permission the manager lacks; renaming it re-sends it unchanged.
        assert _call(server_teams_routes.update_team, MANAGER, 'strong',
                     json={'name': 'x', 'permissions': ['system.hosts:run_command']}) == 200


class TestOrgScope:

    def test_team_outside_own_teams_is_not_found(self, db):
        db['teams']['t-other'] = {'id': 't-other', 'permissions': []}
        assert _call(server_teams_routes.add_team_member, MANAGER, 't-other', method='POST',
                     json={'user_id': 'u-tester'}) == 404
        assert _call(server_teams_routes.get_team_members, MANAGER, 't-other', method='GET') == 404
        assert db['writes'] == []

    def test_scope_leaves_out_the_default_team(self, db):
        app = Flask(__name__)
        with app.test_request_context('/'):
            for key, value in MANAGER.items():
                setattr(request, key, value)
            assert auth_middleware.org_scope_team_ids() == {'t-qa', 'strong', 'weak'}

    def test_default_team_counts_when_it_is_the_only_one(self, db):
        app = Flask(__name__)
        with app.test_request_context('/'):
            for key, value in {**MANAGER, '_vpt_team_ids': {'default'}}.items():
                setattr(request, key, value)
            assert auth_middleware.org_scope_team_ids() == {'default'}

    def test_admin_scope_is_unlimited(self, db):
        app = Flask(__name__)
        with app.test_request_context('/'):
            request.user_role = 'admin'
            assert auth_middleware.org_scope_team_ids() is None


class TestRoleEdits:

    def test_cannot_add_unheld_permission_to_a_role(self, db):
        assert _call(server_permissions_routes.update_role, MANAGER, 'tester',
                     json={'permissions': TESTER_DEFAULTS + ['plugins.testrail:manage']}) == 403
        assert db['writes'] == []

    def test_removing_role_permissions_is_allowed(self, db):
        assert _call(server_permissions_routes.update_role, MANAGER, 'tester',
                     json={'permissions': ['testcases:view']}) == 200
