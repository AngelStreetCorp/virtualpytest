"""TASK-107 goal 2: "Wrong screen?" corrections survive a recapture and reach variants.

A recaptured screenshot brings a fresh fingerprint without `extra` / `negatives`; save_node
rebuilds them from the node's active localize_verdicts rows. A variant that overrides the
fingerprint still sees the base row's samples. Fakes only (no DB).
"""
import importlib

import pytest

lvdb = importlib.import_module('shared.src.lib.database.localize_verdicts_db')
ntdb = importlib.import_module('shared.src.lib.database.navigation_trees_db')
ng = importlib.import_module('shared.src.lib.utils.navigation_graph')

pytestmark = pytest.mark.unit

LIVE_A = {'v': 6, 'dhash': 'aa', 'regions': {'top': 'a1'}}
LIVE_B = {'v': 6, 'dhash': 'bb', 'regions': {'top': 'b1'}}
VERDICTS = [
    {'id': 'v1', 'action': 'add_sample', 'true_node_id': 'home', 'wrong_node_id': 'guide',
     'live_fingerprint': LIVE_A, 'created_at': '2026-10-14T10:00:00Z', 'undone_at': None},
    {'id': 'v2', 'action': 'negative', 'true_node_id': None, 'wrong_node_id': 'home',
     'live_fingerprint': LIVE_B, 'created_at': '2026-10-14T11:00:00Z', 'undone_at': None},
    {'id': 'v3', 'action': 'add_sample', 'true_node_id': 'guide', 'wrong_node_id': None,
     'live_fingerprint': LIVE_B, 'created_at': '2026-10-14T12:00:00Z', 'undone_at': None},
]


class _Q:
    """The chain carry_corrections / save_node build, answering from canned rows."""

    def __init__(self, store, table):
        self.store, self.table, self.filters = store, table, {}

    def __getattr__(self, name):
        def chain(*a, **k):
            if name in ('eq', 'contains', 'is_'):
                self.filters[(name, a[0])] = a[1]
            if name in ('update', 'insert', 'upsert'):
                self.store.setdefault('writes', []).append((self.table, name, a[0]))
            return self
        return chain

    def execute(self):
        class R:
            pass
        r = R()
        if self.table == 'localize_verdicts':
            tree = self.filters.get(('contains', 'tree_ids'), [None])[0]
            r.data = [v for v in self.store['verdicts'] if tree in v.get('tree_ids', ['T1'])]
        elif self.table == 'navigation_nodes':
            r.data = self.store.get('existing', [])
            if self.store.get('writes') and self.store['writes'][-1][0] == 'navigation_nodes':
                r.data = [self.store['writes'][-1][2]] if isinstance(self.store['writes'][-1][2], dict) \
                    else self.store['writes'][-1][2]
        else:
            r.data = []
        return r


class _DB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Q(self.store, name)


@pytest.fixture
def db(monkeypatch):
    store = {'verdicts': [dict(v) for v in VERDICTS], 'existing': [{'id': 'row1'}]}
    fake = _DB(store)
    monkeypatch.setattr(lvdb, 'get_supabase_client', lambda: fake)
    monkeypatch.setattr(ntdb, 'get_supabase', lambda: fake)
    return store


def _fresh_fp():
    return {'v': 6, 'dhash': 'ff', 'regions': {'top': 'f1'}, 'focus': {'kind': 'none'}}


def test_rebuild_is_idempotent_and_drops_undone():
    fp = lvdb.rebuild_corrections(_fresh_fp(), [v for v in VERDICTS if v['true_node_id'] == 'home'])
    assert [s['verdict_id'] for s in fp['extra']] == ['v1']
    assert lvdb.rebuild_corrections(fp, [VERDICTS[0]]) == fp
    undone = {**VERDICTS[0], 'undone_at': '2026-10-15T00:00:00Z'}
    assert 'extra' not in lvdb.rebuild_corrections(fp, [undone])


def test_a_recapture_keeps_the_samples_and_negatives(db):
    """The test the task names: save_node with a recaptured fingerprint keeps both corrections."""
    node = {'node_id': 'home', 'label': 'home', 'data': {'fingerprint': _fresh_fp(), 'screenshot': 'new.jpg'}}
    out = ntdb.save_node('T1', node, 'team')
    assert out['success'] is True
    saved = [w for w in db['writes'] if w[0] == 'navigation_nodes'][-1][2]['data']['fingerprint']
    assert saved['dhash'] == 'ff'                                      # the new capture wins
    assert [s['verdict_id'] for s in saved['extra']] == ['v1']         # the sample survives
    assert [s['verdict_id'] for s in saved['negatives']] == ['v2']     # the negative survives
    assert saved['extra'][0]['regions'] == LIVE_A['regions']


def test_batch_save_carries_per_node(db):
    nodes = [{'node_id': 'home', 'data': {'fingerprint': _fresh_fp()}},
             {'node_id': 'guide', 'data': {'fingerprint': _fresh_fp()}},
             {'node_id': 'other', 'data': {'fingerprint': _fresh_fp()}},
             {'node_id': 'nofp', 'data': {}}]
    assert lvdb.carry_corrections('team', 'T1', nodes) == 2
    assert [s['verdict_id'] for s in nodes[1]['data']['fingerprint']['extra']] == ['v3']
    assert 'extra' not in nodes[2]['data']['fingerprint'] and nodes[3]['data'] == {}


def test_a_stale_copy_of_an_undone_sample_is_dropped(db):
    db['verdicts'] = []                                                # v1 was undone
    stale = {**_fresh_fp(), 'extra': [{'verdict_id': 'v1', 'regions': {'top': 'a1'}}]}
    nodes = [{'node_id': 'home', 'data': {'fingerprint': stale}}]
    assert lvdb.carry_corrections('team', 'T1', nodes) == 1
    assert 'extra' not in nodes[0]['data']['fingerprint']


def test_a_save_never_fails_on_a_db_without_the_table(monkeypatch, db):
    def boom():
        raise RuntimeError('relation "localize_verdicts" does not exist')
    monkeypatch.setattr(lvdb, 'get_supabase_client', boom)
    out = ntdb.save_node('T1', {'node_id': 'home', 'data': {'fingerprint': _fresh_fp()}}, 'team')
    assert out['success'] is True


def test_a_variant_fingerprint_sees_the_base_corrections():
    base_fp = lvdb.rebuild_corrections(_fresh_fp(), VERDICTS[:2])
    node = {'node_id': 'home', 'data': {'fingerprint': base_fp}}
    variant_fp = {'v': 6, 'dhash': 'de', 'regions': {'top': 'd1'}}
    out = ng.resolve_node_variant(node, {'home': {'fingerprint': variant_fp}})
    assert out['__fingerprint']['dhash'] == 'de'
    assert [s['verdict_id'] for s in out['__fingerprint']['extra']] == ['v1']
    assert [s['verdict_id'] for s in out['__fingerprint']['negatives']] == ['v2']
    assert out['data']['fingerprint'] == out['__fingerprint']
    # no duplicate when the variant already carries the same sample
    again = ng.with_base_corrections(out['__fingerprint'], base_fp)
    assert len(again['extra']) == 1
