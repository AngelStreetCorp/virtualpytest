"""GET /server/deployment/history/<deployment_id> — the CoC guard's 30 s poll.

The route answered an opaque 500 for every DB-level problem: a transient
PostgREST failure (pool exhaustion, a reset connection under load), a process
that has no Supabase client at all, and a malformed id (PostgREST answers 400
for that, and the APIError became a 500). It also read executions without the
team scope every other route in the file applies.

These tests drive the real blueprint through a Flask test client with a fake
PostgREST chain, so each of those answers is pinned.
"""
import os
import sys

import pytest
from flask import Flask

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from backend_server.src.routes import server_deployment_routes as routes  # noqa: E402

pytestmark = pytest.mark.unit

TEAM = '00000000-0000-0000-0000-0000000000aa'
OTHER_TEAM = '00000000-0000-0000-0000-0000000000bb'
DEPLOYMENT = 'b1238a96-481c-4157-a5d3-5594cb1bd6d6'


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Records the PostgREST chain so the team scope can be asserted."""

    def __init__(self, rows=None, failures=0):
        self.rows = rows or []
        self.failures = failures
        self.calls = []
        self.executions = 0

    def select(self, columns):
        self.calls.append(('select', columns))
        return self

    def eq(self, column, value):
        self.calls.append(('eq', column, value))
        return self

    def order(self, column, desc=False):
        self.calls.append(('order', column, desc))
        return self

    def limit(self, count):
        self.calls.append(('limit', count))
        return self

    def execute(self):
        self.executions += 1
        self.calls.append(('execute',))
        if self.failures:
            self.failures -= 1
            raise RuntimeError('connection reset by peer')
        return _Result(self.rows)


class _Client:
    def __init__(self, query):
        self.query = query
        self.tables = []

    def table(self, name):
        self.tables.append(name)
        return self.query


@pytest.fixture
def query():
    return _Query(rows=[{'id': 'e1', 'deployment_id': DEPLOYMENT, 'status': 'completed'}])


@pytest.fixture
def client(query, monkeypatch):
    # The route only had a retry budget from the fix; without it these tests run
    # the old code and show the 500 it answered.
    if hasattr(routes, 'HISTORY_RETRY_SLEEP_S'):
        monkeypatch.setattr(routes, 'HISTORY_RETRY_SLEEP_S', 0)
    monkeypatch.setattr(routes, 'get_supabase_client', lambda: _Client(query))
    app = Flask(__name__)
    app.register_blueprint(routes.server_deployment_bp)
    return app.test_client()


def _get(client, deployment_id=DEPLOYMENT, team_id=TEAM):
    query = f'?team_id={team_id}' if team_id is not None else ''
    return client.get(f'/server/deployment/history/{deployment_id}{query}')


def test_history_returns_the_executions(client):
    response = _get(client)
    assert response.status_code == 200
    body = response.get_json()
    assert body['success'] is True
    assert [ex['id'] for ex in body['executions']] == ['e1']


def test_history_scopes_the_read_to_the_team(client, query):
    _get(client)
    assert ('eq', 'deployment_id', DEPLOYMENT) in query.calls
    assert ('eq', 'deployments.team_id', TEAM) in query.calls


def test_history_needs_a_team_id(client):
    response = _get(client, team_id=None)
    assert response.status_code == 400
    assert 'team_id' in response.get_json()['error']


def test_history_rejects_a_malformed_id_as_400(client, query):
    """PostgREST answers 400 for a non-uuid; that APIError used to reach the caller as 500."""
    response = _get(client, deployment_id='not-a-uuid')
    assert response.status_code == 400
    assert response.get_json()['error'] == 'deployment_id must be a UUID'
    assert query.executions == 0


def test_history_recovers_from_a_transient_failure(client, query):
    query.failures = 1
    response = _get(client)
    assert response.status_code == 200
    assert response.get_json()['executions'][0]['id'] == 'e1'
    assert query.executions == 2


def test_history_answers_503_when_the_database_stays_unreachable(client, query):
    query.failures = getattr(routes, 'HISTORY_READ_ATTEMPTS', 1)
    response = _get(client)
    assert response.status_code == 503
    body = response.get_json()
    assert body['error'] == 'deployment history is temporarily unavailable'


def test_history_answers_503_without_a_database_client(client, monkeypatch):
    monkeypatch.setattr(routes, 'get_supabase_client', lambda: None)
    response = _get(client)
    assert response.status_code == 503
    assert response.get_json()['error'] == 'database client is not available'


def test_history_of_another_team_reads_nothing(client, query):
    """The team filter is on the query, so another team's deployment returns no rows."""
    response = _get(client, team_id=OTHER_TEAM)
    assert response.status_code == 200
    assert ('eq', 'deployments.team_id', OTHER_TEAM) in query.calls