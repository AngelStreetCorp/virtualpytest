"""A dead run must not leave its script_results row behind (BUG-0837).

`record_script_execution_start` opens every run with a placeholder row (`execution_time_ms IS
NULL`, `success = False`) and `update_script_execution_result` closes it when the script finishes.
When the run dies first, nothing closes it -- the deployment sweeper can only reach rows whose
`deployment_executions.script_result_id` it can read, and that column is scraped out of the
*finished* run's stdout, so for a dead run it is always NULL. The row then sits on the dashboard
for ever as a failure that never happened, with no error message.

The Supabase client is faked at the query level, so the window, the bare-name match and the grace
period are actually exercised rather than grepped.

Run: pytest tests/backend_host/test_deployment_scheduler_orphan_results.py -v
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, '..', '..'))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

pytestmark = pytest.mark.unit


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, fake, name):
        self.f = fake
        self.name = name

    def select(self, *cols, **k):
        self.f.selects.setdefault(self.name, []).append(cols[0] if cols else '')
        return self

    def eq(self, col, val):
        self.f.filters.append((self.name, 'eq', col, val))
        return self

    def is_(self, col, val):
        self.f.filters.append((self.name, 'is_null', col, None if val == 'null' else val))
        return self

    def lt(self, col, val):
        self.f.filters.append((self.name, 'lt', col, val))
        return self

    def gte(self, col, val):
        self.f.filters.append((self.name, 'gte', col, val))
        return self

    def lte(self, col, val):
        self.f.filters.append((self.name, 'lte', col, val))
        return self

    def order(self, col, desc=False):
        self.f.order = (col, desc)
        return self

    def update(self, payload):
        self.f.updates.append((self.name, payload))
        return self

    def insert(self, payload):
        self.f.inserts.append((self.name, payload))
        return self

    def execute(self):
        rows = list(self.f.data.get(self.name, []))
        for tbl, op, col, val in self.f.filters:
            if tbl != self.name:
                continue
            if op == 'eq':
                rows = [r for r in rows if r.get(col) == val]
            elif op == 'is_null':
                rows = [r for r in rows if r.get(col) is None]
            elif op == 'lt':
                rows = [r for r in rows if str(r.get(col)) < str(val)]
            elif op == 'gte':
                rows = [r for r in rows if str(r.get(col)) >= str(val)]
            elif op == 'lte':
                rows = [r for r in rows if str(r.get(col)) <= str(val)]
        if self.f.order and self.f.order[1]:
            rows.sort(key=lambda r: str(r.get(self.f.order[0])), reverse=True)
        return _Result(rows)


class _FakeSupabase:
    def __init__(self, data=None):
        self.data = data or {}
        self.filters = []
        self.updates = []
        self.inserts = []
        self.selects = {}
        self.order = None

    def table(self, name):
        return _Table(self, name)

    def updates_on(self, name):
        return [p for t, p in self.updates if t == name]

    def selects_on(self, name):
        return self.selects.get(name, [])


@pytest.fixture
def sched():
    """A DeploymentScheduler wired to a fake client, without touching APScheduler's start()."""
    from backend_host.src.services import deployment_scheduler as ds

    fake = _FakeSupabase()
    inst = ds.DeploymentScheduler.__new__(ds.DeploymentScheduler)
    inst.host_name = 'host-clone-2'
    inst.supabase = fake
    import threading
    inst.db_lock = threading.Lock()
    inst.fake = fake
    return inst


def _dead_execution(script_name='game/game_tetris.py', started=None):
    return {
        'id': 'exec-1',
        'script_result_id': None,
        'started_at': _iso(started),
        'deployments': {'host_name': 'host-clone-2', 'script_name': script_name},
    }


# ---- fix 1: the dead execution recovers the placeholder it left behind -------------- #

def test_a_dead_execution_closes_the_placeholder_it_orphaned(sched):
    """The bug: script_result_id is scraped from finished stdout, so a dead run has none."""
    started = datetime.now(timezone.utc) - timedelta(hours=2)
    sched.fake.data['script_results'] = [{
        'id': 'sr-orphan', 'script_name': 'game_tetris',
        'host_name': 'host-clone-2', 'execution_time_ms': None,
        'started_at': _iso(started + timedelta(seconds=20)),
    }]
    sched.fake.data['deployment_executions'] = []

    sched._mark_stale_execution_failed(_dead_execution(started=started), 'timed out')

    closed = sched.fake.updates_on('script_results')
    assert len(closed) == 1
    assert closed[0]['success'] is False
    assert 'timed out' in closed[0]['error_msg']
    assert closed[0]['completed_at']


def test_the_recovered_row_is_found_by_host_and_script_not_merely_by_time(sched):
    """Another script's placeholder from the same hour must not be closed by this execution."""
    started = datetime.now(timezone.utc) - timedelta(hours=2)
    near = started + timedelta(seconds=10)
    sched.fake.data['script_results'] = [
        {'id': 'sr-other-script', 'script_name': 'game_kirby', 'host_name': 'host-clone-2',
         'execution_time_ms': None, 'started_at': _iso(near)},
        {'id': 'sr-other-host', 'script_name': 'game_tetris', 'host_name': 'host-clone-1',
         'execution_time_ms': None, 'started_at': _iso(near)},
        {'id': 'sr-mine', 'script_name': 'game_tetris', 'host_name': 'host-clone-2',
         'execution_time_ms': None, 'started_at': _iso(near)},
    ]
    sched.fake.data['deployment_executions'] = []

    sched._mark_stale_execution_failed(_dead_execution(started=started), 'timed out')

    assert len(sched.fake.updates_on('script_results')) == 1


def test_a_finished_row_is_never_touched_by_the_recovery(sched):
    """execution_time_ms set means the run closed its own row: leave it alone."""
    started = datetime.now(timezone.utc) - timedelta(hours=2)
    sched.fake.data['script_results'] = [{
        'id': 'sr-done', 'script_name': 'game_tetris', 'host_name': 'host-clone-2',
        'execution_time_ms': 123456, 'started_at': _iso(started),
    }]
    sched.fake.data['deployment_executions'] = []

    sched._mark_stale_execution_failed(_dead_execution(started=started), 'timed out')

    assert sched.fake.updates_on('script_results') == []


def test_the_scraped_id_is_still_honoured_when_the_run_printed_one(sched):
    started = datetime.now(timezone.utc) - timedelta(hours=2)
    sched.fake.data['script_results'] = []
    sched.fake.data['deployment_executions'] = []
    execution = _dead_execution(started=started)
    execution['script_result_id'] = 'sr-from-stdout'

    sched._mark_stale_execution_failed(execution, 'timed out')

    # No lookup query was needed at all.
    assert sched.fake.selects_on('script_results') == []
    assert sched.fake.updates_on('script_results')[0]['success'] is False


# ---- fix 2: the periodic sweep for rows no execution links ------------------------- #

def test_the_sweep_closes_only_rows_past_the_grace(sched):
    from backend_host.src.services import deployment_scheduler as ds

    now = datetime.now(timezone.utc)
    sched.fake.data['script_results'] = [
        {'id': 'sr-old', 'script_name': 'a', 'host_name': 'host-clone-2',
         'execution_time_ms': None, 'started_at': _iso(now - timedelta(seconds=ds.ORPHANED_SCRIPT_RESULT_GRACE_SECONDS + 600))},
        {'id': 'sr-recent', 'script_name': 'b', 'host_name': 'host-clone-2',
         'execution_time_ms': None, 'started_at': _iso(now - timedelta(minutes=5))},
    ]

    assert sched._sweep_orphaned_script_results() == 1
    closed = sched.fake.updates_on('script_results')
    assert len(closed) == 1
    assert 'never reported a verdict' in closed[0]['error_msg']


def test_the_sweep_only_touches_this_host(sched):
    now = datetime.now(timezone.utc)
    old = _iso(now - timedelta(hours=9))
    sched.fake.data['script_results'] = [
        {'id': 'sr-mine', 'script_name': 'a', 'host_name': 'host-clone-2',
         'execution_time_ms': None, 'started_at': old},
        {'id': 'sr-theirs', 'script_name': 'a', 'host_name': 'host-clone-1',
         'execution_time_ms': None, 'started_at': old},
    ]

    assert sched._sweep_orphaned_script_results() == 1


def test_the_grace_sits_above_the_longest_legitimate_run():
    """game_clashofclans_llm is allowed 90 min before its deployment is called an orphan."""
    from backend_host.src.services import deployment_scheduler as ds

    assert ds.ORPHANED_SCRIPT_RESULT_GRACE_SECONDS > 5400