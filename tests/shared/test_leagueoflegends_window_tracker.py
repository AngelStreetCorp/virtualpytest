"""Tests for the Win32 window tracker.

Covers :mod:`shared.src.lib.game.leagueoflegends.window_tracker`.

These tests run on macOS (the worktree). The tracker is *read-only*
and platform-guarded: on non-Windows hosts every public method
raises :class:`TrackerUnavailableError` immediately. The tests verify
that contract — that the tracker is *importable* on any host but
*invokable* only on Windows.
"""
from __future__ import annotations

import sys

import pytest

from shared.src.lib.game.leagueoflegends.window_tracker import (
    TrackerUnavailableError,
    TrackedWindow,
    Win32WindowTracker,
)


# ---------------------------------------------------------------------------
# Cross-platform guard.
# ---------------------------------------------------------------------------


def test_tracker_unavailable_on_non_windows() -> None:
    """Every public method on the tracker raises TrackerUnavailableError on macOS."""
    if sys.platform == "win32":
        pytest.skip("this test asserts macOS guard; skip on Windows")
    tracker = Win32WindowTracker()
    with pytest.raises(TrackerUnavailableError):
        tracker.enumerate()
    with pytest.raises(TrackerUnavailableError):
        tracker.query_by_hwnd(0x12345)
    with pytest.raises(TrackerUnavailableError):
        tracker.query_by_title("Riot Client")
    with pytest.raises(TrackerUnavailableError):
        tracker.query_by_class("Chrome_WidgetWin_1")
    with pytest.raises(TrackerUnavailableError):
        tracker.query_by_pid(1234)
    with pytest.raises(TrackerUnavailableError):
        tracker.wait_for_window(title="Riot Client", timeout_s=1.0)
    with pytest.raises(TrackerUnavailableError):
        tracker.find_riot_client()
    with pytest.raises(TrackerUnavailableError):
        tracker.find_league_client()


def test_wait_for_window_requires_at_least_one_matcher() -> None:
    """The wait_for_window method refuses a parameter-less call on any platform."""
    tracker = Win32WindowTracker()
    if sys.platform == "win32":
        with pytest.raises(ValueError):
            tracker.wait_for_window(timeout_s=0.1)
    else:
        # On macOS the platform guard fires first — still raises.
        with pytest.raises(TrackerUnavailableError):
            tracker.wait_for_window(timeout_s=0.1)


# ---------------------------------------------------------------------------
# Data shape.
# ---------------------------------------------------------------------------


def test_tracked_window_is_frozen_dataclass() -> None:
    """TrackedWindow is immutable (frozen dataclass)."""
    from shared.src.lib.game.leagueoflegends.contracts_window import WindowGeometry
    geom = WindowGeometry(
        schema_version="league-window/v1",
        hwnd=0xAAAA,
        x=0, y=0, w=100, h=100, captured_at_ns=0,
    )
    w = TrackedWindow(geometry=geom, title="Riot Client", class_name="Chrome_WidgetWin_1", pid=12345)
    assert w.geometry.hwnd == 0xAAAA
    assert w.title == "Riot Client"
    assert w.class_name == "Chrome_WidgetWin_1"
    assert w.pid == 12345
    # Frozen — assignment raises.
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        w.title = "different"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AST guard.
# ---------------------------------------------------------------------------


def test_window_tracker_does_not_import_pyautogui() -> None:
    """The tracker never imports pyautogui (FR-13)."""
    import ast
    src = open("shared/src/lib/game/leagueoflegends/window_tracker.py").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                assert "pyautogui" not in alias.name, (
                    f"pyautogui import found at line {node.lineno}"
                )
        if isinstance(node, ast.Attribute):
            assert "pyautogui" not in ast.dump(node)