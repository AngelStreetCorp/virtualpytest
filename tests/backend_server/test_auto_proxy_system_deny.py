"""auto_proxy must not forward /server/system/* to the host's admin surface (contract 38).

The catch-all forwards any authenticated caller's /server/<x> to /host/<x> with the server's own
API key, so a host admin endpoint with no dedicated server route (runCommand, updatePrereqs,
applyBundle, envFiles) was reachable by testers/developers/viewers-on-GET.
"""
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

flask = pytest.importorskip('flask')


@pytest.fixture
def client():
    try:
        from backend_server.src.routes import auto_proxy as ap
    except Exception as e:  # backend deps missing in this environment
        pytest.skip(f'auto_proxy not importable: {e}')
    app = flask.Flask(__name__)
    app.register_blueprint(ap.auto_proxy_bp)
    return app.test_client(), ap


@pytest.mark.parametrize('method,path', [
    ('GET', '/server/system/updatePrereqs?host_name=h'),
    ('POST', '/server/system/runCommand'),
    ('POST', '/server/system/applyBundle'),
    ('POST', '/server/system/rollbackBundle'),
    ('GET', '/server/system/envFiles'),
    ('POST', '/server/system/restoreEnvFile'),
    ('POST', '/server/system/updateCore'),
    ('GET', '/server/system/vnc-info'),  # allowlist is POST only
    ('POST', '/server/server/system/runCommand'),  # double prefix is normalised, still denied
])
def test_system_endpoints_are_denied_without_calling_host(client, method, path):
    c, ap = client
    with patch.object(ap, 'proxy_to_host_with_params') as call:
        r = c.open(path, method=method, json={} if method == 'POST' else None)
    assert r.status_code == 404
    assert 'dedicated server route' in r.get_json()['error']
    call.assert_not_called()


def test_vnc_info_post_still_proxies(client):
    c, ap = client
    with patch.object(ap, 'proxy_to_host_with_params', return_value=({'success': True, 'password': ''}, 200)) as call:
        r = c.post('/server/system/vnc-info', json={'host_name': 'h'})
    assert r.status_code == 200
    assert call.call_args[0][0] == '/host/system/vnc-info'


def test_normal_passthrough_still_proxies(client):
    c, ap = client
    with patch.object(ap, 'proxy_to_host_with_params', return_value=({'success': True}, 200)) as call:
        r = c.post('/server/actions/executeBatch', json={'host_name': 'h', 'device_id': 'device1'})
    assert r.status_code == 200
    assert call.call_args[0][0] == '/host/actions/executeBatch'
