"""Unit tests for TASK-23 tenant decorators.

Covers the three behaviours the auth middleware guarantees after Phase 2:

  * @require_platform_admin — refuses anyone who is not a platform super admin.
  * @require_team_in_tenant — refuses if the named team does not belong to a
    tenant the caller has membership in.
  * _caller_is_platform_admin / _caller_tenant_ids — read the JWT claim with
    a database fallback for tokens minted before the claim existed.

Runs entirely in a Flask test request context — no deployed server needed, and
the team.tenant_id / profiles.is_platform_admin lookups are monkeypatched so
no DB is touched.
"""

import pytest
from flask import Flask, jsonify

from backend_server.src.lib import auth_middleware as am


pytestmark = pytest.mark.unit


# ---- fixtures ------------------------------------------------------------


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def caller(monkeypatch):
    """Return a callable: set up the request context and yield a `caller` namespace
    with attributes the decorators / helpers expect to read.
    """

    def _setup(
        *,
        user_id: str = 'u-1',
        user_email: str = 'caller@vpt.local',
        role: str = 'admin',
        tenant_ids=None,
        is_platform_admin: bool = False,
        user_app_metadata=None,
    ):
        tenant_ids = list(tenant_ids or [])
        ctx = {
            'user_id': user_id,
            'user_email': user_email,
            'user_role': role,
            'user_app_metadata': dict(user_app_metadata or {}) | {
                'role': role,
                'tenant_ids': tenant_ids,
                'is_platform_admin': is_platform_admin,
            },
            'user_tenant_ids': tenant_ids,
            'user_is_platform_admin': is_platform_admin,
            'request_user_role': role,
            'request_is_platform_admin': is_platform_admin,
            'request_tenant_ids': tenant_ids,
        }
        return ctx

    return _setup


# ---- _caller_is_platform_admin -------------------------------------------


def test_is_platform_admin_true_when_claim_set(monkeypatch, app, caller):
    ctx = caller(is_platform_admin=True)
    with app.test_request_context('/server/tenants'):
        for k, v in ctx.items():
            if k.startswith('user_'):
                from flask import request
                setattr(request, k, v)
        # DB fallback must NOT be called when the claim is set.
        def _explode(_uid):
            raise AssertionError('DB lookup should not be reached when claim is set')
        monkeypatch.setattr(am, '_is_platform_admin_from_db', _explode)
        assert am._caller_is_platform_admin() is True


def test_is_platform_admin_false_when_claim_missing(monkeypatch, app, caller):
    # No claim -> claim defaults to False -> no DB lookup needed for the False
    # branch (the fallback only fires when the claim key is absent OR the
    # boolean check fails).
    ctx = caller(is_platform_admin=False, user_app_metadata={'role': 'admin'})
    with app.test_request_context('/server/tenants'):
        from flask import request
        for k, v in ctx.items():
            if k.startswith('user_'):
                setattr(request, k, v)
        monkeypatch.setattr(am, '_is_platform_admin_from_db',
                            lambda _uid: True)  # would flip to True if called
        assert am._caller_is_platform_admin() is False


def test_is_platform_admin_db_fallback_on_missing_claim(monkeypatch, app, caller):
    # user_app_metadata has no is_platform_admin key.
    ctx = caller(user_app_metadata={'role': 'admin'})
    ctx['user_is_platform_admin'] = False  # the decode block defaults missing to False
    with app.test_request_context('/server/tenants'):
        from flask import request
        for k, v in ctx.items():
            if k.startswith('user_'):
                setattr(request, k, v)
        monkeypatch.setattr(am, '_is_platform_admin_from_db', lambda _uid: True)
        assert am._caller_is_platform_admin() is True


# ---- @require_platform_admin ---------------------------------------------


def _route_response_decorator(decorator, *, path, method='GET', headers=None, **caller_kwargs):
    """Apply the decorator to a tiny route and return the actual response."""
    app = Flask(__name__)

    @decorator
    def _h():
        return jsonify({'ok': True}), 200

    app.add_url_rule(path, endpoint='h', view_func=_h, methods=[method])

    # Set up the caller context the way the JWT-decode block would.
    from flask import request
    ctx = caller(**caller_kwargs)
    with app.test_request_context(path, method=method, headers=headers or {}):
        for k, v in ctx.items():
            if k.startswith('user_'):
                setattr(request, k, v)
        with app.test_client() as client:
            return client.get(path)


def test_require_platform_admin_blocks_regular_admin(monkeypatch, app, caller):
    """role='admin' but is_platform_admin=False — still denied (Q3)."""
    monkeypatch.setattr(am, '_caller_is_platform_admin', lambda: False)
    resp, status = _route_response_decorator(
        am.require_platform_admin,
        path='/server/tenants',
        role='admin',
        is_platform_admin=False,
    )
    assert status == 403


def test_require_platform_admin_allows_super_admin(monkeypatch, app, caller):
    monkeypatch.setattr(am, '_caller_is_platform_admin', lambda: True)
    resp, status = _route_response_decorator(
        am.require_platform_admin,
        path='/server/tenants',
        role='admin',
        is_platform_admin=True,
    )
    assert status == 200


def test_require_platform_admin_allows_service_role(monkeypatch, app, caller):
    """Service / X-API-Key callers always pass (host callbacks, CI)."""
    monkeypatch.setattr(am, '_caller_is_platform_admin', lambda: False)
    resp, status = _route_response_decorator(
        am.require_platform_admin,
        path='/server/tenants',
        role='service',
        is_platform_admin=False,
    )
    assert status == 200


# ---- @require_team_in_tenant ---------------------------------------------


def test_require_team_in_tenant_blocks_cross_tenant(monkeypatch, app, caller):
    """Caller belongs to tenant A, names a team in tenant B — 403."""
    monkeypatch.setattr(am, '_caller_is_platform_admin', lambda: False)
    monkeypatch.setattr(am, '_caller_tenant_ids',
                        lambda: {'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'})
    monkeypatch.setattr(am, '_team_tenant_id_from_db',
                        lambda _tid: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')

    resp, status = _route_response_decorator(
        am.require_team_in_tenant,
        path='/server/teams/<team_id>',
        role='admin',
        is_platform_admin=False,
        tenant_ids={'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'},
    )
    # The decorator pulls team_id from URL kwargs; emulate that with a request
    # that has the path-param by going through the test client with a real path.
    # Re-do this assertion with a real path:
    app2 = Flask(__name__)

    @am.require_team_in_tenant
    def _h(team_id):
        return jsonify({'ok': True, 'team_id': team_id}), 200

    app2.add_url_rule('/server/teams/<team_id>', endpoint='h', view_func=_h, methods=['GET'])
    with app2.test_request_context('/server/teams/team-b', method='GET'):
        from flask import request
        request.user_role = 'admin'
        request.user_email = 'caller@vpt.local'
        request.user_tenant_ids = ['aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa']
        request.user_is_platform_admin = False
        with app2.test_client() as client:
            r = client.get('/server/teams/team-b')
            assert r.status_code == 403


def test_require_team_in_tenant_allows_same_tenant(monkeypatch, app, caller):
    monkeypatch.setattr(am, '_caller_is_platform_admin', lambda: False)
    monkeypatch.setattr(am, '_caller_tenant_ids',
                        lambda: {'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'})
    monkeypatch.setattr(am, '_team_tenant_id_from_db',
                        lambda _tid: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')

    app2 = Flask(__name__)

    @am.require_team_in_tenant
    def _h(team_id):
        return jsonify({'ok': True, 'team_id': team_id}), 200

    app2.add_url_rule('/server/teams/<team_id>', endpoint='h', view_func=_h, methods=['GET'])
    with app2.test_request_context('/server/teams/team-a', method='GET'):
        from flask import request
        request.user_role = 'admin'
        request.user_email = 'caller@vpt.local'
        request.user_tenant_ids = ['aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa']
        request.user_is_platform_admin = False
        with app2.test_client() as client:
            r = client.get('/server/teams/team-a')
            assert r.status_code == 200


def test_require_team_in_tenant_bypass_for_platform_admin(monkeypatch, app, caller):
    monkeypatch.setattr(am, '_caller_is_platform_admin', lambda: True)
    monkeypatch.setattr(am, '_caller_tenant_ids', lambda: set())
    monkeypatch.setattr(am, '_team_tenant_id_from_db',
                        lambda _tid: 'zzzzz-no-such-tenant')  # would 403 if reached

    app2 = Flask(__name__)

    @am.require_team_in_tenant
    def _h(team_id):
        return jsonify({'ok': True, 'team_id': team_id}), 200

    app2.add_url_rule('/server/teams/<team_id>', endpoint='h', view_func=_h, methods=['GET'])
    with app2.test_request_context('/server/teams/team-z', method='GET'):
        from flask import request
        request.user_role = 'admin'
        request.user_email = 'pa@vpt.local'
        request.user_tenant_ids = []
        request.user_is_platform_admin = True
        with app2.test_client() as client:
            r = client.get('/server/teams/team-z')
            assert r.status_code == 200