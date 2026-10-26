"""
BUG-0561 — global tenant-scope guard covers every team_id source.

The global `enforce_team_scope()` runs on every `/server/*` request. It must refuse
a team the caller does not belong to, regardless of where the team_id came from:
query string, JSON body, URL kwargs, or the `X-Team-Id` header. A per-route decorator
sweep would also work, but the global guard gives every team-scoped route the same
defense at once (BUG-0561).

Placed under tests/shared because the tests/backend_server conftest auto-skips when
the live backend isn't reachable; these tests use the Flask test request context,
not the live server.
"""
import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))


def test_requested_team_id_reads_query_string():
    from backend_server.src.lib import auth_middleware
    from flask import Flask
    app = Flask("t-guard")
    with app.test_request_context('/x', method='GET', query_string={'team_id': 'T1'}):
        assert auth_middleware._requested_team_id() == 'T1'


def test_requested_team_id_reads_url_kwargs():
    from backend_server.src.lib import auth_middleware
    from flask import Flask
    app = Flask("t-guard")
    with app.test_request_context('/x', method='GET'):
        from flask import request
        request.view_args = {'team_id': 'K1'}
        assert auth_middleware._requested_team_id() == 'K1'


def test_requested_team_id_reads_header():
    from backend_server.src.lib import auth_middleware
    from flask import Flask
    app = Flask("t-guard")
    with app.test_request_context('/x', method='GET', headers={'X-Team-Id': 'H1'}):
        assert auth_middleware._requested_team_id() == 'H1'


def test_requested_team_id_reads_json_body_for_writes():
    from backend_server.src.lib import auth_middleware
    from flask import Flask
    app = Flask("t-guard")
    with app.test_request_context('/x', method='POST', json={'team_id': 'B1'}):
        assert auth_middleware._requested_team_id() == 'B1'


def test_requested_team_id_returns_empty_for_read_with_no_source():
    from backend_server.src.lib import auth_middleware
    from flask import Flask
    app = Flask("t-guard")
    with app.test_request_context('/x', method='GET'):
        assert auth_middleware._requested_team_id() == ''


def test_enforce_team_scope_refuses_team_not_in_caller_team_ids(monkeypatch):
    from backend_server.src.lib import auth_middleware
    from flask import Flask
    monkeypatch.setattr(auth_middleware, '_caller_team_ids', lambda: {'T1'})
    monkeypatch.setattr(auth_middleware, '_caller_is_platform_admin', lambda: False)
    monkeypatch.setattr(auth_middleware, '_caller_tenant_ids', lambda: {'tnt-A'})
    monkeypatch.setattr(auth_middleware, '_team_tenant_id_from_db', lambda _t: 'tnt-A')
    app = Flask("t-guard")
    with app.test_request_context('/x', method='GET', query_string={'team_id': 'OTHER'}):
        from flask import request
        request.user_role = 'user'
        request.user_email = 'alice@vpt.local'
        result = auth_middleware.enforce_team_scope()
    assert result is not None
    body, status = result
    assert status == 403
    assert body.get_json()['error'] == 'Forbidden'


def test_enforce_team_scope_refuses_team_whose_tenant_is_outside_caller(monkeypatch):
    """The new BUG-0561 check: caller is a member of the team, but the team's
    tenant is not in the caller's tenant_ids claim. The guard must 403."""
    from backend_server.src.lib import auth_middleware
    from flask import Flask
    monkeypatch.setattr(auth_middleware, '_caller_team_ids', lambda: {'T1'})
    monkeypatch.setattr(auth_middleware, '_caller_is_platform_admin', lambda: False)
    monkeypatch.setattr(auth_middleware, '_caller_tenant_ids', lambda: {'tnt-A'})
    monkeypatch.setattr(auth_middleware, '_team_tenant_id_from_db', lambda _t: 'tnt-B')
    app = Flask("t-guard")
    with app.test_request_context('/x', method='GET', query_string={'team_id': 'T1'}):
        from flask import request
        request.user_role = 'user'
        request.user_email = 'alice@vpt.local'
        result = auth_middleware.enforce_team_scope()
    assert result is not None
    body, status = result
    assert status == 403
    assert 'tenant' in body.get_json()['message']


def test_enforce_team_scope_passes_when_team_matches(monkeypatch):
    from backend_server.src.lib import auth_middleware
    from flask import Flask
    monkeypatch.setattr(auth_middleware, '_caller_team_ids', lambda: {'T1'})
    monkeypatch.setattr(auth_middleware, '_caller_is_platform_admin', lambda: False)
    monkeypatch.setattr(auth_middleware, '_caller_tenant_ids', lambda: {'tnt-A'})
    monkeypatch.setattr(auth_middleware, '_team_tenant_id_from_db', lambda _t: 'tnt-A')
    app = Flask("t-guard")
    with app.test_request_context('/x', method='GET', query_string={'team_id': 'T1'}):
        from flask import request
        request.user_role = 'user'
        result = auth_middleware.enforce_team_scope()
    assert result is None


def test_enforce_team_scope_passes_for_service_role(monkeypatch):
    from backend_server.src.lib import auth_middleware
    from flask import Flask
    monkeypatch.setattr(auth_middleware, '_caller_team_ids', lambda: set())
    monkeypatch.setattr(auth_middleware, '_caller_is_platform_admin', lambda: False)
    app = Flask("t-guard")
    with app.test_request_context('/x', method='GET', query_string={'team_id': 'ANY'}):
        from flask import request
        request.user_role = 'service'
        result = auth_middleware.enforce_team_scope()
    assert result is None


def test_enforce_team_scope_passes_for_platform_admin(monkeypatch):
    from backend_server.src.lib import auth_middleware
    from flask import Flask
    monkeypatch.setattr(auth_middleware, '_caller_team_ids', lambda: set())
    monkeypatch.setattr(auth_middleware, '_caller_is_platform_admin', lambda: True)
    app = Flask("t-guard")
    with app.test_request_context('/x', method='GET', query_string={'team_id': 'ANY'}):
        from flask import request
        request.user_role = 'user'
        result = auth_middleware.enforce_team_scope()
    assert result is None


def test_enforce_team_scope_passes_when_no_team_named(monkeypatch):
    from backend_server.src.lib import auth_middleware
    from flask import Flask
    monkeypatch.setattr(auth_middleware, '_caller_is_platform_admin', lambda: False)
    app = Flask("t-guard")
    with app.test_request_context('/x', method='GET'):
        from flask import request
        request.user_role = 'user'
        result = auth_middleware.enforce_team_scope()
    assert result is None


def test_enforce_team_scope_passes_when_team_does_not_exist(monkeypatch):
    """If the team_id is unknown, the global guard defers to the route's own 404."""
    from backend_server.src.lib import auth_middleware
    from flask import Flask
    monkeypatch.setattr(auth_middleware, '_caller_team_ids', lambda: {'T1'})
    monkeypatch.setattr(auth_middleware, '_caller_is_platform_admin', lambda: False)
    monkeypatch.setattr(auth_middleware, '_caller_tenant_ids', lambda: {'tnt-A'})
    monkeypatch.setattr(auth_middleware, '_team_tenant_id_from_db', lambda _t: None)
    app = Flask("t-guard")
    with app.test_request_context('/x', method='GET', query_string={'team_id': 'T1'}):
        from flask import request
        request.user_role = 'user'
        result = auth_middleware.enforce_team_scope()
    assert result is None


def test_enforce_team_scope_catches_team_id_from_url_kwargs(monkeypatch):
    """The BUG-0561 widening: a route that takes team_id from URL kwargs is now
    refused if the team's tenant is not in the caller's tenant_ids claim."""
    from backend_server.src.lib import auth_middleware
    from flask import Flask
    monkeypatch.setattr(auth_middleware, '_caller_team_ids', lambda: {'T-KW'})
    monkeypatch.setattr(auth_middleware, '_caller_is_platform_admin', lambda: False)
    monkeypatch.setattr(auth_middleware, '_caller_tenant_ids', lambda: {'tnt-A'})
    monkeypatch.setattr(auth_middleware, '_team_tenant_id_from_db', lambda _t: 'tnt-B')
    app = Flask("t-guard")
    with app.test_request_context('/x', method='GET'):
        from flask import request
        request.user_role = 'user'
        request.view_args = {'team_id': 'T-KW'}
        result = auth_middleware.enforce_team_scope()
    assert result is not None
    assert result[1] == 403


def test_enforce_team_scope_catches_team_id_from_header(monkeypatch):
    from backend_server.src.lib import auth_middleware
    from flask import Flask
    monkeypatch.setattr(auth_middleware, '_caller_team_ids', lambda: {'T-H'})
    monkeypatch.setattr(auth_middleware, '_caller_is_platform_admin', lambda: False)
    monkeypatch.setattr(auth_middleware, '_caller_tenant_ids', lambda: {'tnt-A'})
    monkeypatch.setattr(auth_middleware, '_team_tenant_id_from_db', lambda _t: 'tnt-B')
    app = Flask("t-guard")
    with app.test_request_context('/x', method='GET', headers={'X-Team-Id': 'T-H'}):
        from flask import request
        request.user_role = 'user'
        result = auth_middleware.enforce_team_scope()
    assert result is not None
    assert result[1] == 403