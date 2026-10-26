"""Unit tests for the BUG-0569 dashboard aggregations.

Pure-Python functions exercised with hand-rolled match_runs rows and a
stubbed supabase client.  These cover `summary`, `per_device`,
`verdict_distribution` and `sequence` — the four read functions that
power the new MatchRuns page panels.
"""
import os
import sys
import types
from unittest.mock import MagicMock

# Repo root is two levels up from this test file.
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))

from shared.src.lib.database import match_runs_db  # noqa: E402


# ── summary ───────────────────────────────────────────────────────────────────


def test_summary_zero_count_on_empty_team(monkeypatch):
    """Empty match_runs → zero on every counter, distinct_x = 0."""
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.gte.return_value \
        .execute.return_value = types.SimpleNamespace(data=[])
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: fake_db)
    out = match_runs_db.summary('team_x', since_iso='2026-10-16T00:00:00Z')
    assert out['total'] == 0
    assert out['matched'] == 0
    assert out['uncertain'] == 0
    assert out['unknown_or_low_conf'] == 0
    assert out['distinct_devices'] == 0
    assert out['distinct_profiles'] == 0
    assert out['distinct_hosts'] == 0
    assert out['window_started_at'] == '2026-10-16T00:00:00Z'


def test_summary_counts_verdict_buckets_and_distincts(monkeypatch):
    """Three runs, two known_node (one tight), one unknown; one device + profile."""
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.gte.return_value \
        .execute.return_value = types.SimpleNamespace(data=[
            {'verdict': 'known_node', 'runner_up_margin': 0.02, 'device_name': 'stb1',
             'host_name': 'host-A', 'profile': 'tv_app'},
            {'verdict': 'known_node', 'runner_up_margin': 0.40, 'device_name': 'stb1',
             'host_name': 'host-A', 'profile': 'tv_app'},
            {'verdict': 'unknown', 'runner_up_margin': None, 'device_name': 'stb1',
             'host_name': 'host-A', 'profile': 'tv_app'},
        ])
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: fake_db)
    out = match_runs_db.summary('team_x', since_iso='2026-10-16T00:00:00Z')
    assert out['total'] == 3
    assert out['matched'] == 2
    assert out['uncertain'] == 1    # the 0.02-margin row
    assert out['unknown_or_low_conf'] == 1
    assert out['distinct_devices'] == 1
    assert out['distinct_profiles'] == 1
    assert out['distinct_hosts'] == 1


# ── per_device ────────────────────────────────────────────────────────────────


def test_per_device_groups_by_host_and_device(monkeypatch):
    """Two devices, one with matches, one with unknowns; sorted by total desc."""
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.gte.return_value \
        .execute.return_value = types.SimpleNamespace(data=[
            {'host_name': 'hA', 'device_name': 'd1', 'verdict': 'known_node',
             'runner_up_margin': 0.10, 'started_at': '2026-10-16T10:00:00Z'},
            {'host_name': 'hA', 'device_name': 'd1', 'verdict': 'known_node',
             'runner_up_margin': 0.20, 'started_at': '2026-10-16T10:05:00Z'},
            {'host_name': 'hA', 'device_name': 'd2', 'verdict': 'unknown',
             'runner_up_margin': None,  'started_at': '2026-10-16T10:10:00Z'},
        ])
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: fake_db)
    out = match_runs_db.per_device('team_x', since_iso='2026-10-16T00:00:00Z')
    assert len(out) == 2
    # Sorted by total desc → d1 (2) ahead of d2 (1).
    assert out[0]['device_name'] == 'd1'
    assert out[0]['total'] == 2
    assert out[0]['matched'] == 2
    assert out[0]['uncertain'] == 0
    assert out[0]['unknown'] == 0
    assert out[0]['last_match_at'] == '2026-10-16T10:05:00Z'
    assert out[1]['device_name'] == 'd2'
    assert out[1]['matched'] == 0
    assert out[1]['unknown'] == 1


def test_per_device_uncertain_threshold_is_five_percent(monkeypatch):
    """A 6% margin does NOT count as uncertain — only < 5% does."""
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.gte.return_value \
        .execute.return_value = types.SimpleNamespace(data=[
        {'host_name': 'hA', 'device_name': 'd1', 'verdict': 'known_node',
         'runner_up_margin': 0.06, 'started_at': '2026-10-16T10:00:00Z'},
    ])
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: fake_db)
    out = match_runs_db.per_device('team_x', since_iso='2026-10-16T00:00:00Z')
    assert out[0]['uncertain'] == 0
    assert out[0]['matched'] == 1


# ── verdict_distribution ─────────────────────────────────────────────────────


def test_verdict_distribution_buckets_per_hour(monkeypatch):
    """Two hours, two verdicts each → 4 rows out, sorted by bucket."""
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.gte.return_value \
        .execute.return_value = types.SimpleNamespace(data=[
        {'verdict': 'known_node', 'started_at': '2026-10-16T10:15:00Z'},
        {'verdict': 'unknown',     'started_at': '2026-10-16T10:30:00Z'},
        {'verdict': 'known_node', 'started_at': '2026-10-16T11:05:00Z'},
        {'verdict': 'low_confidence', 'started_at': '2026-10-16T11:45:00Z'},
    ])
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: fake_db)
    out = match_runs_db.verdict_distribution('team_x', since_iso='2026-10-16T00:00:00Z')
    assert len(out) == 4
    # Bucket keys are the hour-aligned ISO timestamps.
    buckets = sorted({r['bucket'] for r in out})
    assert buckets == ['2026-10-16T10:00:00', '2026-10-16T11:00:00']
    by_bucket_verdict = {(r['bucket'], r['verdict']): r['count'] for r in out}
    assert by_bucket_verdict[('2026-10-16T10:00:00', 'known_node')] == 1
    assert by_bucket_verdict[('2026-10-16T10:00:00', 'unknown')] == 1
    assert by_bucket_verdict[('2026-10-16T11:00:00', 'known_node')] == 1
    assert by_bucket_verdict[('2026-10-16T11:00:00', 'low_confidence')] == 1


# ── sequence ──────────────────────────────────────────────────────────────────


def test_sequence_returns_chain_for_device_and_ui(monkeypatch):
    """sequence() returns the rows fetched via the chained .eq()×3.order().limit().execute()."""
    rows_in = [
        {'id': 'a', 'verdict': 'known_node', 'started_at': '2026-10-16T10:00:00Z',
         'candidates_top_3': [{'node_id': 'home', 'label': 'home', 'score': 0.95, 'rank': 1}]},
        {'id': 'b', 'verdict': 'unknown', 'started_at': '2026-10-16T10:01:00Z',
         'candidates_top_3': []},
    ]
    fake_db = MagicMock()
    # Without session_id the chain is table().select().eq().eq().eq().order().limit().execute()
    chain = (fake_db.table.return_value.select.return_value
             .eq.return_value.eq.return_value.eq.return_value
             .order.return_value.limit.return_value)
    chain.execute.return_value = types.SimpleNamespace(data=rows_in)
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: fake_db)
    rows = match_runs_db.sequence(
        'team_x', device_id='d1', userinterface_name='stb_tv', limit=5)
    assert len(rows) == 2
    assert rows[0]['id'] == 'a'
    assert rows[1]['verdict'] == 'unknown'
    # candidates_top_3 carries through unchanged — the operator gets the breakdown.
    assert rows[0]['candidates_top_3'][0]['rank'] == 1


def test_sequence_returns_empty_on_db_error(monkeypatch):
    """A supabase error → empty list (the route returns success=True, rows=[])."""
    fake_db = MagicMock()
    chain = (fake_db.table.return_value.select.return_value
             .eq.return_value.eq.return_value.eq.return_value
             .order.return_value.limit.return_value)
    chain.execute.side_effect = Exception('boom')
    monkeypatch.setattr(match_runs_db, 'get_supabase_client', lambda: fake_db)
    rows = match_runs_db.sequence('team_x', device_id='d1', userinterface_name='stb_tv')
    assert rows == []


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
