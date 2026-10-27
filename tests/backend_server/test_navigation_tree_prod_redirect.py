"""The blueprint's prod-write guard (TASK-173) — a write aimed at a prod tree lands on dev.

Prod trees are only written by Publish, so a per-node / per-edge / subtree write
aimed at a prod tree is re-aimed at the dev tree it was published from. That
guard is a blueprint `before_request`, so it runs in front of EVERY write on this
blueprint — including in a process that has no database at all.

The guard has no route of its own to fail on, which is why it was untested until
it broke every tree write in a database-less process: the resolver dereferenced
a None Supabase client and the request died on an empty 500 before the route
ever ran. These tests pin the three behaviours the guard owes its callers.

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
    publish = importlib.import_module('shared.src.lib.database.userinterface_publish')
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"server runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit

TEAM = 'team-1'
TREE = 'tree-1'
DEV_TREE = 'dev-tree-1'


@pytest.fixture
def client(monkeypatch):
    """A bare Flask app with the blueprint; the route's own DB and host calls are mocks."""
    seen = {}
    monkeypatch.setattr(routes, 'refresh_navigation_mv',
                        lambda: {'success': True, 'refreshed_at': 'T1'})
    monkeypatch.setattr(routes, 'get_mv_tree_summary',
                        lambda tree_id, team_id: {'success': True, 'mv_present': True,
                                                  'node_count': 0, 'edge_count': 0,
                                                  'last_refreshed': None})
    monkeypatch.setattr(routes, '_clear_server_tree_caches', lambda tree_id, team_id: None)

    def fake_clear_hosts(tree_id, team_id):
        seen['tree_id'] = tree_id
        return []

    monkeypatch.setattr(routes, 'clear_tree_cache_on_hosts', fake_clear_hosts)

    app = flask.Flask('t')
    app.register_blueprint(routes.server_navigation_trees_bp)
    client = app.test_client()
    client.seen = seen
    return client


def test_a_write_without_a_database_still_reaches_the_route(client, monkeypatch):
    """No Supabase client (BUG-0109): there is no prod tree to redirect to.

    The resolver used to dereference the missing client, so every tree write in
    a database-less process died on an empty 500 before the route ran. The write
    itself cannot be persisted without a database either, so the honest answer
    is "not a prod tree" — and the route answers for itself.
    """
    monkeypatch.setattr(publish, 'get_supabase', lambda: None)

    resp = client.post(f'/server/navigationTrees/{TREE}/refresh?team_id={TEAM}')

    assert resp.status_code == 200
    assert resp.get_json()['success'] is True


def test_a_failing_lookup_refuses_the_write_with_a_readable_body(client, monkeypatch):
    """The lookup itself fails: the write is refused, and the caller can read why.

    The guard exists so that an edit never lands on a prod tree. When the lookup
    fails we cannot prove the tree is not a prod tree, so the write must not go
    through — with a JSON body, not a bare 500 the caller cannot parse.
    """
    def boom(tree_id, team_id):
        raise RuntimeError('database is down')

    monkeypatch.setattr(publish, 'resolve_dev_tree_for_prod', boom)

    resp = client.post(f'/server/navigationTrees/{TREE}/refresh?team_id={TEAM}')

    assert resp.status_code == 503
    body = resp.get_json()
    assert body['success'] is False
    assert 'database is down' in body['error']
    # The route never ran: a refused write touches no tree.
    assert 'tree_id' not in client.seen


def test_a_prod_tree_write_is_re_aimed_at_the_dev_tree(client, monkeypatch):
    """The guard still does its job when it can answer."""
    monkeypatch.setattr(publish, 'resolve_dev_tree_for_prod', lambda tree_id, team_id: {
        'dev_tree_id': DEV_TREE,
        'dev_userinterface_id': 'dev-ui',
        'prod_userinterface_id': 'prod-ui',
    })

    resp = client.post(f'/server/navigationTrees/{TREE}/refresh?team_id={TEAM}')

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    # The route was handed the dev tree, not the prod one it was aimed at.
    assert client.seen['tree_id'] == DEV_TREE
    assert body['redirected_to_dev'] is True
