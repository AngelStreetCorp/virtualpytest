"""Server proxy for the Settings monitoring-profile picker (TASK-90 follow-up):
GET /server/settings/host-monitor-profiles and .../status forward to the selected host, behind settings.general:view.
No live server: the Flask app is built here and the host call is patched."""
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


@pytest.fixture
def client():
    from backend_server.src.routes.server_settings_routes import server_settings_bp
    app = Flask(__name__)
    app.register_blueprint(server_settings_bp)
    app.config['TESTING'] = True
    return app.test_client()


def _unwrap(fn):
    while hasattr(fn, '__wrapped__'):
        fn = fn.__wrapped__
    return fn


def _call(path, fn_name, host_ret=None, host=True):
    from backend_server.src.routes import server_settings_routes as r
    app = Flask(__name__)
    manager = MagicMock()
    manager.get_host.return_value = {'host_name': 'h1'} if host else None
    with app.test_request_context(path), \
            patch('backend_server.src.lib.utils.server_utils.get_host_manager', return_value=manager), \
            patch('shared.src.lib.utils.build_url_utils.call_host', return_value=host_ret or ({'success': True}, 200)) as ch:
        resp = _unwrap(getattr(r, fn_name))()
        resp, code = (resp if isinstance(resp, tuple) else (resp, 200))
        return resp.get_json(), code, ch


def test_list_is_forwarded_to_the_host():
    body, code, ch = _call('/x?host_name=h1', 'host_monitor_profiles', ({'success': True, 'profiles': []}, 200))
    assert code == 200 and body['profiles'] == []
    assert ch.call_args.args[1] == '/host/monitor/profiles' and ch.call_args.kwargs['method'] == 'GET'


def test_status_is_forwarded_to_the_host():
    _, _, ch = _call('/x?host_name=h1', 'host_monitor_profiles_status')
    assert ch.call_args.args[1] == '/host/monitor/profiles/status'


def test_host_name_is_required():
    body, code, _ = _call('/x', 'host_monitor_profiles')
    assert code == 400 and 'host_name' in body['error']


def test_unknown_host_is_404():
    _, code, _ = _call('/x?host_name=nope', 'host_monitor_profiles', host=False)
    assert code == 404


def test_host_error_status_is_passed_through():
    _, code, _ = _call('/x?host_name=h1', 'host_monitor_profiles', ({'success': False}, 502))
    assert code == 502


@pytest.mark.parametrize('path', ['/server/settings/host-monitor-profiles', '/server/settings/host-monitor-profiles/status'])
def test_routes_are_guarded_by_user_auth(client, path):
    """No credentials: the route must not answer 200."""
    assert client.get(path + '?host_name=h1').status_code in (401, 403, 500)


def test_save_still_needs_edit_permission():
    """The profile is saved through /host-config, which stays behind settings.general:edit."""
    import inspect
    from backend_server.src.routes import server_settings_routes as r
    src = inspect.getsource(r)
    assert "route('/host-config'" in src
    block = src[src.index("route('/host-config'"):src.index("def host_config")]
    assert "settings.general:edit" in block
