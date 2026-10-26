"""BUG-0902: reading the campaign results must not close a campaign that is still running.

Run them with:

    timeout 300 python3 -m pytest tests/test_campaign_reconcile_staleness.py -q

Nothing here touches the network, a browser, a host, a device or a database: the
Supabase client is the repo's own in-memory mock. Placeholders only.

Negative control: on the pre-fix tree every case but the guards (test_abandoned_*,
test_executor_final_write_wins, test_finished_campaign_*) fails with an AssertionError, because the
reconcile closed any running row older than timeout + grace as a generic 'failed'
stamped with the reader's clock.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.src.lib.database import campaign_executions_db as campaign_db  # noqa: E402
from tests._supabase_mock import SupabaseMock  # noqa: E402

TEAM_ID = '11111111-1111-1111-1111-111111111111'
PLACEHOLDER_HOST = 'placeholder-host'
PERMITTED_STATUSES = {'pending', 'running', 'completed', 'failed', 'cancelled', 'aborted'}
MIN = timedelta(minutes=1)


class _Counting:
    """Wraps the mock and records which tables were queried."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def table(self, name):
        self.calls.append(name)
        return self.inner.table(name)


@pytest.fixture
def sb(monkeypatch):
    mock = SupabaseMock({'script_results': [], 'campaign_executions': []})
    counting = _Counting(mock)
    monkeypatch.setattr(campaign_db, 'get_supabase', lambda: counting)
    getattr(campaign_db, '_last_reconcile_by_team', {}).clear()
    mock.counting = counting
    return mock


def _iso(dt):
    return dt.isoformat()


def _seed(sb, *, started_ago, timeout_minutes=120, scripts=(), expected=None, cid='c1'):
    """A running campaign started `started_ago` ago.

    scripts: (started_ago, completed_ago or None, success) per linked script result.
    """
    now = datetime.now(timezone.utc)
    ids = []
    for i, (s_ago, c_ago, ok) in enumerate(scripts):
        sid = f'{cid}-s{i}'
        ids.append(sid)
        done = c_ago is not None
        sb.table('script_results').insert({
            'id': sid, 'team_id': TEAM_ID,
            'started_at': _iso(now - s_ago),
            'completed_at': _iso(now - c_ago) if done else None,
            'updated_at': _iso(now - (c_ago if done else s_ago)),
            'execution_time_ms': 1000 if done else None,
            'success': ok if done else False, 'skipped': False,
        }).execute()
    n = expected if expected is not None else len(ids)
    sb.table('campaign_executions').insert({
        'id': cid, 'team_id': TEAM_ID, 'campaign_name': 'placeholder_campaign',
        'host_name': PLACEHOLDER_HOST, 'status': 'running', 'success': False,
        'started_at': _iso(now - started_ago), 'created_at': _iso(now - started_ago),
        'updated_at': _iso(now - started_ago), 'completed_at': None,
        'error_message': None, 'execution_time_ms': None,
        'script_result_ids': ids,
        'script_configurations': [{'script_name': 'x.py'} for _ in range(n)],
        'execution_config': {'timeout_minutes': timeout_minutes},
    }).execute()
    return cid


def _row(sb, cid='c1'):
    return next(r for r in sb.get_table('campaign_executions') if r['id'] == cid)


def test_running_old_with_scripts_in_flight_is_not_written(sb):
    _seed(sb, started_ago=130 * MIN, scripts=[(5 * MIN, None, False)], expected=3)
    before = dict(_row(sb))
    assert campaign_db.reconcile_stale_campaign_executions(TEAM_ID) == 0
    assert _row(sb) == before


def test_nightly_170_minutes_with_live_scripts_is_not_closed(sb):
    _seed(sb, started_ago=170 * MIN, timeout_minutes=120,
          scripts=[(160 * MIN, 150 * MIN, True), (3 * MIN, None, False)], expected=5)
    before = dict(_row(sb))
    campaign_db.get_campaign_results(TEAM_ID)
    assert _row(sb) == before


def test_read_changes_no_field_of_a_running_row(sb):
    _seed(sb, started_ago=140 * MIN, scripts=[(1 * MIN, None, False)], expected=2)
    before = dict(_row(sb))
    campaign_db.get_campaign_results(TEAM_ID)
    after = _row(sb)
    for field in ('status', 'success', 'completed_at', 'error_message',
                  'execution_time_ms', 'updated_at'):
        assert after[field] == before[field], field


def test_worker_gone_closes_with_reason_and_real_time(sb):
    _seed(sb, started_ago=300 * MIN, scripts=[(200 * MIN, None, False)], expected=2)
    last = datetime.now(timezone.utc) - 200 * MIN
    before_call = datetime.now(timezone.utc)
    assert campaign_db.reconcile_stale_campaign_executions(TEAM_ID) == 1
    row = _row(sb)
    assert row['status'] == 'aborted' and row['status'] in PERMITTED_STATUSES
    assert row['success'] is False
    completed = datetime.fromisoformat(row['completed_at'])
    assert completed.tzinfo is not None
    assert abs((completed - last).total_seconds()) < 5          # the last activity,
    assert before_call - completed > 100 * MIN                  # not the reader's clock
    assert row['error_message'].startswith('Campaign execution abandoned: no activity for 200 min (limit 125 min); ')
    assert row['error_message'].endswith('1 of 2 expected script results recorded, 0 succeeded')


def test_all_succeeded_but_fewer_than_expected_names_the_counts(sb):
    _seed(sb, started_ago=400 * MIN, scripts=[(390 * MIN, 380 * MIN, True)], expected=2)
    assert campaign_db.reconcile_stale_campaign_executions(TEAM_ID) == 1
    row = _row(sb)
    assert row['error_message'] != 'Campaign execution became stale before completion'
    assert row['status'] == 'aborted' and row['success'] is False
    assert row['error_message'].endswith('1 of 2 expected script results recorded, 1 succeeded')


def test_abandoned_row_still_ends_closed(sb):
    """Guard (passes before the fix too): the repair must not be deleted."""
    _seed(sb, started_ago=600 * MIN, scripts=[(590 * MIN, None, False)], expected=2)
    campaign_db.reconcile_stale_campaign_executions(TEAM_ID)
    assert _row(sb)['status'] != 'running'


def test_no_script_fetch_when_a_row_has_no_script_results(sb):
    _seed(sb, started_ago=10 * MIN, scripts=[], expected=2)
    sb.counting.calls.clear()
    campaign_db.reconcile_stale_campaign_executions(TEAM_ID)
    assert sb.counting.calls == ['campaign_executions']


def test_finished_campaign_younger_than_the_limit_is_closed_by_its_scripts(sb):
    _seed(sb, started_ago=10 * MIN,
          scripts=[(9 * MIN, 5 * MIN, True), (8 * MIN, 4 * MIN, True)])
    assert campaign_db.reconcile_stale_campaign_executions(TEAM_ID) == 1
    row = _row(sb)
    assert row['status'] == 'completed' and row['success'] is True
    assert row['execution_time_ms'] == 2000


def test_repeated_reads_repair_at_most_once(sb):
    _seed(sb, started_ago=10 * MIN)
    sb.counting.calls.clear()
    for _ in range(3):
        campaign_db.get_campaign_results(TEAM_ID)
    selects = [t for t in sb.counting.calls if t == 'campaign_executions']
    # one repair select + one result select on the first read, one result select per later read
    assert len(selects) == 4


def test_executor_final_write_wins(sb):
    """Guard: a verdict the executor wrote after the threshold is never overwritten."""
    _seed(sb, started_ago=170 * MIN, scripts=[(160 * MIN, 1 * MIN, True)])
    sb.table('campaign_executions').update(
        {'status': 'completed', 'success': True, 'completed_at': _iso(datetime.now(timezone.utc))}
    ).eq('id', 'c1').execute()
    before = dict(_row(sb))
    assert campaign_db.reconcile_stale_campaign_executions(TEAM_ID) == 0
    assert _row(sb) == before
