"""Unit tests: TASK-145 notification history (per-account bell / page history).

- The user comes from the verified principal; every db call carries team_id and that user.
- Bad items are dropped, a batch is capped, a viewer may write its own history.
- The db module filters every query by team_id and user_id, and trims to 200.

Runs offline: the database module is stubbed.
"""
import pytest
from flask import Flask, request

from backend_server.src.lib import auth_middleware
from backend_server.src.routes import server_notifications_routes as routes
from shared.src.lib.database import notifications_db

pytestmark = pytest.mark.unit

TEAM = 't-1'


def _unwrap(fn):
    while hasattr(fn, '__wrapped__'):
        fn = fn.__wrapped__
    return fn


@pytest.fixture
def calls(monkeypatch):
    log = []
    monkeypatch.setattr(routes.notifications_db, 'list_notifications',
                        lambda t, u: log.append(('list', t, u)) or [{'id': 'a', 'to_path': '/x', 'ts': 1}])
    monkeypatch.setattr(routes.notifications_db, 'upsert_notifications', lambda t, u, rows: log.append(('upsert', t, u, rows)))
    monkeypatch.setattr(routes.notifications_db, 'mark_read', lambda *a: log.append(('read',) + a))
    monkeypatch.setattr(routes.notifications_db, 'dismiss', lambda *a: log.append(('dismiss',) + a))
    return log


def _call(fn, method, user_id='u-1', role='viewer', **kwargs):
    with Flask('t').test_request_context('/server/notifications', method=method, **kwargs):
        request.user_id = user_id
        request.user_role = role
        response = _unwrap(fn)()
        return response if isinstance(response, tuple) else (response, 200)


def _item(**over):
    return {'id': 'dash-device-down:d1', 'category': 'device', 'severity': 'error', 'message': 'Pixel is down',
            'to': '/device-control', 'scope': {'device_id': 'd1'}, 'ts': 1700000000000, 'read': False, **over}


def test_list_is_scoped_to_team_and_caller_and_renames_to(calls):
    response, status = _call(routes.list_notifications, 'GET', query_string={'team_id': TEAM})
    assert status == 200 and calls == [('list', TEAM, 'u-1')]
    assert response.get_json()['rows'][0]['to'] == '/x' and 'to_path' not in response.get_json()['rows'][0]


def test_upsert_keeps_valid_items_only(calls):
    items = [_item(), _item(id=''), _item(severity='fatal'), _item(ts='x'), _item(id='b', category='nope')]
    response, status = _call(routes.upsert_notifications, 'POST', json={'team_id': TEAM, 'items': items})
    assert status == 200 and response.get_json()['saved'] == 2
    _, t, u, rows = calls[-1]
    assert (t, u) == (TEAM, 'u-1')
    assert rows[0]['to_path'] == '/device-control' and rows[0]['scope'] == {'device_id': 'd1'}
    assert rows[1]['category'] == 'action'


def test_upsert_passes_resolved_at_through(calls):
    """TASK-100: the resolve timestamp must reach the DB row, untouched."""
    items = [_item(id='dash-monitoring:pi1', resolved_at=1700000000000)]
    _, status = _call(routes.upsert_notifications, 'POST', json={'team_id': TEAM, 'items': items})
    assert status == 200
    _, _, _, rows = calls[-1]
    assert rows[0]['resolved_at'] == 1700000000000


def test_upsert_drops_non_int_resolved_at(calls):
    """TASK-100: a string or null passed as resolved_at must not crash the route — they become NULL."""
    items = [_item(id='a', resolved_at='soon'), _item(id='b', resolved_at=None)]
    _, status = _call(routes.upsert_notifications, 'POST', json={'team_id': TEAM, 'items': items})
    assert status == 200
    _, _, _, rows = calls[-1]
    assert rows[0]['resolved_at'] is None and rows[1]['resolved_at'] is None


def test_batch_is_capped(calls):
    _, status = _call(routes.upsert_notifications, 'POST', json={'team_id': TEAM, 'items': [_item()] * 201})
    assert status == 400


def test_read_and_dismiss_use_the_principal(calls):
    _call(routes.mark_read, 'PATCH', json={'team_id': TEAM, 'id': 'a', 'user_id': 'someone-else'})
    _call(routes.dismiss, 'DELETE', json={'team_id': TEAM})
    assert calls == [('read', TEAM, 'u-1', 'a'), ('dismiss', TEAM, 'u-1', None)]


def test_no_user_no_history(calls):
    _, status = _call(routes.list_notifications, 'GET', user_id='', query_string={'team_id': TEAM})
    assert status == 403
    _, status = _call(routes.list_notifications, 'GET')
    assert status == 400


@pytest.mark.parametrize('method', ['POST', 'PATCH', 'DELETE'])
def test_viewer_write_floor(method):
    with Flask('t').test_request_context('/server/notifications', method=method):
        request.user_role = 'viewer'
        assert auth_middleware.enforce_viewer_read_only() is None


class _Query:
    def __init__(self, log, data):
        self.log, self.data = log, data

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.log.append((name,) + args)
            return self
        return record

    def execute(self):
        data = self.data
        return type('R', (), {'data': data})()


def test_db_module_filters_by_team_and_user_and_trims(monkeypatch):
    log = []
    monkeypatch.setattr(notifications_db, 'get_supabase',
                        lambda: type('S', (), {'table': lambda self, n: _Query(log, [{'id': 'old'}])})())
    notifications_db.list_notifications(TEAM, 'u-1')
    notifications_db.upsert_notifications(TEAM, 'u-1', [{'id': 'a'}])
    notifications_db.mark_read(TEAM, 'u-1', 'a')
    notifications_db.dismiss(TEAM, 'u-1')
    eqs = [e[1:] for e in log if e[0] == 'eq']
    assert eqs.count(('team_id', TEAM)) == eqs.count(('user_id', 'u-1')) == 5  # list, trim select, trim delete, read, dismiss
    assert ('in_', 'id', ['old']) in log
