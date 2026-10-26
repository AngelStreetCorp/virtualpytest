"""Unit tests: TASK-100 per-user executable favorites.

- The route takes the user from the verified principal, scopes every call by team_id AND user_id,
  and keeps kind in the key.
- Only the four known kinds are accepted.
- A principal with no user (service key) cannot star.
- A viewer may PUT/DELETE (the path is exempt from the viewer read-only floor); other viewer writes stay blocked.
- The DB module filters every query by team_id and user_id.

Runs offline: the database module is stubbed.
"""
import pytest
from flask import Flask, request

from backend_server.src.lib import auth_middleware
from backend_server.src.routes import server_executable_favorites_routes as routes
from shared.src.lib.database import executable_favorites_db

pytestmark = pytest.mark.unit

TEAM = 't-1'


def _unwrap(fn):
    while hasattr(fn, '__wrapped__'):
        fn = fn.__wrapped__
    return fn


@pytest.fixture
def calls(monkeypatch):
    log = []
    monkeypatch.setattr(routes.executable_favorites_db, 'list_favorites',
                        lambda *a: log.append(('list',) + a) or [{'kind': 'script', 'item_id': 'goto.py'}])
    monkeypatch.setattr(routes.executable_favorites_db, 'add_favorite', lambda *a: log.append(('add',) + a))
    monkeypatch.setattr(routes.executable_favorites_db, 'remove_favorite', lambda *a: log.append(('remove',) + a))
    return log


def _call(fn, method, user_id='u-1', **kwargs):
    with Flask('t').test_request_context('/server/executable-favorites', method=method, **kwargs):
        request.user_id = user_id
        response = _unwrap(fn)()
        return response if isinstance(response, tuple) else (response, 200)


def test_list_scopes_by_team_and_the_callers_user(calls):
    response, status = _call(routes.list_favorites, 'GET', query_string={'team_id': TEAM})
    assert status == 200
    assert response.get_json()['favorites'] == [{'kind': 'script', 'item_id': 'goto.py'}]
    assert calls == [('list', TEAM, 'u-1', None)]


def test_list_can_be_narrowed_to_one_kind(calls):
    _call(routes.list_favorites, 'GET', query_string={'team_id': TEAM, 'kind': 'campaign'})
    assert calls == [('list', TEAM, 'u-1', 'campaign')]
    _, status = _call(routes.list_favorites, 'GET', query_string={'team_id': TEAM, 'kind': 'device'})
    assert status == 400


def test_user_comes_from_the_principal_not_the_request(calls):
    _call(routes.add_favorite, 'PUT',
          json={'team_id': TEAM, 'kind': 'testcase', 'item_id': 'tc-1', 'user_id': 'someone-else'})
    assert calls == [('add', TEAM, 'u-1', 'testcase', 'tc-1')]


def test_remove_accepts_query_params_and_keeps_the_kind_in_the_key(calls):
    _, status = _call(routes.remove_favorite, 'DELETE',
                      query_string={'team_id': TEAM, 'kind': 'virtual_script', 'item_id': 'goto'})
    assert status == 200
    assert calls == [('remove', TEAM, 'u-1', 'virtual_script', 'goto')]


@pytest.mark.parametrize('body', [{'team_id': TEAM, 'item_id': 'x'}, {'team_id': TEAM, 'kind': 'script'},
                                  {'kind': 'script', 'item_id': 'x'}])
def test_write_needs_team_kind_and_item(calls, body):
    _, status = _call(routes.add_favorite, 'PUT', json=body)
    assert status == 400 and calls == []


def test_write_rejects_an_unknown_kind(calls):
    _, status = _call(routes.add_favorite, 'PUT', json={'team_id': TEAM, 'kind': 'device', 'item_id': 'x'})
    assert status == 400 and calls == []


def test_a_principal_without_a_user_cannot_star(calls):
    _, status = _call(routes.add_favorite, 'PUT', user_id='',
                      json={'team_id': TEAM, 'kind': 'script', 'item_id': 'a.py'})
    assert status == 403 and calls == []
    _, status = _call(routes.list_favorites, 'GET', user_id=None, query_string={'team_id': TEAM})
    assert status == 403


@pytest.mark.parametrize('method', ['PUT', 'DELETE'])
def test_viewer_may_star_but_not_write_elsewhere(method):
    with Flask('t').test_request_context('/server/executable-favorites', method=method):
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
    monkeypatch.setattr(executable_favorites_db, 'get_supabase',
                        lambda: type('S', (), {'table': lambda self, n: _Query(log)})())
    executable_favorites_db.list_favorites(TEAM, 'u-1')
    executable_favorites_db.list_favorites(TEAM, 'u-1', 'script')
    executable_favorites_db.remove_favorite(TEAM, 'u-1', 'testcase', 'tc-1')
    eqs = [e[1:] for e in log if e[0] == 'eq']
    assert eqs.count(('team_id', TEAM)) == 3 and eqs.count(('user_id', 'u-1')) == 3
    assert ('kind', 'testcase') in eqs and ('item_id', 'tc-1') in eqs and ('kind', 'script') in eqs
