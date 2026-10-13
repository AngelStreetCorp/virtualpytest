"""
Unit tests for the two small-ops routes added in TASK-74:
- /host/system/checkStorage  (df -h equivalent)
- /host/system/pingHost     (TCP probe to backend port 6109)

Both routes are intentionally lightweight: they do not touch any device
controller, they do not require an admin token, and they always answer
within their bounded timeouts. The tests use Flask's test_client so they
run without a live backend_host.
"""
import platform

import pytest


@pytest.fixture
def app():
    """Minimal Flask app that registers the host_system blueprint only."""
    from flask import Flask
    from backend_host.src.routes.host_system_routes import host_system_bp

    flask_app = Flask(__name__)
    flask_app.register_blueprint(host_system_bp)
    flask_app.config['TESTING'] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


# --- /host/system/checkStorage ---------------------------------------------

def test_check_storage_returns_known_shape(client):
    """The route returns {success, host, rows: [...]} on every platform."""
    response = client.get('/host/system/checkStorage')
    assert response.status_code == 200
    body = response.get_json()
    assert body.get('success') is True
    assert isinstance(body.get('host'), str) and body['host']
    assert isinstance(body.get('rows'), list)
    assert len(body['rows']) >= 1, 'at least one filesystem must be reported'


def test_check_storage_rows_have_required_fields(client):
    """Each row has filesystem / size / used / available / use_pct / mountpoint."""
    response = client.get('/host/system/checkStorage')
    rows = response.get_json().get('rows') or []
    required = {'filesystem', 'size', 'used', 'available', 'use_pct', 'mountpoint'}
    for row in rows:
        assert required.issubset(set(row.keys())), f"row missing fields: {required - set(row.keys())}"
        assert isinstance(row['size'], int) and row['size'] > 0
        assert isinstance(row['used'], int) and 0 <= row['used'] <= row['size']
        assert isinstance(row['available'], int) and row['available'] > 0
        assert isinstance(row['use_pct'], (int, float)) and 0.0 <= row['use_pct'] <= 100.0


# --- /host/system/pingHost --------------------------------------------------

def test_ping_host_responds_with_required_fields(client):
    """The route returns {success, host, rtt_ms, backend_port, ...}."""
    response = client.get('/host/system/pingHost')
    assert response.status_code == 200
    body = response.get_json()
    # success may be True or False depending on whether the test client can
    # actually reach 127.0.0.1:6109 — both are valid answers; what matters
    # is that the route returned the shape, not that the host is up.
    assert 'success' in body
    assert isinstance(body.get('host'), str) and body['host']
    assert isinstance(body.get('rtt_ms'), (int, float))
    assert body.get('rtt_ms') >= 0
    assert body.get('backend_port') == 6109
    # boot_time is best-effort (psutil); either a string or None.
    assert body.get('boot_time') is None or isinstance(body['boot_time'], str)


def test_ping_host_is_fast(client):
    """The route bounds its own socket connect to 200 ms. We allow 1 s total
    for the Flask round-trip in case CI is slow."""
    import time
    start = time.monotonic()
    response = client.get('/host/system/pingHost')
    elapsed = time.monotonic() - start
    assert response.status_code == 200
    assert elapsed < 1.0, f"pingHost took {elapsed:.3f}s — exceeds the 1s bound"
