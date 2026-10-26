"""Tests for the Win32 click executor.

Covers :mod:`shared.src.lib.game.leagueoflegends.click_executor`.

The executor is **Windows-only**; on macOS every public method
raises :class:`ExecutorUnavailableError`. The tests verify that
contract and the AST guard.
"""
from __future__ import annotations

import sys

import pytest

from shared.src.lib.game.leagueoflegends.click_executor import (
    ExecutorUnavailableError,
    Win32ClickExecutor,
)


def test_executor_unavailable_on_non_windows() -> None:
    if sys.platform == "win32":
        pytest.skip("macOS guard; skip on Windows")
    executor = Win32ClickExecutor()
    from shared.src.lib.game.leagueoflegends.contracts_window import ScreenPoint
    with pytest.raises(ExecutorUnavailableError):
        executor.click(ScreenPoint(x=100, y=100))
    with pytest.raises(ExecutorUnavailableError):
        executor.move_to(ScreenPoint(x=100, y=100))
    with pytest.raises(ExecutorUnavailableError):
        executor.cursor_pos()


def test_executor_dry_run_returns_clickresult_without_input() -> None:
    """``dry_run=True`` does not call SendInput (skipped on macOS)."""
    if sys.platform != "win32":
        pytest.skip("dry_run requires Windows for full path; skipped on macOS")
    from shared.src.lib.game.leagueoflegends.contracts_window import ScreenPoint
    executor = Win32ClickExecutor()
    result = executor.click(ScreenPoint(x=1234, y=567), dry_run=True)
    assert not result.delivered
    assert "1234" in result.reason
    assert "567" in result.reason


def test_click_executor_does_not_import_pyautogui() -> None:
    """AST guard: no pyautogui imports (FR-13)."""
    import ast
    src = open("shared/src/lib/game/leagueoflegends/click_executor.py").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                assert "pyautogui" not in alias.name