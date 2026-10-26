"""The server log must not be flooded by the per-request auth checks (BUG-0786).

"Role check passed" and "Permission check passed" were printed on every allowed
request. During an incident they were two thirds of what the operator read, and
they carried no information: the check passing is the normal case, and the
activity audit trail records what the request was allowed to do. The refusals
stay logged — they are events.

These tests pin the new behaviour: silent by default, back on with AUTH_TRACE=1.
"""

import pytest
from flask import Flask, request

from backend_server.src.lib import auth_middleware
from backend_server.src.lib.auth_middleware import require_permission, require_role

pytestmark = pytest.mark.unit  # no live backend needed (conftest: require_server_reachable)


@pytest.fixture
def app(monkeypatch):
    """A Flask app with one route behind @require_role and one behind @require_permission."""
    flask_app = Flask(__name__)

    monkeypatch.setattr(auth_middleware, 'principal_holds_permission', lambda permission: True)

    @flask_app.before_request
    def _as_admin():
        # What @require_user_auth leaves behind for the route decorators.
        request.user_role = 'admin'
        request.user_email = 'someone@example.com'

    @flask_app.get('/server/thing')
    @require_role('admin')
    def _role_route():
        return {'ok': True}

    @flask_app.get('/server/other')
    @require_permission('testcases:hide')
    def _permission_route():
        return {'ok': True}

    return flask_app


def _call(app, path, monkeypatch, trace):
    if trace:
        monkeypatch.setenv('AUTH_TRACE', '1')
    else:
        monkeypatch.delenv('AUTH_TRACE', raising=False)

    with app.test_request_context(path):
        return app.test_client().get(path).status_code


def test_a_successful_permission_check_is_not_printed(app, monkeypatch, capsys):
    """The default: the log stays clean."""
    assert _call(app, '/server/other', monkeypatch, trace=False) == 200
    out = capsys.readouterr().out
    assert 'Permission check passed' not in out
    assert 'Role check passed' not in out


def test_a_successful_role_check_is_not_printed(app, monkeypatch, capsys):
    assert _call(app, '/server/thing', monkeypatch, trace=False) == 200
    out = capsys.readouterr().out
    assert 'Role check passed' not in out
    assert 'Permission check passed' not in out


def test_the_checks_come_back_with_auth_trace(app, monkeypatch, capsys):
    """AUTH_TRACE=1 turns them on for somebody chasing an auth problem."""
    assert _call(app, '/server/other', monkeypatch, trace=True) == 200
    out = capsys.readouterr().out
    assert 'Permission check passed: testcases:hide' in out

    assert _call(app, '/server/thing', monkeypatch, trace=True) == 200
    out = capsys.readouterr().out
    assert 'Role check passed: admin' in out


@pytest.mark.parametrize('trace', [False, True])
def test_a_refused_permission_is_logged_with_or_without_trace(app, monkeypatch, caplog, trace):
    """The refusal line is an event: it must not depend on AUTH_TRACE."""
    monkeypatch.setattr(auth_middleware, 'principal_holds_permission', lambda permission: False)

    @app.before_request
    def _ids():
        request.user_id = 'user-123'

    with caplog.at_level('WARNING'):
        assert _call(app, '/server/other', monkeypatch, trace=trace) == 403
    text = caplog.text
    assert 'Permission check refused' in text
    assert 'user-123' in text and 'admin' in text and 'testcases:hide' in text and '/server/other' in text


def test_a_refused_role_is_logged(app, monkeypatch, caplog):
    @app.before_request
    def _viewer():
        request.user_role = 'viewer'

    with caplog.at_level('WARNING'):
        assert _call(app, '/server/thing', monkeypatch, trace=False) == 403
    assert 'Role check refused' in caplog.text
    assert 'viewer' in caplog.text and '/server/thing' in caplog.text
