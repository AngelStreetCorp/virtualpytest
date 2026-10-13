"""Unit tests: provisioning sets role and team (TASK-31 phase A).

POST / PUT /server/users/<email> now accept `role` — a role's preferred name, as the external
platform knows it ("SuperAdmin" -> admin), or its id — plus `team` (same as `group`) and
`replace_teams`. The service key may set any role, admin included (decision 4). A manager may
only provision inside their own teams and only give roles ranked below their own.

Runs offline in a Flask request context; users_db / roles_db / teams_db are stubbed.
"""

import pytest
from flask import Flask, request

from backend_server.src.lib import auth_middleware
from backend_server.src.routes import server_users_routes

pytestmark = pytest.mark.unit

EMAIL = 'marie.dupont@example.com'
SERVICE = {'user_role': 'service', 'user_id': 'service'}
MANAGER = {
    'user_role': 'manager',
    'user_id': 'auto_signed',
    'user_permissions': ['org.users:view', 'org.users:create', 'org.users:edit'],
    '_vpt_team_ids': {'t-qa', 'default'},
}
# role -> preferred name, as an installation would set them on the Roles page
PREFERRED = {'admin': 'SuperAdmin', 'manager': 'SuperUser', 'developer': 'DevUser',
             'tester': 'User', 'viewer': 'Guest'}


@pytest.fixture(autouse=True)
def role_table(monkeypatch):
    monkeypatch.setattr(auth_middleware, '_load_role_defaults', lambda: {
        'manager': ['testcases:view', 'testcases:create'], 'developer': ['testcases:view'],
        'tester': ['testcases:view'], 'viewer': ['dashboard:view']})
    monkeypatch.setitem(auth_middleware._role_defaults_cache, 'value', None)
    auth_middleware.invalidate_role_defaults_cache()


@pytest.fixture
def db(monkeypatch):
    """Stubs; db['upserts'] records every upsert_user call's keyword arguments."""
    from shared.src.lib.database import roles_db, teams_db
    state = {'existing': None, 'upserts': []}
    users = server_users_routes.users_db

    def fake_upsert(**kw):
        state['upserts'].append(kw)
        return {'action': 'updated' if state['existing'] else 'created', 'user_id': 'u1',
                'email': kw['email'], 'role': kw.get('role') or kw['default_role'],
                'team': kw.get('group'), 'teams': [kw['group']] if kw.get('group') else [],
                'full_name': 'marie.dupont', 'provider_type': kw.get('provider_type') or 'virtualpytest'}

    monkeypatch.setattr(users, 'upsert_user', fake_upsert)
    monkeypatch.setattr(users, 'get_user_by_email', lambda e: state['existing'])
    catalog = {role: {'display_name': name, 'allowed_devices': None} for role, name in PREFERRED.items()}
    monkeypatch.setattr(roles_db, 'get_role_catalog', lambda: catalog)
    monkeypatch.setattr(teams_db, 'get_default_team_ids', lambda: {'default'})
    monkeypatch.setattr(teams_db, 'get_all_teams', lambda: [
        {'id': 't-qa', 'name': 'QA Team', 'permissions': []},
        {'id': 't-other', 'name': 'Other Team', 'permissions': []},
    ])
    return state


def _call(view, principal, *args, method='PUT', json=None):
    app = Flask(__name__)
    with app.test_request_context('/server/users', method=method, json=json):
        for key, value in principal.items():
            setattr(request, key, value)
        response = view(*args)
        resp, status = response if isinstance(response, tuple) else (response, 200)
        return status, resp.get_json()


class TestRoleResolution:

    @pytest.mark.parametrize('sent,expected', [
        ('SuperAdmin', 'admin'), ('superadmin', 'admin'), (' DevUser ', 'developer'),
        ('SuperUser', 'manager'), ('Guest', 'viewer'), ('developer', 'developer'), ('Tester', 'tester'),
    ])
    def test_preferred_name_or_id(self, db, sent, expected):
        status, body = _call(server_users_routes.update_user, SERVICE, EMAIL, json={'role': sent})
        assert status == 200, body
        assert db['upserts'][0]['role'] == expected

    def test_provider_type_plays_no_part(self, db):
        status, _ = _call(server_users_routes.update_user, SERVICE, EMAIL,
                          json={'role': 'User', 'provider_type': 'anything'})
        assert status == 200 and db['upserts'][0]['role'] == 'tester'

    def test_unknown_role_lists_what_is_accepted(self, db):
        status, body = _call(server_users_routes.update_user, SERVICE, EMAIL, json={'role': 'Overlord'})
        assert status == 400
        assert 'SuperAdmin' in body['detail'] and 'developer' in body['detail']
        assert db['upserts'] == []

    def test_service_key_may_grant_admin(self, db):
        status, _ = _call(server_users_routes.create_user, SERVICE, method='POST',
                          json={'email': EMAIL, 'password': 'pw123456', 'role': 'SuperAdmin'})
        assert status == 200 and db['upserts'][0]['role'] == 'admin'

    def test_no_role_leaves_it_alone(self, db):
        status, _ = _call(server_users_routes.update_user, SERVICE, EMAIL, json={'password': 'pw123456'})
        assert status == 200 and db['upserts'][0]['role'] is None


class TestTeamFields:

    def test_team_is_passed_as_the_group(self, db):
        status, body = _call(server_users_routes.update_user, SERVICE, EMAIL,
                             json={'team': 'QA Team', 'replace_teams': True})
        assert status == 200
        assert db['upserts'][0]['group'] == 'QA Team' and db['upserts'][0]['replace_teams'] is True
        assert body['platform']['teams'] == ['QA Team']

    def test_team_and_group_must_agree(self, db):
        status, _ = _call(server_users_routes.update_user, SERVICE, EMAIL,
                          json={'team': 'QA Team', 'group': 'Other Team'})
        assert status == 400 and db['upserts'] == []

    def test_replace_teams_needs_a_team(self, db):
        status, _ = _call(server_users_routes.update_user, SERVICE, EMAIL, json={'replace_teams': True})
        assert status == 400 and db['upserts'] == []


class TestManagerProvisioning:

    def test_creates_a_developer_in_own_team(self, db):
        status, body = _call(server_users_routes.create_user, MANAGER, method='POST',
                             json={'email': EMAIL, 'password': 'pw123456', 'team': 'QA Team',
                                   'role': 'developer'})
        assert status == 200, body

    def test_cannot_create_without_a_team(self, db):
        status, _ = _call(server_users_routes.create_user, MANAGER, method='POST',
                          json={'email': EMAIL, 'password': 'pw123456'})
        assert status == 400 and db['upserts'] == []

    def test_cannot_use_a_team_that_is_not_theirs(self, db):
        status, _ = _call(server_users_routes.create_user, MANAGER, method='POST',
                          json={'email': EMAIL, 'password': 'pw123456', 'team': 'Other Team'})
        assert status == 403 and db['upserts'] == []

    def test_cannot_auto_create_a_team(self, db):
        status, _ = _call(server_users_routes.create_user, MANAGER, method='POST',
                          json={'email': EMAIL, 'password': 'pw123456', 'team': 'Brand New'})
        assert status == 403 and db['upserts'] == []

    @pytest.mark.parametrize('role', ['admin', 'manager', 'SuperUser', 'SuperAdmin'])
    def test_cannot_give_a_role_at_or_above_own(self, db, role):
        status, _ = _call(server_users_routes.create_user, MANAGER, method='POST',
                          json={'email': EMAIL, 'password': 'pw123456', 'team': 'QA Team', 'role': role})
        assert status == 403 and db['upserts'] == []

    def test_cannot_touch_a_user_outside_own_teams(self, db):
        db['existing'] = {'id': 'u1', 'email': EMAIL, 'role': 'tester', 'provider_type': 'virtualpytest',
                          'team_ids': ['default', 't-other']}
        status, _ = _call(server_users_routes.update_user, MANAGER, EMAIL, json={'password': 'pw123456'})
        assert status == 403 and db['upserts'] == []

    def test_cannot_replace_teams(self, db):
        db['existing'] = {'id': 'u1', 'email': EMAIL, 'role': 'tester', 'provider_type': 'virtualpytest',
                          'team_ids': ['default', 't-qa']}
        status, _ = _call(server_users_routes.update_user, MANAGER, EMAIL,
                          json={'team': 'QA Team', 'replace_teams': True})
        assert status == 403 and db['upserts'] == []

    def test_cannot_reset_an_admin(self, db):
        db['existing'] = {'id': 'u1', 'email': EMAIL, 'role': 'admin', 'provider_type': 'virtualpytest',
                          'team_ids': ['default', 't-qa']}
        status, _ = _call(server_users_routes.update_user, MANAGER, EMAIL, json={'password': 'pw123456'})
        assert status == 403 and db['upserts'] == []
