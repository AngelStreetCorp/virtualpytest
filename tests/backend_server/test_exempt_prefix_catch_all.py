"""An unauthenticated prefix exempts its own route only, never the auto_proxy catch-all behind it.

Found by the TASK-49 security review: /server/share/a/b/c and /server/health/%2e%2e/actions/...
reached auto_proxy (which calls a host with the server's API key) without any credential.
"""
import pytest
from flask import Flask

import backend_server.src.app as appmod
from backend_server.src.routes import auto_proxy

pytestmark = pytest.mark.unit


@pytest.fixture
def client(monkeypatch):
    for name in ('SERVER_OPEN_MODE', 'AUTO_SIGN_ENABLED', 'SERVER_PUBLIC_KEY'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('API_KEY', 'strong-key-xyz')
    monkeypatch.setenv('SUPABASE_JWT_SECRET', 'jwt-secret-xyz')
    monkeypatch.setenv('ENFORCE_FRONTEND_JWT', 'true')
    calls = []
    monkeypatch.setattr(auto_proxy, 'proxy_to_host_with_params',
                        lambda ep, m, d, q, timeout=0, headers=None: (calls.append(ep) or ({'success': True}, 200)))
    app = Flask('exempt-catch-all')
    appmod.configure_global_frontend_auth_guard(app)

    @app.route('/server/health')
    def health():
        return 'ok'

    app.register_blueprint(auto_proxy.auto_proxy_bp)
    c = app.test_client()
    c.calls = calls
    return c


def test_exempt_route_itself_stays_open(client):
    assert client.get('/server/health').status_code == 200


@pytest.mark.parametrize('path', ['/server/share/a/b/c', '/server/health/x', '/server/share/x'])
def test_catch_all_under_an_exempt_prefix_needs_auth(client, path):
    assert client.post(path, json={'host_name': 'h'}).status_code == 401
    assert client.calls == []


def test_dot_segments_never_reach_a_host(client):
    resp = client.open(method='POST', json={'host_name': 'h'},
                       environ_overrides={'PATH_INFO': '/server/health/../actions/executeBatch'})
    assert resp.status_code == 401
    assert client.calls == []
    # Even authenticated, a dot segment is refused by the proxy itself.
    resp = client.open(method='POST', json={'host_name': 'h'}, headers={'X-API-Key': 'strong-key-xyz'},
                       environ_overrides={'PATH_INFO': '/server/x/../actions/executeBatch'})
    assert resp.status_code == 400 and client.calls == []
