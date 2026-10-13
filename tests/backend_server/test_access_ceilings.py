"""Unit tests: TASK-31 phases B and C — the team › role › user › workspace ceiling chain.

- A user's individual grants must sit inside their team ceiling; their device limit inside
  team ∩ role (for every caller: it is structure, not privilege).
- A team's `permissions` is a ceiling; only an admin may lift it (null); a non-admin may not
  widen it past what they hold. `allowed_devices` is validated as host:device keys.
- GET /server/users/<id>/scope returns the device chain and the effective set.
- Workspaces are administered only inside the caller's teams.
- _compute_effective labels every permission role / grant / denied / capped / none.

Runs offline in a Flask request context; the database modules are stubbed.
"""

import pytest
from flask import Flask, request

from backend_server.src.lib import auth_middleware, device_scope
from backend_server.src.routes import (
    server_permissions_routes,
    server_teams_routes,
    server_users_routes,
    server_workspaces_routes,
)

pytestmark = pytest.mark.unit

ADMIN = {'user_role': 'admin', 'user_id': 'u-admin'}
MANAGER = {
    'user_role': 'manager', 'user_id': 'u-manager',
    'user_permissions': ['org.users:view', 'org.users:edit', 'org.teams:edit',
                         'org.workspaces:view', 'org.workspaces:edit', 'org.workspaces:manage_members'],
    '_vpt_team_ids': {'t-qa', 'default'},
}
TESTER = {'user_role': 'tester', 'user_id': 'u-capped'}


@pytest.fixture(autouse=True)
def role_table(monkeypatch):
    monkeypatch.setattr(auth_middleware, '_load_role_defaults', lambda: {
        'manager': ['testcases:view'], 'developer': [], 'tester': ['testcases:view', 'testcases:create'],
        'viewer': ['dashboard:view']})
    monkeypatch.setitem(auth_middleware._role_defaults_cache, 'value', None)
    auth_middleware.invalidate_role_defaults_cache()


@pytest.fixture
def db(monkeypatch):
    from shared.src.lib.database import roles_db, teams_db, workspaces_db
    state = {
        'users': {
            'u-capped': {'id': 'u-capped', 'role': 'tester', 'permissions': [], 'denied_permissions': [],
                         'team_ids': ['default', 't-qa'], 'team_ceiling': ['testcases:view', 'org.users:view'],
                         'team_device_ceiling': ['pi1:device1', 'pi1:device2'], 'allowed_devices': None},
            'u-free': {'id': 'u-free', 'role': 'tester', 'permissions': [], 'denied_permissions': [],
                       'team_ids': ['default', 't-qa'], 'team_ceiling': None,
                       'team_device_ceiling': None, 'allowed_devices': ['pi1:device1']},
            'u-admin': {'id': 'u-admin', 'role': 'admin', 'permissions': [], 'denied_permissions': [],
                        'team_ids': ['default'], 'team_ceiling': [], 'team_device_ceiling': [],
                        'allowed_devices': None},
            'u-outsider': {'id': 'u-outsider', 'role': 'tester', 'permissions': [], 'denied_permissions': [],
                           'team_ids': ['default', 't-other'], 'team_ceiling': None,
                           'team_device_ceiling': None, 'allowed_devices': None},
        },
        'teams': {'t-qa': {'id': 't-qa', 'permissions': ['testcases:view']},
                  't-open': {'id': 't-open', 'permissions': None}},
        'workspaces': {'w-qa': [{'type': 'team', 'team_id': 't-qa'}],
                       'w-other': [{'type': 'team', 'team_id': 't-other'}],
                       'w-by-user': [{'type': 'user', 'user_id': 'u-capped'}]},
        'writes': [],
    }
    users = server_users_routes.users_db
    monkeypatch.setattr(users, 'get_user', lambda uid: state['users'].get(uid))
    monkeypatch.setattr(users, 'update_user', lambda uid, data: state['writes'].append(('update_user', uid, dict(data))) or {'id': uid})
    monkeypatch.setattr(teams_db, 'get_team', lambda tid: state['teams'].get(tid))
    monkeypatch.setattr(teams_db, 'update_team', lambda tid, data: state['writes'].append(('update_team', tid, dict(data))) or {'id': tid})
    monkeypatch.setattr(teams_db, 'get_default_team_ids', lambda: {'default'})
    monkeypatch.setattr(roles_db, 'role_devices', lambda role: ['pi1:device1'] if role == 'tester' else None)
    monkeypatch.setattr(workspaces_db, 'get_workspace_members', lambda wid: state['workspaces'].get(wid, []))
    monkeypatch.setattr(workspaces_db, 'get_all_workspaces', lambda: [{'id': w} for w in state['workspaces']])
    monkeypatch.setattr(workspaces_db, 'get_workspace', lambda wid: {'id': wid} if wid in state['workspaces'] else None)
    monkeypatch.setattr(workspaces_db, 'update_workspace', lambda wid, data: state['writes'].append(('update_ws', wid)) or {'id': wid})
    monkeypatch.setattr(workspaces_db, 'add_workspace_team', lambda wid, tid, role: state['writes'].append(('ws_team', wid, tid)) or {'id': 'm'})
    monkeypatch.setattr(server_workspaces_routes, '_with_device_names', lambda w: w)
    return state


def _call(view, principal, *args, method='PUT', json=None):
    app = Flask(__name__)
    with app.test_request_context('/server/x', method=method, json=json):
        for key, value in principal.items():
            setattr(request, key, value)
        response = view(*args)
        resp, status = response if isinstance(response, tuple) else (response, 200)
        return status, resp.get_json()


class TestUserGrantsInsideTeamCeiling:

    def test_grant_outside_the_ceiling_is_refused_even_for_an_admin(self, db):
        status, body = _call(server_users_routes.update_user, ADMIN, 'u-capped',
                             json={'permissions': ['org.users:view', 'settings.logs:view']})
        assert status == 400 and body['permissions'] == ['settings.logs:view']
        assert db['writes'] == []

    def test_grant_beyond_the_role_inside_the_ceiling(self, db):
        status, _ = _call(server_users_routes.update_user, ADMIN, 'u-capped',
                          json={'permissions': ['org.users:view']})
        assert status == 200

    def test_no_ceiling_no_limit(self, db):
        status, _ = _call(server_users_routes.update_user, ADMIN, 'u-free',
                          json={'permissions': ['settings.logs:view']})
        assert status == 200

    def test_an_admin_target_has_no_limits(self, db):
        status, _ = _call(server_users_routes.update_user, ADMIN, 'u-admin',
                          json={'permissions': ['settings.logs:view']})
        assert status == 200


class TestUserDevicesInsideTeamAndRole:

    def test_device_outside_team_and_role_is_refused(self, db):
        # team allows device1+2, tester role allows device1 only
        status, body = _call(server_users_routes.update_user, ADMIN, 'u-capped',
                             json={'allowed_devices': ['pi1:device1', 'pi1:device2']})
        assert status == 400 and body['devices'] == ['pi1:device2']

    def test_device_inside_is_saved_normalised(self, db):
        status, _ = _call(server_users_routes.update_user, ADMIN, 'u-capped',
                          json={'allowed_devices': [' pi1:device1 ', 'pi1:device1']})
        assert status == 200
        assert db['writes'][-1][2]['allowed_devices'] == ['pi1:device1']

    def test_null_inherits(self, db):
        status, _ = _call(server_users_routes.update_user, ADMIN, 'u-capped', json={'allowed_devices': None})
        assert status == 200

    @pytest.mark.parametrize('bad', ['pi1:device1', ['nocolon'], [':device1']])
    def test_bad_keys(self, db, bad):
        status, _ = _call(server_users_routes.update_user, ADMIN, 'u-free', json={'allowed_devices': bad})
        assert status == 400


class TestTeamLimits:

    def test_only_an_admin_lifts_a_limit(self, db):
        assert _call(server_teams_routes.update_team, MANAGER, 't-qa', json={'permissions': None})[0] == 403
        assert _call(server_teams_routes.update_team, ADMIN, 't-qa', json={'permissions': None})[0] == 200

    def test_non_admin_cannot_widen_past_what_they_hold(self, db):
        status, _ = _call(server_teams_routes.update_team, MANAGER, 't-qa',
                          json={'permissions': ['testcases:view', 'settings.logs:view']})
        assert status == 403

    def test_narrowing_is_fine(self, db):
        status, _ = _call(server_teams_routes.update_team, MANAGER, 't-qa', json={'permissions': []})
        assert status == 200

    def test_team_devices_validated(self, db):
        assert _call(server_teams_routes.update_team, ADMIN, 't-qa', json={'allowed_devices': ['x']})[0] == 400
        assert _call(server_teams_routes.update_team, ADMIN, 't-qa', json={'allowed_devices': ['pi1:device3']})[0] == 200


class TestScopeEndpoint:

    def test_own_scope(self, db):
        status, body = _call(server_users_routes.get_user_scope, TESTER, 'u-capped', method='GET')
        assert status == 200
        assert body['effective_devices'] == ['pi1:device1']
        assert body['team_devices'] == ['pi1:device1', 'pi1:device2'] and body['role_devices'] == ['pi1:device1']

    def test_admin_sees_everything(self, db):
        status, body = _call(server_users_routes.get_user_scope, ADMIN, 'u-admin', method='GET')
        assert status == 200 and body['effective_devices'] is None

    def test_someone_elses_scope_needs_org_users_view(self, db):
        assert _call(server_users_routes.get_user_scope, TESTER, 'u-free', method='GET')[0] == 403

    def test_manager_outside_own_teams(self, db):
        assert _call(server_users_routes.get_user_scope, MANAGER, 'u-outsider', method='GET')[0] == 404
        assert _call(server_users_routes.get_user_scope, MANAGER, 'u-free', method='GET')[0] == 200


class TestWorkspaceScope:

    def test_list_is_filtered(self, db):
        status, body = _call(server_workspaces_routes.get_workspaces, MANAGER, method='GET')
        assert status == 200 and sorted(w['id'] for w in body) == ['w-by-user', 'w-qa']

    def test_admin_lists_everything(self, db):
        _, body = _call(server_workspaces_routes.get_workspaces, ADMIN, method='GET')
        assert len(body) == 3

    def test_cannot_edit_another_teams_workspace(self, db):
        assert _call(server_workspaces_routes.update_workspace, MANAGER, 'w-other', json={'name': 'x'})[0] == 404
        assert _call(server_workspaces_routes.update_workspace, MANAGER, 'w-qa', json={'name': 'x'})[0] == 200

    def test_cannot_add_a_team_that_is_not_theirs(self, db):
        status, _ = _call(server_workspaces_routes.add_workspace_team, MANAGER, 'w-qa', method='POST',
                          json={'team_id': 't-other'})
        assert status == 404


class TestSources:

    def _sources(self, **user):
        base = {'role': 'tester', 'permissions': [], 'denied_permissions': [], 'team_ceiling': None}
        return server_permissions_routes._compute_effective({**base, **user})

    def test_labels(self):
        out = self._sources(permissions=['org.users:view', 'settings.logs:view'],
                            denied_permissions=['testcases:create'],
                            team_ceiling=['testcases:view', 'testcases:create', 'org.users:view'])
        src = out['sources']
        assert src['testcases:view'] == 'role'
        assert src['org.users:view'] == 'grant'
        assert src['testcases:create'] == 'denied'
        assert src['settings.logs:view'] == 'capped'
        assert src['dashboard:view'] == 'none'
        assert out['effective'] == ['org.users:view', 'testcases:view']

    def test_admin_holds_everything(self):
        out = self._sources(role='admin', team_ceiling=[])
        assert set(out['sources'].values()) == {'role'}


class TestDeviceHelpers:

    def test_intersect(self):
        assert device_scope.intersect(None, None) is None
        assert device_scope.intersect(['a:1', 'a:2'], None, ['a:2', 'a:3']) == ['a:2']

    def test_outside(self):
        assert device_scope.outside(None, ['a:1']) == []
        assert device_scope.outside(['a:1', 'a:2'], None) == []
        assert device_scope.outside(['a:1', 'a:2'], ['a:1']) == ['a:2']
