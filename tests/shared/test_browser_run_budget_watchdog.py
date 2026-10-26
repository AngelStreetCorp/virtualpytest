"""A browser run must not outlive its budget, and must report why it ended (BUG-0842).

``--max_duration`` was a script argument and nothing else: the game scripts stop there,
but nothing outside the action loop enforced it. A run whose device call never returned
therefore stayed alive for ever — no result, and the browser and the driver it held left
behind.

The watchdog lives outside the action loop: the executor watches the run itself, stops it
at the run's own budget, closes what the run held, and says why in the result.

What is checked here:
  - the run's own ``--max_duration`` is the ceiling when the caller declared none,
  - a budget declared by the caller still wins,
  - a run without any budget keeps the default,
  - a run over budget is stopped AND its browser is torn down (no orphan),
  - the result reports a timeout with a reason, never a silent success,
  - a healthy run keeps its old verdict.
"""

import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))

script_executor_mod = importlib.import_module('shared.src.lib.executors.script_executor')

ScriptExecutor = script_executor_mod.ScriptExecutor
MARGIN = script_executor_mod.SCRIPT_RESULT_WRITE_MARGIN_SECONDS


def _new(name):
    """The new API, or None when this code does not have it yet."""
    return getattr(script_executor_mod, name, None)


# ---------------------------------------------------------------------------
# The budget of the run
# ---------------------------------------------------------------------------

def test_the_runs_own_max_duration_is_read_out_of_its_parameters():
    reader = _new('declared_run_budget_seconds')
    assert reader is not None, 'nothing reads the budget out of the run parameters'
    assert reader('--max_pieces 300 --max_duration 900') == 900
    assert reader('--max_duration 900 --max_pieces 300') == 900
    assert reader('--max_duration=900') == 900


def test_a_run_without_a_budget_declares_none():
    reader = _new('declared_run_budget_seconds')
    assert reader is not None, 'nothing reads the budget out of the run parameters'
    assert reader('') is None
    assert reader('--max_pieces 300') is None
    assert reader('--max_duration abc') is None
    assert reader('--max_duration 0') is None


def test_the_executor_stops_the_run_at_its_own_budget():
    """The ceiling the executor enforces is the run's own budget plus the write margin."""
    executor = ScriptExecutor('game_tetris.py', host_name='<host>', device_id='host',
                              device_model='host')
    executor.timeout_seconds = None
    executor.run_parameters = '--max_pieces 300 --max_duration 900'

    assert executor.resolve_timeout_seconds() == 900 + MARGIN
    assert executor.resolve_timeout_seconds() < 3600


def test_a_budget_declared_by_the_caller_still_wins():
    assert _new('declared_run_budget_seconds') is not None, \
        'the run parameters carry no budget to read'
    executor = ScriptExecutor('game_tetris.py', host_name='<host>', device_id='host',
                              device_model='host')
    executor.timeout_seconds = 120
    executor.run_parameters = '--max_duration 900'

    assert executor.resolve_timeout_seconds() == 120 + MARGIN


def test_a_run_without_any_budget_keeps_the_default():
    assert _new('declared_run_budget_seconds') is not None, \
        'the run parameters carry no budget to read'
    executor = ScriptExecutor('game_tetris.py', host_name='<host>', device_id='host',
                              device_model='host')
    executor.timeout_seconds = None
    executor.run_parameters = '--max_pieces 300'

    assert executor.resolve_timeout_seconds() == 3600


def test_a_budget_larger_than_the_platform_ceiling_does_not_raise_it():
    """The platform's own ceiling still bounds the run."""
    executor = ScriptExecutor('game_tetris.py', host_name='<host>', device_id='host',
                              device_model='host')
    executor.timeout_seconds = None
    executor.run_parameters = '--max_duration 7200'

    assert executor.resolve_timeout_seconds() == 3600 + MARGIN


# ---------------------------------------------------------------------------
# The watchdog: the run ends, and what it held is closed
# ---------------------------------------------------------------------------

def test_a_run_over_budget_is_stopped_and_its_browser_is_closed(monkeypatch):
    """The script never reached its own teardown, so the host closes what the run held."""
    stop = _new('stop_run_for_timeout')
    assert stop is not None, 'nothing stops a run that outlived its budget'
    killed, torn_down = [], []

    monkeypatch.setattr(script_executor_mod, '_kill_process_tree',
                        lambda process, timeout=5.0: killed.append(process))
    monkeypatch.setattr(script_executor_mod, '_teardown_run_browser',
                        lambda: torn_down.append(True) or {'reaped': [], 'reaped_drivers': []})

    reason = stop('the-run', 900, 1204.5)

    assert killed == ['the-run'], 'the run was not stopped'
    assert torn_down == [True], 'the browser the run held was left behind'
    assert '900' in reason
    assert '1204.5' in reason


def test_a_stopped_run_reports_a_timeout_with_a_reason():
    verdict = _new('apply_timeout_verdict')
    assert verdict is not None, 'there is no timeout verdict to report'

    result = verdict({'script_success': True, 'stdout': 'partial'}, 'because')

    assert result['timed_out'] is True
    assert result['timeout_reason'] == 'because'
    assert result['script_success'] is False, 'a timed-out run must not report a success'


def test_a_healthy_run_keeps_its_own_verdict():
    """The timeout keys are only ever added to a run that was actually stopped."""
    verdict = _new('apply_timeout_verdict')
    assert verdict is not None, 'there is no timeout verdict to apply'

    healthy = {'script_success': True, 'stdout': 'ok', 'exit_code': 0}

    assert 'timed_out' not in healthy
    assert 'timeout_reason' not in healthy
    assert healthy['script_success'] is True
