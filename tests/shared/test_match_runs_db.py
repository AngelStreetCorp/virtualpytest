"""Unit tests for the match_runs helpers (TASK-115).

The DB-touching functions are exercised against a mock supabase client;
the pure helpers (top-N extraction, floor, runner-up margin) are tested
with hand-rolled dicts.
"""
import os
import sys
import types
from unittest.mock import MagicMock

# Repo root is the parent of the tests/ directory; tests/shared/conftest.py
# already inserts it but this file may be run directly (python3 -m pytest
# tests/shared/test_match_runs_db.py from the repo root) without the
# conftest applying.  Insert the parent of this file's parent.
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))

from shared.src.lib.database import match_runs_db  # noqa: E402


def _result(candidates=None, ranked=None, kind=None):
    r = {}
    if candidates is not None:
        r['candidates'] = candidates
    if ranked is not None:
        r['ranked'] = ranked
    if kind is not None:
        r['kind'] = kind
    return r


def test_top_n_picks_candidates_over_ranked():
    # Candidates are post-narrowing; ranked is pre-narrowing.  We want
    # the post-narrowing list because the runner-up is a real second
    # opinion, not something the matcher already decided to drop.
    res = _result(
        candidates=[
            {'node_id': 'A', 'label': 'A', 'confidence': 0.95},
            {'node_id': 'B', 'label': 'B', 'confidence': 0.85},
        ],
        ranked=[{'node_id': 'X', 'label': 'X', 'confidence': 0.50}],
    )
    top3 = match_runs_db._top_n(res, n=3)
    assert top3[0]['node_id'] == 'A'
    assert top3[1]['node_id'] == 'B'
    assert len(top3) == 2


def test_top_n_caps_at_n():
    res = _result(candidates=[
        {'node_id': f'n{i}', 'label': f'n{i}', 'confidence': 0.9 - i * 0.05}
        for i in range(10)
    ])
    top3 = match_runs_db._top_n(res, n=3)
    assert len(top3) == 3
    assert [c['node_id'] for c in top3] == ['n0', 'n1', 'n2']


def test_top_n_falls_back_to_ranked_when_candidates_empty():
    res = _result(candidates=[], ranked=[
        {'node_id': 'A', 'label': 'A', 'confidence': 0.7},
        {'node_id': 'B', 'label': 'B', 'confidence': 0.65},
    ])
    top3 = match_runs_db._top_n(res, n=3)
    assert [c['node_id'] for c in top3] == ['A', 'B']


def test_top_n_handles_empty_input():
    assert match_runs_db._top_n({}) == []
    assert match_runs_db._top_n(_result(candidates=[])) == []


def test_floor_hit_true_above_threshold():
    top3 = [{'score': 0.85}, {'score': 0.80}, {'score': 0.50}]
    assert match_runs_db._floor_hit(top3, 0.80) is True


def test_floor_hit_false_below_threshold():
    top3 = [{'score': 0.79}, {'score': 0.40}]
    assert match_runs_db._floor_hit(top3, 0.80) is False


def test_floor_hit_false_on_empty():
    assert match_runs_db._floor_hit([], 0.80) is False


def test_runner_up_margin_computes_difference():
    top3 = [{'score': 0.95}, {'score': 0.85}, {'score': 0.50}]
    assert match_runs_db._runner_up_margin(top3) == 0.10


def test_runner_up_margin_none_with_single_candidate():
    top3 = [{'score': 0.95}]
    assert match_runs_db._runner_up_margin(top3) is None


def test_runner_up_margin_none_on_empty():
    assert match_runs_db._runner_up_margin([]) is None


def test_record_match_run_short_circuits_on_missing_args():
    out = match_runs_db.record_match_run(
        team_id='', host_name='h', userinterface_name='ui', source='verify',
        result={}
    )
    assert out['success'] is False
    assert 'required' in out['error']


def test_record_match_run_known_node_when_winner_clears_floor(monkeypatch):
    """End-to-end of the floor logic on a representative matcher result."""
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .eq.return_value.order.return_value.limit.return_value.execute.return_value \
        = types.SimpleNamespace(data=[])  # no prior event
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: fake_db)
    out = match_runs_db.record_match_run(
        team_id='t1', host_name='h1', userinterface_name='stb_tv', source='localize_button',
        result=_result(candidates=[
            {'node_id': 'home', 'label': 'home', 'confidence': 0.92},
            {'node_id': 'movies', 'label': 'movies', 'confidence': 0.88},
            {'node_id': 'replay', 'label': 'replay', 'confidence': 0.50},
        ]),
        device_id='d1', confidence_floor=0.80,
    )
    assert out['success'] is True
    assert out['verdict'] == 'known_node'
    assert out['floor_hit'] is True
    # The row payload should carry the top-3 with score, label, rank.
    insert_call = fake_db.table.return_value.insert.call_args
    payload = insert_call.args[0]
    assert payload['matched_node_id'] == 'home'
    assert payload['candidate_floor_hit'] is True
    assert payload['candidates_top_3'][0]['rank'] == 1
    assert payload['candidates_top_3'][2]['rank'] == 3
    assert payload['runner_up_margin'] == 0.04  # 0.92 - 0.88


def test_record_match_run_low_confidence_when_winner_below_floor(monkeypatch):
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .eq.return_value.order.return_value.limit.return_value.execute.return_value \
        = types.SimpleNamespace(data=[])
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: fake_db)
    out = match_runs_db.record_match_run(
        team_id='t1', host_name='h1', userinterface_name='stb_tv', source='localize_button',
        result=_result(candidates=[
            {'node_id': 'home', 'label': 'home', 'confidence': 0.65},
            {'node_id': 'movies', 'label': 'movies', 'confidence': 0.60},
        ]),
        device_id='d1', confidence_floor=0.80,
    )
    assert out['verdict'] == 'low_confidence'
    assert out['floor_hit'] is False
    # No winner is recorded for a low_confidence verdict — matched_node_id NULL.
    payload = fake_db.table.return_value.insert.call_args.args[0]
    assert payload['matched_node_id'] is None
    # But the top-3 IS still in the payload (the operator wants to see the breakdown).
    assert len(payload['candidates_top_3']) == 2


def test_record_match_run_unknown_when_candidates_empty(monkeypatch):
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .eq.return_value.order.return_value.limit.return_value.execute.return_value \
        = types.SimpleNamespace(data=[])
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: fake_db)
    out = match_runs_db.record_match_run(
        team_id='t1', host_name='h1', userinterface_name='stb_tv', source='localize_button',
        result=_result(candidates=[], ranked=[]),
        device_id='d1', confidence_floor=0.80,
    )
    assert out['verdict'] == 'unknown'


def test_summary_until_closes_the_window(monkeypatch):
    """until_iso adds a `started_at < until` filter, so summary() can describe the previous window."""
    q = MagicMock()
    for m in ('select', 'eq', 'gte', 'lt'):
        getattr(q, m).return_value = q
    q.table.return_value = q
    q.execute.return_value = types.SimpleNamespace(data=[
        {'verdict': 'known_node', 'runner_up_margin': 0.2, 'matched_confidence': 0.9,
         'device_name': 'd1', 'host_name': 'h1', 'profile': None},
        {'verdict': 'unknown', 'runner_up_margin': None, 'matched_confidence': None,
         'device_name': 'd1', 'host_name': 'h1', 'profile': None},
    ])
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: q)
    out = match_runs_db.summary('t1', since_iso='2026-10-18T00:00:00+00:00',
                                until_iso='2026-10-19T00:00:00+00:00')
    q.gte.assert_called_once_with('started_at', '2026-10-18T00:00:00+00:00')
    q.lt.assert_called_once_with('started_at', '2026-10-19T00:00:00+00:00')
    assert out['total'] == 2 and out['matched'] == 1 and out['unknown_or_low_conf'] == 1


def test_summary_without_until_has_no_upper_bound(monkeypatch):
    q = MagicMock()
    for m in ('select', 'eq', 'gte', 'lt'):
        getattr(q, m).return_value = q
    q.table.return_value = q
    q.execute.return_value = types.SimpleNamespace(data=[])
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: q)
    match_runs_db.summary('t1', since_iso='2026-10-18T00:00:00+00:00')
    q.lt.assert_not_called()


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))


def _fake_db_no_prior():
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .eq.return_value.order.return_value.limit.return_value.execute.return_value \
        = types.SimpleNamespace(data=[])
    return fake_db


def test_record_match_run_stores_live_fingerprint_with_regions(monkeypatch):
    fake_db = _fake_db_no_prior()
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: fake_db)
    fp = {'v': 6, 'dhash': 'ab', 'regions': {'tl': 'ff'}}
    res = _result(candidates=[{'node_id': 'home', 'label': 'home', 'confidence': 0.9}])
    res['live_fingerprint'] = fp
    match_runs_db.record_match_run(team_id='t1', host_name='h1', userinterface_name='stb_tv',
                                   source='localize_button', result=res, device_id='d1')
    assert fake_db.table.return_value.insert.call_args.args[0]['live_fingerprint'] == fp


def test_record_match_run_live_fingerprint_null_without_regions(monkeypatch):
    fake_db = _fake_db_no_prior()
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: fake_db)
    res = _result(candidates=[])
    res['live_fingerprint'] = {'v': 6, 'dhash': 'ab'}
    match_runs_db.record_match_run(team_id='t1', host_name='h1', userinterface_name='stb_tv',
                                   source='monitor_localize', result=res, device_id='d1')
    assert fake_db.table.return_value.insert.call_args.args[0]['live_fingerprint'] is None


def test_list_recent_flags_fingerprint_and_strips_it_by_default(monkeypatch):
    rows = [{'id': 1, 'live_fingerprint': {'regions': {}}}, {'id': 2, 'live_fingerprint': None}]
    fake_db = MagicMock()
    chain = fake_db.table.return_value.select.return_value.eq.return_value
    chain.order.return_value.limit.return_value.execute.return_value = types.SimpleNamespace(data=rows)
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: fake_db)
    out = match_runs_db.list_recent('t1')
    assert [r['has_fingerprint'] for r in out] == [True, False]
    assert all('live_fingerprint' not in r for r in out)
