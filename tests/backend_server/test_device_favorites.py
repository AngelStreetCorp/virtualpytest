"""Unit tests: TASK-99 per-user device favorites.

- The route takes the user from the verified principal, scopes every call by team_id AND user_id,
  and keeps host_name in the key.
- A principal with no user (service key) cannot star.
- A viewer may PUT/DELETE (the path is exempt from the viewer read-only floor); other viewer writes stay blocked.
- The DB module filters every query by team_id and user_id.

Runs offline: the database module is stubbed.
"""
import pytest
from flask import Flask, request

from backend_server.src.lib import auth_middleware
from backend_server.src.routes import server_device_favorites_routes as routes
from shared.src.lib.database import device_favorites_db

pytestmark = pytest.mark.unit

TEAM = 't-1'


def _unwrap(fn):
    while hasattr(fn, '__wrapped__'):
        fn = fn.__wrapped__
    return fn


@pytest.fixture
def calls(monkeypatch):
    log = []
    monkeypatch.setattr(routes.device_favorites_db, 'list_favorites',
                        lambda t, u: log.append(('list', t, u)) or [{'host_name': 'h1', 'device_id': 'device1'}])
    monkeypatch.setattr(routes.device_favorites_db, 'add_favorite', lambda *a: log.append(('add',) + a))
    monkeypatch.setattr(routes.device_favorites_db, 'remove_favorite', lambda *a: log.append(('remove',) + a))
    return log


def _call(fn, method, user_id='u-1', **kwargs):
    with Flask('t').test_request_context('/server/device-favorites', method=method, **kwargs):
        request.user_id = user_id
        response = _unwrap(fn)()
        return response if isinstance(response, tuple) else (response, 200)


def test_list_scopes_by_team_and_the_callers_user(calls):
    response, status = _call(routes.list_favorites, 'GET', query_string={'team_id': TEAM})
    assert status == 200
    assert response.get_json()['favorites'] == [{'host_name': 'h1', 'device_id': 'device1'}]
    assert calls == [('list', TEAM, 'u-1')]


def test_user_comes_from_the_principal_not_the_request(calls):
    _call(routes.add_favorite, 'PUT', json={'team_id': TEAM, 'host_name': 'h1', 'device_id': 'device1', 'user_id': 'someone-else'})
    assert calls == [('add', TEAM, 'u-1', 'h1', 'device1')]


def test_remove_accepts_query_params_and_keeps_the_host_in_the_key(calls):
    _, status = _call(routes.remove_favorite, 'DELETE',
                      query_string={'team_id': TEAM, 'host_name': 'h2', 'device_id': 'device1'})
    assert status == 200
    assert calls == [('remove', TEAM, 'u-1', 'h2', 'device1')]


@pytest.mark.parametrize('body', [{'team_id': TEAM, 'device_id': 'd'}, {'team_id': TEAM, 'host_name': 'h'},
                                  {'host_name': 'h', 'device_id': 'd'}])
def test_write_needs_team_host_and_device(calls, body):
    _, status = _call(routes.add_favorite, 'PUT', json=body)
    assert status == 400 and calls == []


def test_a_principal_without_a_user_cannot_star(calls):
    _, status = _call(routes.add_favorite, 'PUT', user_id='',
                      json={'team_id': TEAM, 'host_name': 'h', 'device_id': 'd'})
    assert status == 403 and calls == []
    _, status = _call(routes.list_favorites, 'GET', user_id=None, query_string={'team_id': TEAM})
    assert status == 403


@pytest.mark.parametrize('method', ['PUT', 'DELETE'])
def test_viewer_may_star_but_not_write_elsewhere(method):
    with Flask('t').test_request_context('/server/device-favorites', method=method):
        request.user_role = 'viewer'
        assert auth_middleware.enforce_viewer_read_only() is None
    with Flask('t').test_request_context('/server/device-flags/h/d', method=method):
        request.user_role = 'viewer'
        assert auth_middleware.enforce_viewer_read_only()[1] == 403


class _Query:
    def __init__(self, log):
        self.log = log

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.log.append((name,) + args)
            return self
        return record

    def execute(self):
        class R:
            data = []
        return R()


def test_db_module_filters_every_query_by_team_and_user(monkeypatch):
    log = []
    monkeypatch.setattr(device_favorites_db, 'get_supabase', lambda: type('S', (), {'table': lambda self, n: _Query(log)})())
    device_favorites_db.list_favorites(TEAM, 'u-1')
    device_favorites_db.remove_favorite(TEAM, 'u-1', 'h1', 'device1')
    eqs = [e[1:] for e in log if e[0] == 'eq']
    assert eqs.count(('team_id', TEAM)) == 2 and eqs.count(('user_id', 'u-1')) == 2
    assert ('host_name', 'h1') in eqs and ('device_id', 'device1') in eqs
