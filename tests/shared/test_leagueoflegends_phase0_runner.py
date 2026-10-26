"""Tests for the phase-0 orchestrator.

Covers :mod:`shared.src.lib.game.leagueoflegends.phase0_runner`.

The orchestrator is the end-to-end launcher chain (Riot → League).
Tests use mocked tracker / executor / detector / screenshot_fn so
the chain runs deterministically on macOS.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List

import pytest
from PIL import Image

from shared.src.lib.game.leagueoflegends.click_executor import ClickResult
from shared.src.lib.game.leagueoflegends.contracts_window import (
    DriftTolerance,
    ScreenPoint,
    WindowGeometry,
)
from shared.src.lib.game.leagueoflegends.phase0_runner import (
    Phase0Config,
    Phase0Result,
    Phase0Runner,
    StepRecord,
)
from shared.src.lib.game.leagueoflegends.vision_nav import (
    LOL_ICON,
    PLAY_BUTTON,
    NavHit,
    NavTarget,
    NavTargetDetector,
)
from shared.src.lib.game.leagueoflegends.window_tracker import TrackedWindow


# ---------------------------------------------------------------------------
# Fakes — fully controllable stand-ins for the Win32 pieces.
# ---------------------------------------------------------------------------


class FakeTracker:
    """Tracker fake: returns pre-configured windows / geometries."""

    def __init__(self) -> None:
        self._windows: List[TrackedWindow] = []
        self._current_geometry: WindowGeometry | None = None

    def set_windows(self, windows: List[TrackedWindow]) -> None:
        self._windows = windows

    def set_current_geometry(self, geom: WindowGeometry) -> None:
        self._current_geometry = geom

    def enumerate(self) -> List[TrackedWindow]:
        return list(self._windows)

    def query_by_hwnd(self, hwnd: int) -> WindowGeometry | None:
        return self._current_geometry

    def wait_for_window(
        self,
        *,
        title: str | None = None,
        class_name: str | None = None,
        pid: int | None = None,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.5,
    ) -> TrackedWindow | None:
        for w in self._windows:
            if title is not None and title not in w.title:
                continue
            if class_name is not None and w.class_name != class_name:
                continue
            if pid is not None and w.pid != pid:
                continue
            return w
        return None

    def query_by_class(self, class_name: str):
        return [w for w in self._windows if w.class_name == class_name]

    def find_riot_client(self):
        return self.query_by_title_or_none("Riot Client", exact=True)

    def find_league_client(self):
        return self.query_by_title_or_none("League of Legends", exact=False)

    def query_by_title_or_none(self, title: str, *, exact: bool = True):
        for w in self._windows:
            if exact and w.title == title:
                return w
            if not exact and title in w.title:
                return w
        return None


class FakeExecutor:
    """Executor fake: returns a successful ClickResult without sending input."""

    def __init__(self) -> None:
        self.clicks: List[ScreenPoint] = []

    def click(
        self,
        screen_point: ScreenPoint,
        *,
        captured=None,
        current=None,
        tolerance=None,
        now_monotonic_ns=None,
        dry_run: bool = False,
    ) -> ClickResult:
        self.clicks.append(screen_point)
        return ClickResult(
            delivered=True,
            reason=f"fake clicked at ({screen_point.x}, {screen_point.y})",
            screen_point=screen_point,
        )


class FakeDetector:
    """Detector fake: returns one hit at a configured normalized point."""

    def __init__(self, hit_normalized_x: float = 0.5, hit_normalized_y: float = 0.5) -> None:
        self._x = hit_normalized_x
        self._y = hit_normalized_y

    def detect_best(self, screenshot_path, target: NavTarget):
        from shared.src.lib.game.leagueoflegends.contracts_decision import Point
        return NavHit(
            target_name=target.name,
            normalized=Point(x=self._x, y=self._y),
            match_score=0.95,
            bbox=(0, 0, 32, 32),
        )


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _geom(**overrides) -> WindowGeometry:
    payload = dict(
        schema_version="league-window/v1",
        hwnd=0xAAAA,
        x=100, y=100, w=1500, h=900,
        captured_at_ns=1_000_000_000,
    )
    payload.update(overrides)
    return WindowGeometry(**payload)


def _tracked(hwnd: int, title: str, geom: WindowGeometry) -> TrackedWindow:
    return TrackedWindow(geometry=geom, title=title, class_name="Chrome_WidgetWin_1", pid=12345)


def _screenshot_stub(target_path: Path) -> None:
    """``screenshot_fn`` fake: write a 1500x900 placeholder PNG."""
    Image.new("RGB", (1500, 900), (40, 40, 50)).save(target_path)


# ---------------------------------------------------------------------------
# End-to-end happy path (with fakes).
# ---------------------------------------------------------------------------


def test_phase0_happy_path_returns_ok_with_two_step_records() -> None:
    tracker = FakeTracker()
    riot_geom = _geom(hwnd=0xAAAA)
    league_geom = _geom(hwnd=0xBBBB, x=200, y=200)
    riot_window = _tracked(0xAAAA, "Riot Client", riot_geom)
    league_window = _tracked(0xBBBB, "League of Legends", league_geom)
    tracker.set_windows([riot_window, league_window])
    tracker.set_current_geometry(riot_geom)

    executor = FakeExecutor()
    detector = FakeDetector(hit_normalized_x=0.5, hit_normalized_y=0.5)

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Phase0Config(
            screenshot_dir=Path(tmpdir),
            riot_window_timeout_s=5.0,
            league_window_timeout_s=5.0,
            league_game_timeout_s=5.0,
            screenshot_fn=_screenshot_stub,
        )
        runner = Phase0Runner(
            cfg,
            tracker=tracker,
            executor=executor,
            detector=detector,
        )
        result = runner.run()

    assert isinstance(result, Phase0Result)
    # The launch_riot step uses real subprocess — it may or may not
    # succeed in the test env. We only assert the steps after the
    # launch (the orchestrator hard-stops on launch failure).
    step_names = [s.name for s in result.steps]
    if "launch_riot" in step_names:
        launch_idx = step_names.index("launch_riot")
        if not result.steps[launch_idx].ok:
            pytest.skip(f"launch_riot step failed in test env: {result.steps[launch_idx].detail}")

    assert step_names[0] == "kill_existing"
    assert step_names[1] == "launch_riot"
    assert step_names[2] == "wait_for_riot"

    # We expect at least these steps: kill_existing, launch, wait_for_riot, click_lol, wait_for_league, click_play
    assert "click_lol_icon" in step_names
    assert "wait_for_league" in step_names
    assert "click_play_button" in step_names

    # The orchestrator should have clicked twice (once for LoL icon, once for Play).
    assert len(executor.clicks) == 2


def test_phase0_runner_requires_screenshot_fn() -> None:
    """No default screenshot_fn — operator must inject one."""
    cfg = Phase0Config(screenshot_fn=None)
    with pytest.raises(ValueError, match="screenshot_fn"):
        Phase0Runner(cfg)


def test_phase0_runner_uses_overridden_screenshot_fn() -> None:
    """An override at construction takes precedence over config.screenshot_fn."""
    sentinel_calls: List[Path] = []

    def fake_screenshot(p: Path) -> None:
        sentinel_calls.append(p)
        Image.new("RGB", (100, 100), (0, 0, 0)).save(p)

    cfg = Phase0Config(screenshot_fn=_screenshot_stub)
    runner = Phase0Runner(cfg, screenshot_fn=fake_screenshot)
    assert runner._screenshot_fn is fake_screenshot


# ---------------------------------------------------------------------------
# Step-level behavior.
# ---------------------------------------------------------------------------


def test_phase0_wait_for_riot_window_succeeds() -> None:
    """The wait_for_riot step finds a window whose title is 'Home'."""
    tracker = FakeTracker()
    riot_geom = _geom(hwnd=0xAAAA)
    tracker.set_windows([_tracked(0xAAAA, "Riot Client", riot_geom)])

    executor = FakeExecutor()
    detector = FakeDetector()

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Phase0Config(
            screenshot_dir=Path(tmpdir),
            screenshot_fn=_screenshot_stub,
            riot_window_timeout_s=2.0,
        )
        runner = Phase0Runner(cfg, tracker=tracker, executor=executor, detector=detector)
        rec, window = runner._wait_for_riot_window()
        assert rec.ok
        assert window.geometry.hwnd == 0xAAAA
        assert rec.detail.startswith("Riot window HWND=")


def test_phase0_wait_for_riot_window_fails_when_no_match() -> None:
    tracker = FakeTracker()  # empty
    rec, _window = Phase0Runner(
        Phase0Config(screenshot_fn=_screenshot_stub, riot_window_timeout_s=1.0),
        tracker=tracker,
    )._wait_for_riot_window()
    assert not rec.ok
    assert "did not appear" in rec.detail


# ---------------------------------------------------------------------------
# AST guard.
# ---------------------------------------------------------------------------


def test_phase0_runner_does_not_import_pyautogui() -> None:
    """AST guard: no pyautogui imports (FR-13)."""
    import ast
    src = open("shared/src/lib/game/leagueoflegends/phase0_runner.py").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                assert "pyautogui" not in alias.name, (
                    f"pyautogui import found at line {node.lineno}: {alias.name}"
                )


def test_phase0_runner_step_record_immutable() -> None:
    """StepRecord is a frozen dataclass."""
    import dataclasses
    rec = StepRecord(name="x", ok=True, detail="y")
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.ok = False  # type: ignore[misc]