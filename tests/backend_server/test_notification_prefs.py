"""Unit tests: TASK-145 notification preferences route and db module.

- The user comes from the verified principal; a user row is always the caller's own.
- Team / workspace / project rows and `locked` need the admin role; a user cannot write an admin-locked category.
- A viewer may write its own rows (path exempt from the read-only floor), nothing else.
- The db module filters every query by team_id.

Runs offline: the database module is stubbed.
"""
import pytest
from flask import Flask, request

from backend_server.src.lib import auth_middleware
from backend_server.src.routes import server_notification_prefs_routes as routes
from shared.src.lib.database import notification_prefs_db

pytestmark = pytest.mark.unit

TEAM = 't-1'


def _unwrap(fn):
    while hasattr(fn, '__wrapped__'):
        fn = fn.__wrapped__
    return fn


@pytest.fixture
def calls(monkeypatch):
    class Log(list):
        existing = []

    log = Log()
    log.existing = existing = []
    monkeypatch.setattr(routes.notification_prefs_db, 'list_prefs',
                        lambda t, u: log.append(('list', t, u)) or existing)
    monkeypatch.setattr(routes.notification_prefs_db, 'upsert_pref', lambda t, row: log.append(('upsert', t, row)))
    monkeypatch.setattr(routes.notification_prefs_db, 'delete_pref', lambda *a: log.append(('delete',) + a))
    return log


def _call(fn, method, user_id='u-1', role='viewer', **kwargs):
    with Flask('t').test_request_context('/server/notification-prefs', method=method, **kwargs):
        request.user_id = user_id
        request.user_role = role
        response = _unwrap(fn)()
        return response if isinstance(response, tuple) else (response, 200)


def _row(**over):
    return {'scope_type': 'user', 'scope_id': 'ignored', 'category': 'script', 'bell': True, 'toast': True,
            'min_severity': 'warning', **over}


def test_list_scopes_by_team_and_caller(calls):
    response, status = _call(routes.list_prefs, 'GET', role='admin', query_string={'team_id': TEAM})
    assert status == 200 and response.get_json()['is_admin'] is True
    assert calls == [('list', TEAM, 'u-1')]


def test_user_row_is_stamped_with_the_principal_and_cannot_lock(calls):
    _, status = _call(routes.upsert_pref, 'PUT', json={'team_id': TEAM, 'row': _row(user_id='someone-else', locked=True)})
    assert status == 200
    _, t, row = calls[-1]
    assert t == TEAM and row['user_id'] == 'u-1' and row['scope_id'] == 'u-1' and row['locked'] is False


@pytest.mark.parametrize('scope', ['team', 'workspace', 'project'])
def test_shared_rows_need_admin(calls, scope):
    body = {'team_id': TEAM, 'row': _row(scope_type=scope, scope_id='x')}
    _, status = _call(routes.upsert_pref, 'PUT', role='viewer', json=body)
    assert status == 403 and not any(c[0] == 'upsert' for c in calls)
    _, status = _call(routes.upsert_pref, 'PUT', role='admin', json=body)
    assert status == 200
    assert calls[-1][2]['user_id'] == '' and calls[-1][2]['scope_id'] == 'x'


def test_user_cannot_override_an_admin_lock(calls):
    calls.existing.append({'scope_type': 'team', 'category': 'script', 'locked': True})
    _, status = _call(routes.upsert_pref, 'PUT', json={'team_id': TEAM, 'row': _row()})
    assert status == 403
    _, status = _call(routes.upsert_pref, 'PUT', json={'team_id': TEAM, 'row': _row(category='device')})
    assert status == 200


@pytest.mark.parametrize('row', [_row(category='nope'), _row(scope_type='galaxy'), _row(min_severity='fatal')])
def test_invalid_rows_are_refused(calls, row):
    _, status = _call(routes.upsert_pref, 'PUT', json={'team_id': TEAM, 'row': row})
    assert status == 400


def test_no_user_no_prefs(calls):
    _, status = _call(routes.list_prefs, 'GET', user_id='', query_string={'team_id': TEAM})
    assert status == 403


def test_delete_scopes_user_rows_to_the_caller(calls):
    _, status = _call(routes.delete_pref, 'DELETE', json={'team_id': TEAM, 'scope_type': 'user', 'scope_id': 'u-9', 'category': 'script'})
    assert status == 200 and calls == [('delete', TEAM, 'user', 'u-1', 'u-1', 'script')]
    _, status = _call(routes.delete_pref, 'DELETE', json={'team_id': TEAM, 'scope_type': 'team', 'scope_id': TEAM, 'category': 'script'})
    assert status == 403


@pytest.mark.parametrize('method', ['PUT', 'DELETE'])
def test_viewer_write_floor(method):
    with Flask('t').test_request_context('/server/notification-prefs', method=method):
        request.user_role = 'viewer'
        assert auth_middleware.enforce_viewer_read_only() is None


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


def test_db_module_filters_every_query_by_team(monkeypatch):
    log = []
    monkeypatch.setattr(notification_prefs_db, 'get_supabase', lambda: type('S', (), {'table': lambda self, n: _Query(log)})())
    notification_prefs_db.list_prefs(TEAM, 'u-1')
    notification_prefs_db.delete_pref(TEAM, 'user', 'u-1', 'u-1', 'script')
    eqs = [e[1:] for e in log if e[0] == 'eq']
    assert eqs.count(('team_id', TEAM)) == 2


def test_device_row_is_the_callers_own_and_viewer_may_write_it(calls):
    body = {'team_id': TEAM, 'row': _row(scope_type='device', scope_id='dev-7', category='device', bell=False, toast=False)}
    _, status = _call(routes.upsert_pref, 'PUT', role='viewer', json=body)
    assert status == 200
    _, t, row = calls[-1]
    assert t == TEAM and row['scope_type'] == 'device' and row['scope_id'] == 'dev-7' and row['user_id'] == 'u-1' and row['locked'] is False
    body['row']['scope_id'] = ''
    _, status = _call(routes.upsert_pref, 'PUT', role='viewer', json=body)
    assert status == 400


def test_device_row_delete_is_scoped_to_the_caller(calls):
    _, status = _call(routes.delete_pref, 'DELETE', json={'team_id': TEAM, 'scope_type': 'device', 'scope_id': 'dev-7', 'category': 'device'})
    assert status == 200 and calls == [('delete', TEAM, 'device', 'dev-7', 'u-1', 'device')]
