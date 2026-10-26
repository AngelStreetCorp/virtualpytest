"""A run must not outlive its declared budget (E50).

The executor's ceiling was a flat 3600 s (4 h for a full-tree validation), so a game run
that declared `--max_duration 900` still got an hour: the journal showed the kill at
3600 s, and the host was busy for four times the declared budget.

The contract is now explicit: the CALLER declares the budget of the run (the game
dispatcher reads it from the script's own `--max_duration`), the server hands it to the
host, and the executor enforces it as the run's hard ceiling. The budget is the script's
own stop, so the executor adds the margin the script needs to write its result.

What is checked here:
  - a declared budget wins over the flat default,
  - a run without a declared budget keeps the defaults (no global value is imposed),
  - the full-tree validation keeps its 4 h (BUG-0633),
  - the executor really uses the declared budget.
"""

import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))

script_executor_mod = importlib.import_module('shared.src.lib.executors.script_executor')

resolve_script_timeout_seconds = script_executor_mod.resolve_script_timeout_seconds
ScriptExecutor = script_executor_mod.ScriptExecutor
MARGIN = script_executor_mod.SCRIPT_RESULT_WRITE_MARGIN_SECONDS


def test_a_declared_budget_wins_over_the_flat_default():
    assert resolve_script_timeout_seconds('game_tetris.py', 900) == 900 + MARGIN
    assert resolve_script_timeout_seconds('game_tetris.py', 900) < 3600


def test_a_run_without_a_declared_budget_keeps_the_default():
    assert resolve_script_timeout_seconds('game_tetris.py') == 3600
    assert resolve_script_timeout_seconds('game_tetris.py', None) == 3600


def test_a_full_tree_validation_keeps_its_four_hours():
    """A validation of stb_tv takes 70+ min on a slow box (BUG-0633)."""
    assert resolve_script_timeout_seconds('validation') == 4 * 3600
    assert resolve_script_timeout_seconds('validation.py') == 4 * 3600


def test_a_nonsense_budget_falls_back_to_the_default():
    assert resolve_script_timeout_seconds('game_tetris.py', 0) == 3600
    assert resolve_script_timeout_seconds('game_tetris.py', -5) == 3600
    assert resolve_script_timeout_seconds('game_tetris.py', 'not a number') == 3600


def test_the_executor_enforces_the_declared_budget():
    executor = ScriptExecutor('game_tetris.py', host_name='<host>', device_id='host', device_model='host')
    executor.script_name = 'game_tetris.py'

    executor.timeout_seconds = 900
    assert executor.resolve_timeout_seconds() == 900 + MARGIN

    executor.timeout_seconds = None
    assert executor.resolve_timeout_seconds() == 3600
