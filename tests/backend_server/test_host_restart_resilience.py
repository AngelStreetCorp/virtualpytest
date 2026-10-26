"""Unit tests: a host that is restarting must not answer 502 straight away (TASK-169).

The server proxies a picture request to a lab host. A deploy restarts the host and
the server at the same time, so for a second or two the host refuses the
connection — and the proxy turned that into an HTTP 502 for whoever asked (the
Atlas / stb benchmark).

- `_fetch_host_file` retries ONCE when the host refuses the connection, and does
  NOT retry a timeout: a timeout means the host answered, and the answer is what
  it is.
- The server's exit cleanup runs ONCE, not once from the signal handler and once
  from atexit: each agent's stop joins a worker thread with a timeout, so doing
  it twice is twice the waiting inside the unit's TimeoutStopSec.
- The gunicorn `graceful_timeout` is below the unit's TimeoutStopSec, so the
  arbiter gives up on a busy worker before systemd gives up on the whole unit.

Runs offline: `requests` is stubbed, no host and no database.
"""

import pytest
import requests

from backend_server.src.routes import server_monitoring_routes

pytestmark = pytest.mark.unit


class _Response:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.headers = {'Content-Type': 'image/jpeg'}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f'{self.status_code}')

    def iter_content(self, chunk_size=8192):
        yield b'jpeg-bytes'


def test_a_refused_connection_is_retried_once(monkeypatch):
    calls = []

    def _get(url, stream=False, timeout=None):
        calls.append(url)
        if len(calls) == 1:
            raise requests.exceptions.ConnectionError('connection refused')
        return _Response()

    monkeypatch.setattr(server_monitoring_routes.requests, 'get', _get)
    monkeypatch.setattr(server_monitoring_routes.time, 'sleep', lambda _s: None)

    response = server_monitoring_routes._fetch_host_file('http://host:6109/file.jpg')

    assert response.status_code == 200
    assert len(calls) == 2


def test_a_refused_connection_is_given_up_after_the_retry(monkeypatch):
    calls = []

    def _get(url, stream=False, timeout=None):
        calls.append(url)
        raise requests.exceptions.ConnectionError('connection refused')

    monkeypatch.setattr(server_monitoring_routes.requests, 'get', _get)
    monkeypatch.setattr(server_monitoring_routes.time, 'sleep', lambda _s: None)

    with pytest.raises(requests.exceptions.ConnectionError):
        server_monitoring_routes._fetch_host_file('http://host:6109/file.jpg')

    # one attempt + one retry, and no more
    assert len(calls) == 2


def test_a_timeout_is_not_retried(monkeypatch):
    calls = []

    def _get(url, stream=False, timeout=None):
        calls.append(url)
        raise requests.exceptions.ReadTimeout('too slow')

    monkeypatch.setattr(server_monitoring_routes.requests, 'get', _get)
    monkeypatch.setattr(server_monitoring_routes.time, 'sleep', lambda _s: None)

    with pytest.raises(requests.exceptions.ReadTimeout):
        server_monitoring_routes._fetch_host_file('http://host:6109/file.jpg')

    assert len(calls) == 1


def test_the_server_exit_cleanup_runs_only_once(monkeypatch):
    from backend_server.src import app as server_app

    stopped = []

    class _Agent:
        background_running = True

        def stop_background(self):
            stopped.append('stopped')

    monkeypatch.setattr(server_app, '_background_agents', {'atlas': _Agent()}, raising=False)
    monkeypatch.setattr(server_app, '_cleanup_done', False, raising=False)

    cleanup = server_app.setup_server_cleanup()
    cleanup()
    cleanup()

    assert stopped == ['stopped']


def test_the_gunicorn_graceful_timeout_is_inside_the_unit_timeout():
    """The arbiter must give up on a busy worker before systemd gives up on the unit."""
    from backend_server.src.lib.server import gunicorn_app

    source = gunicorn_app.__file__
    with open(source, 'r', encoding='utf-8') as handle:
        text = handle.read()
    assert "'graceful_timeout': 10" in text
