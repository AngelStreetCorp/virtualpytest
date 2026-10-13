"""POST /server/navigationTrees/<tree_id>/refresh — make a tree write visible to hosts now.

Hosts read mv_full_navigation_trees, which the live databases refresh once a minute
(pg_cron), so every tree write needed a ~90 s wait before navigation saw it. The route
refreshes the view, reads the tree's row back, clears server caches and clears the tree
on every host synchronously, and reports each step.

Unit-level: the blueprint runs in a bare Flask app; the database and hosts are mocks.
"""
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

flask = pytest.importorskip('flask')
try:
    routes = importlib.import_module('backend_server.src.routes.server_navigation_trees_routes')
    nav_db = importlib.import_module('shared.src.lib.database.navigation_trees_db')
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"server runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit

TEAM = 'team-1'
TREE = 'tree-1'


class FakeHostManager:
    def __init__(self, hosts):
        self.hosts = hosts

    def get_all_hosts(self):
        return {h['host_name']: h for h in self.hosts}


@pytest.fixture
def client(monkeypatch):
    calls = []
    monkeypatch.setattr(routes, 'refresh_navigation_mv',
                        lambda: calls.append('refresh') or {'success': True, 'refreshed_at': 'T1'})
    monkeypatch.setattr(routes, 'get_mv_tree_summary',
                        lambda tree_id, team_id: calls.append(('summary', tree_id, team_id)) or {
                            'success': True, 'mv_present': True, 'node_count': 7,
                            'edge_count': 9, 'last_refreshed': '2026-10-03T10:00:00+00:00'})
    monkeypatch.setattr(routes, '_clear_server_tree_caches',
                        lambda tree_id, team_id: calls.append(('server_cache', tree_id, team_id)))

    hosts = [{'host_name': 'host-clone-1'}, {'host_name': 'host-clone-2'}, {'host_name': 'vpt-pi1'}]
    import backend_server.src.lib.utils.server_utils as server_utils
    import backend_server.src.lib.utils.route_utils as route_utils
    monkeypatch.setattr(server_utils, 'get_host_manager', lambda: FakeHostManager(hosts))

    def fake_proxy(host_info, endpoint, method='GET', **_):
        calls.append(('host', host_info['host_name'], endpoint, method))
        if host_info['host_name'] == 'host-clone-2':
            return {'success': False, 'error': 'no graph cached'}, 200
        if host_info['host_name'] == 'vpt-pi1':
            raise ConnectionError('host unreachable')
        return {'success': True}, 200

    monkeypatch.setattr(route_utils, 'proxy_to_host_direct', fake_proxy)

    app = flask.Flask('t')
    app.register_blueprint(routes.server_navigation_trees_bp)
    c = app.test_client()
    c.calls = calls
    return c


def test_refresh_reports_view_row_and_every_host(client):
    resp = client.post(f'/server/navigationTrees/{TREE}/refresh?team_id={TEAM}')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {
        'success': True,
        'tree_id': TREE,
        'mv_present': True,
        'node_count': 7,
        'edge_count': 9,
        'last_refreshed': '2026-10-03T10:00:00+00:00',
        'hosts': [
            {'host': 'host-clone-1', 'success': True, 'error': None},
            {'host': 'host-clone-2', 'success': False, 'error': 'no graph cached'},
            {'host': 'vpt-pi1', 'success': False, 'error': 'host unreachable'},
        ],
    }
    # Order matters: refresh before reading back, server caches before hosts rebuild.
    kinds = [c if isinstance(c, str) else c[0] for c in client.calls]
    assert kinds == ['refresh', 'summary', 'server_cache', 'host', 'host', 'host']
    host_call = client.calls[3]
    assert host_call[2] == f'/host/navigation/cache/clear/{TREE}?team_id={TEAM}'
    assert host_call[3] == 'POST'


def test_refresh_requires_team_id(client):
    resp = client.post(f'/server/navigationTrees/{TREE}/refresh')
    assert resp.status_code == 400
    assert client.calls == []


def test_refresh_failure_stops_before_hosts(client, monkeypatch):
    monkeypatch.setattr(routes, 'refresh_navigation_mv',
                        lambda: {'success': False, 'error': 'function refresh_navigation_trees_mv() does not exist'})
    resp = client.post(f'/server/navigationTrees/{TREE}/refresh?team_id={TEAM}')
    assert resp.status_code == 500
    body = resp.get_json()
    assert body['success'] is False
    assert '20261003a_refresh_navigation_trees_mv' in body['error']
    assert not any(isinstance(c, tuple) and c[0] == 'host' for c in client.calls)


def test_tree_missing_from_view_is_reported_not_hidden(client, monkeypatch):
    monkeypatch.setattr(routes, 'get_mv_tree_summary', lambda tree_id, team_id: {
        'success': True, 'mv_present': False, 'node_count': 0, 'edge_count': 0, 'last_refreshed': None})
    body = client.post(f'/server/navigationTrees/{TREE}/refresh?team_id={TEAM}').get_json()
    assert body['success'] is True
    assert body['mv_present'] is False
    assert body['node_count'] == 0


# ---- DB layer -------------------------------------------------------------------

class FakeQuery:
    def __init__(self, data, log):
        self.data, self.log = data, log

    def __getattr__(self, name):
        def chain(*args, **kwargs):
            self.log.append((name, args))
            return self
        return chain

    def execute(self):
        return type('R', (), {'data': self.data})()


class FakeSupabase:
    def __init__(self, rows=None, rpc_data=None, rpc_error=None):
        self.rows, self.rpc_data, self.rpc_error = rows or [], rpc_data, rpc_error
        self.log = []

    def rpc(self, name, params):
        self.log.append(('rpc', name, params))
        if self.rpc_error:
            raise self.rpc_error
        return FakeQuery(self.rpc_data, self.log)

    def table(self, name):
        self.log.append(('table', name))
        return FakeQuery(self.rows, self.log)


def test_refresh_navigation_mv_calls_the_function(monkeypatch):
    sb = FakeSupabase(rpc_data='2026-10-03T10:00:01+00:00')
    monkeypatch.setattr(nav_db, 'get_supabase', lambda: sb)
    assert nav_db.refresh_navigation_mv() == {'success': True, 'refreshed_at': '2026-10-03T10:00:01+00:00'}
    assert sb.log[0] == ('rpc', 'refresh_navigation_trees_mv', {})


def test_refresh_navigation_mv_reports_errors(monkeypatch):
    monkeypatch.setattr(nav_db, 'get_supabase', lambda: FakeSupabase(rpc_error=RuntimeError('boom')))
    assert nav_db.refresh_navigation_mv() == {'success': False, 'error': 'boom'}


def test_mv_tree_summary_counts_nodes_and_edges(monkeypatch):
    row = {'tree_id': TREE, 'last_refreshed': 'T',
           'full_tree_data': {'nodes': [{}, {}, {}], 'edges': [{}]}}
    sb = FakeSupabase(rows=[row])
    monkeypatch.setattr(nav_db, 'get_supabase', lambda: sb)
    assert nav_db.get_mv_tree_summary(TREE, TEAM) == {
        'success': True, 'mv_present': True, 'node_count': 3, 'edge_count': 1, 'last_refreshed': 'T'}
    assert ('table', 'mv_full_navigation_trees') in sb.log
    assert ('eq', ('team_id', TEAM)) in sb.log


def test_mv_tree_summary_without_row(monkeypatch):
    monkeypatch.setattr(nav_db, 'get_supabase', lambda: FakeSupabase(rows=[]))
    assert nav_db.get_mv_tree_summary(TREE, TEAM)['mv_present'] is False
