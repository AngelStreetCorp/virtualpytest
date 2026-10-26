"""Tests for the League of Legends window-geometry contracts and drift translator.

Covers :mod:`shared.src.lib.game.leagueoflegends.contracts_window`
(WindowGeometry, DriftTolerance, TranslationResult, and the pure
``translate_decision_to_screen`` function).

No real League client interaction; no ``pyautogui``; no League-process
helper. The tests are deterministic — the caller supplies the monotonic
clock reading (``now_monotonic_ns``) so a translation's staleness gate is
testable to the nanosecond.
"""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from shared.src.lib.game.leagueoflegends.contracts_decision import Point
from shared.src.lib.game.leagueoflegends.contracts_window import (
    DriftTolerance,
    ScreenPoint,
    TranslationResult,
    WindowGeometry,
    translate_decision_to_screen,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _geom(**overrides: Any) -> WindowGeometry:
    """Build a valid minimal ``WindowGeometry`` for tests.

    Defaults to a 1500x900 Riot Client-ish window at (1524, 476) — the
    coordinates the Riot Client log says it uses (392x488 splash,
    centered on the 3440x1440 primary monitor — see TASK-121 evidence
    files). Tests override the fields they care about.
    """
    payload: dict[str, Any] = {
        "schema_version": "league-window/v1",
        "hwnd": 0x12345,
        "x": 1524,
        "y": 476,
        "w": 1500,
        "h": 900,
        "captured_at_ns": 1_700_000_000_000_000_000,
    }
    payload.update(overrides)
    return WindowGeometry(**payload)


def _synth_geom(**overrides: Any) -> WindowGeometry:
    """Synthetic simulator window (``hwnd == 0``)."""
    return _geom(hwnd=0, **overrides)


def _tolerance(**overrides: Any) -> DriftTolerance:
    payload: dict[str, Any] = {
        "schema_version": "league-window/v1",
    }
    payload.update(overrides)
    return DriftTolerance(**payload)


# ---------------------------------------------------------------------------
# Schema tests — happy paths.
# ---------------------------------------------------------------------------


def test_window_geometry_valid_full_payload() -> None:
    geom = _geom(
        process_name="RiotClientUx.exe",
        dpi_scale=1.5,
    )
    assert geom.schema_version == "league-window/v1"
    assert geom.hwnd == 0x12345
    assert geom.x == 1524
    assert geom.y == 476
    assert geom.w == 1500
    assert geom.h == 900
    assert geom.dpi_scale == 1.5
    assert geom.process_name == "RiotClientUx.exe"


def test_window_geometry_synthetic_default() -> None:
    """``hwnd=0`` is the synthetic-window sentinel; defaults are otherwise the same."""
    geom = _synth_geom()
    assert geom.hwnd == 0
    assert geom.dpi_scale == 1.0
    assert geom.process_name == ""


def test_drift_tolerance_defaults() -> None:
    tol = _tolerance()
    assert tol.max_translation_px == 8
    assert tol.max_resize_px == 4
    assert tol.max_age_ns == 2_000_000_000


def test_screen_point_valid() -> None:
    p = ScreenPoint(x=1234, y=-567)
    assert p.x == 1234
    assert p.y == -567


# ---------------------------------------------------------------------------
# Schema tests — refusals.
# ---------------------------------------------------------------------------


def test_window_geometry_refuses_zero_width() -> None:
    with pytest.raises(ValidationError):
        _geom(w=0)


def test_window_geometry_refuses_zero_height() -> None:
    with pytest.raises(ValidationError):
        _geom(h=0)


def test_window_geometry_refuses_negative_capture_time() -> None:
    with pytest.raises(ValidationError):
        _geom(captured_at_ns=-1)


def test_window_geometry_refuses_extra_fields() -> None:
    with pytest.raises(ValidationError):
        WindowGeometry(
            schema_version="league-window/v1",
            hwnd=0x1,
            x=0,
            y=0,
            w=1,
            h=1,
            captured_at_ns=0,
            rogue_field="not allowed",
        )


def test_drift_tolerance_refuses_negative_translation() -> None:
    with pytest.raises(ValidationError):
        _tolerance(max_translation_px=-1)


def test_drift_tolerance_refuses_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DriftTolerance(
            schema_version="league-window/v1",
            max_translation_px=10,
            rogue=42,
        )


def test_translation_result_refuses_outcome_point_mismatch() -> None:
    """``outcome != "TRANSLATED"`` requires a NULL ``screen_point``."""
    with pytest.raises(ValidationError):
        TranslationResult(
            schema_version="league-window/v1",
            outcome="WINDOW_MOVED",
            screen_point=ScreenPoint(x=1, y=2),
            human_reason="should not carry a point",
        )


def test_translation_result_refuses_translated_without_point() -> None:
    """``outcome == "TRANSLATED"`` requires a non-NULL ``screen_point``."""
    with pytest.raises(ValidationError):
        TranslationResult(
            schema_version="league-window/v1",
            outcome="TRANSLATED",
            screen_point=None,
            human_reason="must carry a point",
        )


# ---------------------------------------------------------------------------
# Translator — happy path.
# ---------------------------------------------------------------------------


def test_translate_no_drift_returns_pixel_inside_current_window() -> None:
    """Window did not move between capture and execution → pixel is current+normalized*size."""
    captured = _geom(captured_at_ns=1_000_000_000)
    current = _geom(captured_at_ns=1_000_000_500)  # 500 ns later, well within tolerance
    tol = _tolerance()
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        captured,
        current,
        tolerance=tol,
        now_monotonic_ns=1_000_001_000,
    )
    assert result.outcome == "TRANSLATED"
    assert result.screen_point is not None
    # pixel = (1524 + 0.5*1500, 476 + 0.5*900) = (2274, 926)
    assert result.screen_point.x == 2274
    assert result.screen_point.y == 926


def test_translate_top_left_corner() -> None:
    """``(0.0, 0.0)`` translates to the window's top-left pixel."""
    geom = _geom()
    result = translate_decision_to_screen(
        Point(x=0.0, y=0.0),
        geom,
        geom,
        tolerance=_tolerance(),
        now_monotonic_ns=geom.captured_at_ns + 100,
    )
    assert result.outcome == "TRANSLATED"
    assert result.screen_point is not None
    assert result.screen_point.x == 1524
    assert result.screen_point.y == 476


def test_translate_bottom_right_corner() -> None:
    """``(1.0, 1.0)`` translates to the window's bottom-right pixel."""
    geom = _geom()
    result = translate_decision_to_screen(
        Point(x=1.0, y=1.0),
        geom,
        geom,
        tolerance=_tolerance(),
        now_monotonic_ns=geom.captured_at_ns + 100,
    )
    assert result.outcome == "TRANSLATED"
    assert result.screen_point is not None
    assert result.screen_point.x == 1524 + 1500  # 3024
    assert result.screen_point.y == 476 + 900  # 1376


# ---------------------------------------------------------------------------
# Translator — drift refusals.
# ---------------------------------------------------------------------------


def test_translate_refuses_when_window_moved_x() -> None:
    """Window dragged 10 px right > max_translation_px=8 → WINDOW_MOVED."""
    captured = _geom(x=1524, y=476)
    current = _geom(x=1524 + 10, y=476)
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        captured,
        current,
        tolerance=_tolerance(),
        now_monotonic_ns=captured.captured_at_ns + 100,
    )
    assert result.outcome == "WINDOW_MOVED"
    assert result.screen_point is None
    assert "+10" in result.human_reason


def test_translate_refuses_when_window_moved_y() -> None:
    captured = _geom(x=1524, y=476)
    current = _geom(x=1524, y=476 + 9)  # 9 px > 8
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        captured,
        current,
        tolerance=_tolerance(),
        now_monotonic_ns=captured.captured_at_ns + 100,
    )
    assert result.outcome == "WINDOW_MOVED"
    assert result.screen_point is None


def test_translate_allows_drift_within_tolerance() -> None:
    """Window dragged 5 px right (Manhattan=5 <= 8) → translate succeeds."""
    captured = _geom(x=1524, y=476)
    current = _geom(x=1524 + 5, y=476)
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        captured,
        current,
        tolerance=_tolerance(),
        now_monotonic_ns=captured.captured_at_ns + 100,
    )
    assert result.outcome == "TRANSLATED"
    assert result.screen_point is not None
    # pixel uses current, not captured: (1529 + 750, 476 + 450) = (2279, 926)
    assert result.screen_point.x == 2279


def test_translate_refuses_when_window_resized_wider() -> None:
    captured = _geom(w=1500)
    current = _geom(w=1500 + 5)  # 5 px > max_resize_px=4
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        captured,
        current,
        tolerance=_tolerance(),
        now_monotonic_ns=captured.captured_at_ns + 100,
    )
    assert result.outcome == "WINDOW_RESIZED"
    assert result.screen_point is None


def test_translate_refuses_when_window_resized_taller() -> None:
    captured = _geom(h=900)
    current = _geom(h=900 + 10)
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        captured,
        current,
        tolerance=_tolerance(),
        now_monotonic_ns=captured.captured_at_ns + 100,
    )
    assert result.outcome == "WINDOW_RESIZED"


def test_translate_allows_resize_within_tolerance() -> None:
    captured = _geom(w=1500, h=900)
    current = _geom(w=1500 + 4, h=900 + 4)  # exactly at the limit
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        captured,
        current,
        tolerance=_tolerance(),
        now_monotonic_ns=captured.captured_at_ns + 100,
    )
    assert result.outcome == "TRANSLATED"


def test_translate_refuses_when_hwnd_changed() -> None:
    captured = _geom(hwnd=0xAAAA)
    current = _geom(hwnd=0xBBBB)
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        captured,
        current,
        tolerance=_tolerance(),
        now_monotonic_ns=captured.captured_at_ns + 100,
    )
    assert result.outcome == "HWND_CHANGED"
    assert "0xaaaa" in result.human_reason.lower() or "0xAAAA" in result.human_reason


def test_translate_refuses_when_current_geometry_is_none() -> None:
    """Tracker could not find the window (returned None) → HWND_CHANGED."""
    captured = _geom()
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        captured,
        None,
        tolerance=_tolerance(),
        now_monotonic_ns=captured.captured_at_ns + 100,
    )
    assert result.outcome == "HWND_CHANGED"
    assert result.screen_point is None


def test_translate_refuses_when_geometry_is_stale() -> None:
    captured = _geom(captured_at_ns=1_000_000_000)
    current = _geom(captured_at_ns=1_000_000_500)
    tol = _tolerance(max_age_ns=100)
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        captured,
        current,
        tolerance=tol,
        now_monotonic_ns=1_000_005_000,  # 4.5 s later — way past 100 ns
    )
    assert result.outcome == "STALE_GEOMETRY"
    assert result.screen_point is None


def test_translate_allows_fresh_geometry_at_age_limit() -> None:
    """Age exactly at the limit is allowed (the gate is ``>``, not ``>=``)."""
    captured = _geom(captured_at_ns=1_000_000_000)
    current = _geom(captured_at_ns=1_000_000_500)
    tol = _tolerance(max_age_ns=500)
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        captured,
        current,
        tolerance=tol,
        now_monotonic_ns=1_000_001_000,  # current is 500 ns old — at the limit
    )
    assert result.outcome == "TRANSLATED"


# ---------------------------------------------------------------------------
# Translator — bounds / coordinate refusals.
# ---------------------------------------------------------------------------


def test_translate_refuses_out_of_bounds_point() -> None:
    """Defence-in-depth: the translator rejects points outside [0, 1] even if a
    ``Point`` somehow made it past the schema validator (``model_construct``
    bypasses validators — defense in depth is still required)."""
    geom = _geom()
    bad_point = Point.model_construct(x=1.5, y=0.5)  # bypasses Point's le=1.0
    result = translate_decision_to_screen(
        bad_point,
        geom,
        geom,
        tolerance=_tolerance(),
        now_monotonic_ns=geom.captured_at_ns + 100,
    )
    assert result.outcome == "OUT_OF_BOUNDS"
    assert result.screen_point is None


def test_translate_refuses_nan_point_via_model_construct() -> None:
    """``NaN`` would otherwise sneak past the schema's ``Field(ge=…, le=…)`` —
    the translator's math.isfinite check catches it."""
    import math
    geom = _geom()
    nan_point = Point.model_construct(x=math.nan, y=0.5)
    result = translate_decision_to_screen(
        nan_point,
        geom,
        geom,
        tolerance=_tolerance(),
        now_monotonic_ns=geom.captured_at_ns + 100,
    )
    assert result.outcome == "OUT_OF_BOUNDS"


def test_translate_refuses_negative_normalized() -> None:
    geom = _geom()
    # ``Point`` field validator should already catch this, but the
    # translator has a defense-in-depth check too.
    with pytest.raises(ValidationError):
        Point(x=-0.1, y=0.5)


# ---------------------------------------------------------------------------
# Translator — synthetic (simulator) windows.
# ---------------------------------------------------------------------------


def test_translate_synthetic_window_no_current_geometry_refuses() -> None:
    """A synthetic window with no current geometry → STALE_GEOMETRY."""
    captured = _synth_geom(captured_at_ns=1_000_000_000)
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        captured,
        None,
        tolerance=_tolerance(),
        now_monotonic_ns=1_000_000_500,
    )
    assert result.outcome == "STALE_GEOMETRY"


def test_translate_synthetic_window_translates_via_captured_geometry() -> None:
    """A synthetic window translates using the captured geometry alone."""
    captured = _synth_geom(captured_at_ns=1_000_000_000)
    # The current geometry for a synthetic window is the same as the
    # captured — the simulator owns its own coordinate space.
    current = _synth_geom(captured_at_ns=1_000_000_500)
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        captured,
        current,
        tolerance=_tolerance(),
        now_monotonic_ns=1_000_001_000,
    )
    assert result.outcome == "TRANSLATED"
    assert result.screen_point is not None
    assert "synthetic" in result.human_reason.lower()


def test_translate_synthetic_window_skips_hwnd_check_even_when_hwnd_is_set() -> None:
    """A synthetic captured window (``hwnd=0``) ignores current.hwnd even if non-zero.

    This is the simulator-exception path: the simulator may have
    spawned a real Win32 window for input synthesis, but the
    captured-side geometry is the synthetic one. The translator does
    not compare HWNDs for synthetic captured windows.
    """
    captured = _synth_geom(captured_at_ns=1_000_000_000)
    current = _geom(hwnd=0xFFFF, captured_at_ns=1_000_000_500)  # different hwnd
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        captured,
        current,
        tolerance=_tolerance(),
        now_monotonic_ns=1_000_001_000,
    )
    assert result.outcome == "TRANSLATED"


# ---------------------------------------------------------------------------
# Translator — round-trip on a small example from the user's screenshots.
# ---------------------------------------------------------------------------


def test_translate_lol_icon_position_in_left_sidebar() -> None:
    """Reproduce the user's mockup: LoL icon at ~ (75, 185) of a 1500-wide window.

    The user shared screenshots showing the LoL launcher icon (gold 'L')
    in the Riot Client's left sidebar and the gold 'Play' button on
    the League Client. This test pins the math so the icon at ~5 % x,
    ~21 % y of a 1500x900 window maps to the expected screen pixel.
    """
    captured = _geom(x=100, y=100, w=1500, h=900)
    result = translate_decision_to_screen(
        Point(x=0.05, y=0.21),  # 5 % across, 21 % down → sidebar icon area
        captured,
        captured,
        tolerance=_tolerance(),
        now_monotonic_ns=captured.captured_at_ns + 100,
    )
    assert result.outcome == "TRANSLATED"
    assert result.screen_point is not None
    # 100 + 0.05*1500 = 175, 100 + 0.21*900 = 289
    assert result.screen_point.x == 175
    assert result.screen_point.y == 289


def test_translate_play_button_position_centered() -> None:
    """Reproduce the user's mockup: 'Play' button centered horizontally, mid-low vertically."""
    captured = _geom(x=200, y=200, w=1500, h=900)
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.66),  # center x, ~2/3 down → Play button area
        captured,
        captured,
        tolerance=_tolerance(),
        now_monotonic_ns=captured.captured_at_ns + 100,
    )
    assert result.outcome == "TRANSLATED"
    assert result.screen_point is not None
    # 200 + 0.5*1500 = 950, 200 + 0.66*900 = 794 (rounded)
    assert result.screen_point.x == 950
    assert result.screen_point.y == 794


# ---------------------------------------------------------------------------
# Translator — schema / contract guards.
# ---------------------------------------------------------------------------


def test_translate_returns_result_with_schema_version() -> None:
    geom = _geom()
    result = translate_decision_to_screen(
        Point(x=0.5, y=0.5),
        geom,
        geom,
        tolerance=_tolerance(),
        now_monotonic_ns=geom.captured_at_ns + 100,
    )
    assert result.schema_version == "league-window/v1"


def test_translate_human_reason_never_empty() -> None:
    """Every refusal path produces a non-empty human-readable reason."""
    geom = _geom()
    # Walk each one to make sure the field is populated.
    cases: list[tuple[WindowGeometry, WindowGeometry | None, DriftTolerance, int, str]] = [
        # (captured, current, tolerance, now, expected_outcome)
        (geom, _geom(x=geom.x + 100), _tolerance(), geom.captured_at_ns + 100, "WINDOW_MOVED"),
        (geom, _geom(w=geom.w + 100), _tolerance(), geom.captured_at_ns + 100, "WINDOW_RESIZED"),
        (geom, _geom(hwnd=0xBEEF), _tolerance(), geom.captured_at_ns + 100, "HWND_CHANGED"),
        (geom, None, _tolerance(), geom.captured_at_ns + 100, "HWND_CHANGED"),
        (
            geom,
            _geom(captured_at_ns=1),
            _tolerance(max_age_ns=10),
            100_000,
            "STALE_GEOMETRY",
        ),
        (geom, geom, _tolerance(), geom.captured_at_ns + 100, "TRANSLATED"),
    ]
    for captured, current, tol, now, expected in cases:
        result = translate_decision_to_screen(
            Point(x=0.5, y=0.5),
            captured,
            current,
            tolerance=tol,
            now_monotonic_ns=now,
        )
        assert result.outcome == expected
        assert len(result.human_reason) >= 1
        assert len(result.human_reason) <= 300