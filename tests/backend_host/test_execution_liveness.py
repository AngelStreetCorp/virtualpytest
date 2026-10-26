"""The host's busy signal must be liveness-based, not row-based (E50).

A `deployment_executions` row in 'running' is a CLAIM, not a fact: the run that owns it
died - or the host restarted - and the row stayed 'running'. Two things happened because
of that:

  * the busy snapshot (`/host/deployment/jobs`) reported the dead row, so the deploy gate
    deferred every restart of this host,
  * the server's stale-row reaper skipped the dead row, because it asked "is this DEVICE
    busy?" and one unrelated live run on the same device answered yes. A runaway run
    shielded every dead row of the host.

What is checked here:
  - a row whose process is gone is not reported as running,
  - a row whose process is alive still is,
  - a row the host cannot judge yet (the run started, its process did not register) is
    kept rather than called dead,
  - a registry the host cannot read keeps every row: unknown is busy, never "dead".
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))

liveness = pytest.importorskip('backend_host.src.services.execution_liveness')
script_executor = pytest.importorskip('shared.src.lib.executors.script_executor')


class _Process:
    """A process that is either alive or gone."""

    def __init__(self, alive=True):
        self._alive = alive

    def poll(self):
        return None if self._alive else 0


@pytest.fixture
def registry():
    """The host's script process registry, empty before and after the test."""
    with script_executor._running_processes_lock:
        script_executor._running_processes_by_device.clear()
    yield script_executor._running_processes_by_device
    with script_executor._running_processes_lock:
        script_executor._running_processes_by_device.clear()


def _row(execution_id, age_s=7200):
    started = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return {
        'id': execution_id,
        'status': 'running',
        'started_at': started.isoformat(),
        'deployments': {'host_name': '<host>', 'device_id': 'host', 'name': 'game_tetris.py'},
    }


def _register(device_id, execution_id, alive=True):
    with script_executor._running_processes_lock:
        script_executor._running_processes_by_device.setdefault(device_id, []).append({
            'process': _Process(alive=alive),
            'script_name': 'game_tetris.py',
            'started_at': 0,
            'task_id': 'task-1',
            'execution_id': execution_id,
        })


def test_a_row_whose_process_is_gone_is_not_reported_as_running(registry):
    """The dead claim must leave the busy signal, or the deploy defers forever (E50)."""
    _register('host', 'exec-dead', alive=False)

    live, stale = liveness.split_running_by_liveness([_row('exec-dead')])

    assert [r['id'] for r in stale] == ['exec-dead']
    assert live == []


def test_a_row_with_no_process_at_all_is_not_reported_as_running(registry):
    """A row nobody runs any more is a dead claim too (the host restarted, the run died)."""
    live, stale = liveness.split_running_by_liveness([_row('exec-gone')])

    assert [r['id'] for r in stale] == ['exec-gone']
    assert live == []


def test_a_live_run_is_still_reported_as_running(registry):
    """The busy signal must not lose a run that is really going."""
    _register('host', 'exec-live', alive=True)

    live, stale = liveness.split_running_by_liveness([_row('exec-live')])

    assert [r['id'] for r in live] == ['exec-live']
    assert stale == []


def test_a_dead_row_does_not_hide_behind_an_unrelated_live_run(registry):
    """The bug: a live run on the device shielded every dead row of that device."""
    _register('host', 'exec-live', alive=True)

    live, stale = liveness.split_running_by_liveness([_row('exec-dead'), _row('exec-live')])

    assert [r['id'] for r in live] == ['exec-live']
    assert [r['id'] for r in stale] == ['exec-dead']


def test_a_row_that_just_started_is_not_called_dead(registry):
    """The row is created before the script starts: a run that is still registering its
    process must not be reaped (E50)."""
    live, stale = liveness.split_running_by_liveness([_row('exec-starting', age_s=5)])

    assert [r['id'] for r in live] == ['exec-starting']
    assert stale == []


def test_a_registry_the_host_cannot_read_keeps_every_row(monkeypatch):
    """Unknown is busy: the host may not close a row on a guess."""
    import builtins
    real_import = builtins.__import__

    def broken_import(name, *args, **kwargs):
        if 'script_executor' in name:
            raise ImportError('registry unavailable')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', broken_import)

    snapshot = liveness.liveness_snapshot()
    assert snapshot['complete'] is False

    live, stale = liveness.split_running_by_liveness([_row('exec-dead')])
    assert [r['id'] for r in live] == ['exec-dead']
    assert stale == []


def test_execution_is_alive_answers_per_row(registry):
    """The per-row question: is THIS execution still running?"""
    _register('host', 'exec-live', alive=True)

    assert liveness.execution_is_alive('exec-live') is True
    assert liveness.execution_is_alive('exec-dead') is False
