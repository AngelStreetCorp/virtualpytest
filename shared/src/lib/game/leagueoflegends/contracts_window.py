"""Typed contracts for window tracking and drift-aware decision translation (TASK-121 §8).

This module pins the **window-geometry contract** and the **drift-aware
decision translator** that turn the agent's normalized coordinates
(``Point`` in ``[0.0, 1.0]`` × ``[0.0, 1.0]``, relative to a captured
bitmap) into concrete screen pixels suitable for a downstream click
executor.

Why this module exists
----------------------

The Riot Client / League Client is **drifty**:

* the user drags the window around the desktop between runs;
* the taskbar / DPI may change between sessions;
* the captured frame is relative to *where the window was when the
  screenshot was taken*, but the click executor needs to know *where the
  window is now* before it sends mouse events.

A naive translation pipeline (``x_screen = x_norm * W``, ``y_screen =
y_norm * H``) breaks the moment the window moves — the executor would
click somewhere on the desktop instead of on the LoL icon, with no
diagnostic. This module makes the drift **explicit and gated**:

* ``WindowGeometry`` pins the rectangle the bitmap was captured from
  (HWND + rect + capture time);
* ``DriftTolerance`` pins the bounds the executor is willing to accept
  (``max_translation_px``, ``max_resize_px``, ``max_age_ns``);
* ``translate_decision_to_screen()`` is the pure translator: it takes
  the captured geometry + a *fresh* ``WindowTracker.query()`` result
  + tolerance, and either returns concrete ``ScreenPoint`` pixels or
  one of the structured refusal outcomes.

Hard policy (TASK-121 §6 FR-13, §8, §13)
-----------------------------------------

* The translator MUST refuse to translate if the window moved beyond
  ``DriftTolerance.max_translation_px`` between capture and execution
  (the user could have dragged the window intentionally — clicking
  blindly would land on the wrong pixel).
* The translator MUST refuse to translate if the window resized beyond
  ``DriftTolerance.max_resize_px`` (the LoL icon moved proportionally,
  and a normalized point from the old geometry no longer corresponds
  to the same physical control).
* The translator MUST refuse to translate if the geometry is older than
  ``DriftTolerance.max_age_ns`` (the world may have changed — fonts
  reflowed, a popup appeared, etc.).
* The translator MUST refuse to translate if the HWND changed (the
  previous window was closed and a new one took its place).
* The translator MUST refuse to translate if the normalized point is
  outside ``[0.0, 1.0]`` (FR-07 — the field validator on ``Point`` is
  the first gate; the translator re-checks for defense in depth).
* The schema MUST never import ``pyautogui`` or any League-process
  helper. This module is pure data + pure functions.
* ``extra='forbid'`` so the schema cannot be silently extended by an
  LLM.
* ``strict=True`` so type coercion (string→int, bool→int, …) is
  impossible.

Schema: ``league-window/v1``.

What this module is NOT
-----------------------

This module is **not** the click executor. It produces ``ScreenPoint``
pixels suitable for an executor adapter (Win32 ``SendInput``,
``pyautogui``, the simulator's event pump — all out of scope here).
The executor is a future wave; the contract here is the only thing
the runner and vision modules need to know about to plan the click.
"""
from __future__ import annotations

import math
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.src.lib.game.leagueoflegends.contracts_decision import Point


# ---------------------------------------------------------------------------
# Schema-level constants.
# ---------------------------------------------------------------------------

# The single supported schema version. Bump on breaking shape changes.
_LEAGUE_WINDOW_SCHEMA: Final = "league-window/v1"

# The five structured refusal outcomes the translator can return. Each
# maps to a single concrete failure mode the runner can react to
# (record, retry, request a fresh observation, refuse to execute).
TranslationOutcome = Literal[
    "TRANSLATED",       # success — pixels returned
    "WINDOW_MOVED",     # captured vs current delta > max_translation_px
    "WINDOW_RESIZED",   # captured vs current delta > max_resize_px
    "HWND_CHANGED",     # the source window's HWND is no longer the same
    "STALE_GEOMETRY",   # current geometry is older than max_age_ns
    "OUT_OF_BOUNDS",    # normalized point outside [0.0, 1.0]
]


# ---------------------------------------------------------------------------
# Window geometry.
# ---------------------------------------------------------------------------


class WindowGeometry(BaseModel):
    """The rectangle (and provenance) of a captured window.

    Schema: ``league-window/v1`` (shared schema with the translator).

    Field rationale:

    * ``hwnd`` is the Win32 window handle the bitmap was captured from
      (or 0 for a synthetic simulator target — see ``hwnd==0`` field).
    * ``x``, ``y``, ``w``, ``h`` describe the rectangle in **virtual
      screen coordinates** (the OS's primary desktop coordinate space,
      pre-DPI scaling). This is the coordinate system Win32
      ``GetWindowRect`` and ``SetCursorPos`` use.
    * ``captured_at_ns`` is the monotonic clock reading when the
      bitmap was captured. Combined with ``DriftTolerance.max_age_ns``
      it gates the staleness check.
    * ``dpi_scale`` is the window's per-monitor DPI scale (1.0 = 100 %
      DPI). Captured for traceability — the translator does not scale
      anything itself, but a downstream click executor may need to
      un-scale cursor coordinates on high-DPI displays.
    * ``process_name`` is the executable basename the window belongs to
      (e.g. ``"RiotClientUx.exe"``). Best-effort, for audit logs; the
      translator does not validate it (validation lives at the source
      of the bitmap — :mod:`contracts_simulator` and the runtime
      window tracker).

    Hard policy:

    * ``hwnd=0`` is reserved for synthetic simulator targets (a fake
      window for the custom-moba / community-sim targets). The
      translator treats ``hwnd=0`` as "synthetic — drift checks skipped
      except for the staleness check".
    * ``w`` and ``h`` MUST be > 0 (a degenerate rectangle cannot host
      a click target).
    * ``captured_at_ns`` MUST be >= 0.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["league-window/v1"]
    hwnd: int = Field(ge=0)
    x: int
    y: int
    w: int = Field(gt=0)
    h: int = Field(gt=0)
    captured_at_ns: int = Field(ge=0)
    dpi_scale: float = Field(default=1.0, ge=0.1, le=10.0)
    process_name: str = Field(default="", min_length=0, max_length=260)

    @field_validator("x", "y")
    @classmethod
    def _coord_finite_check(cls, v: int) -> int:
        # ``int`` is finite by construction — the guard exists only to
        # make the validator stack match the rest of the contracts
        # and to give a single source of truth if a future schema
        # moves to a numeric union.
        if not math.isfinite(float(v)):
            raise ValueError("coordinate must be a finite number")
        return v


# ---------------------------------------------------------------------------
# Drift tolerance.
# ---------------------------------------------------------------------------


class DriftTolerance(BaseModel):
    """The bounds the translator accepts between capture and execution.

    Schema: ``league-window/v1`` (shared schema).

    The runner / operator configures this once per session. The
    translator consults it on every translation. Defaults are tuned
    for the Riot Client UI (small fonts, single-monitor desktops);
    high-DPI / multi-monitor sessions may want looser bounds.

    Field rationale:

    * ``max_translation_px``: the maximum acceptable Manhattan (x + y)
      distance between the captured and current window top-left.
      Default 8 px — a window dragged by a single click can easily
      move 2-3 px before the drag completes; > 8 px is "the user
      moved it on purpose".
    * ``max_resize_px``: the maximum acceptable per-axis resize
      delta. Default 4 px — Riot Client UI is not normally resized
      while playing; any resize is suspicious.
    * ``max_age_ns``: the maximum acceptable age (current monotonic
      clock minus ``WindowGeometry.captured_at_ns``). Default 2
      seconds — fast enough for interactive play, slow enough to
      survive a single dropped frame.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["league-window/v1"]
    max_translation_px: int = Field(default=8, ge=0, le=10_000)
    max_resize_px: int = Field(default=4, ge=0, le=10_000)
    max_age_ns: int = Field(default=2_000_000_000, ge=0, le=600_000_000_000)

    @field_validator("max_translation_px", "max_resize_px", "max_age_ns")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        # ``Field(ge=0)`` covers this; the validator is here only as
        # defense in depth in case a future change relaxes the bound.
        if v < 0:
            raise ValueError("tolerance values must be non-negative")
        return v


# ---------------------------------------------------------------------------
# Translation result.
# ---------------------------------------------------------------------------


class ScreenPoint(BaseModel):
    """A concrete pixel coordinate on the desktop.

    Schema: ``league-window/v1`` (shared schema).

    Distinct from :class:`contracts_decision.Point` (which is
    normalized ``[0.0, 1.0]``). This is the *output* of the
    translator — the input a click executor needs.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    x: int = Field(ge=-32_768, le=32_767)
    y: int = Field(ge=-32_768, le=32_767)

    @field_validator("x", "y")
    @classmethod
    def _coord_finite_check(cls, v: int) -> int:
        if not math.isfinite(float(v)):
            raise ValueError("coordinate must be a finite number")
        return v


class TranslationResult(BaseModel):
    """The translator's output: either a translated pixel pair or a structured refusal.

    Schema: ``league-window/v1``.

    ``outcome`` is the single machine-readable verdict. ``screen_point``
    is non-NULL iff ``outcome == "TRANSLATED"``. ``human_reason`` is the
    operator-readable explanation (1..300 chars).
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["league-window/v1"]
    outcome: TranslationOutcome
    screen_point: ScreenPoint | None = None
    human_reason: str = Field(min_length=1, max_length=300)

    @field_validator("screen_point")
    @classmethod
    def _point_matches_outcome(cls, v: ScreenPoint | None, info) -> ScreenPoint | None:
        # Defense in depth: the runner only consults ``screen_point``
        # when ``outcome == "TRANSLATED"``. Catching the inconsistency
        # at the schema layer keeps downstream consumers from
        # accidentally reading a stale pixel pair.
        outcome = info.data.get("outcome")
        if outcome == "TRANSLATED" and v is None:
            raise ValueError("TRANSLATED requires a non-null screen_point")
        if outcome != "TRANSLATED" and v is not None:
            raise ValueError(
                f"non-TRANSLATED outcome {outcome!r} must have a null screen_point"
            )
        return v


# ---------------------------------------------------------------------------
# Pure translator.
# ---------------------------------------------------------------------------


def translate_decision_to_screen(
    normalized: Point,
    captured: WindowGeometry,
    current: WindowGeometry | None,
    *,
    tolerance: DriftTolerance,
    now_monotonic_ns: int,
    screenshot_extent: Optional[WindowGeometry] = None,
) -> TranslationResult:
    """Translate a normalized ``Point`` (captured-relative) into desktop pixels.

    The function is **pure** — no I/O, no clock reads inside (the
    caller supplies ``now_monotonic_ns``), no League-process helpers,
    no ``pyautogui``. The runner can call it deterministically in
    tests.

    Args:
        normalized: the agent's click target, in ``[0.0, 1.0]``
            relative to the captured bitmap.
        captured: the ``WindowGeometry`` the bitmap was captured from.
            This is the geometry the normalized point is interpreted
            against.
        current: a fresh ``WindowGeometry`` for the same window,
            typically the result of ``WindowTracker.query(hwnd)`` taken
            just before execution. ``None`` means "the tracker could
            not find the window" → ``HWND_CHANGED`` (or
            ``MISSING_GEOMETRY`` if the captured window never had an
            HWND either, i.e. was synthetic).
        tolerance: the drift bounds. The translator uses its
            ``max_translation_px``, ``max_resize_px``, ``max_age_ns``.
        now_monotonic_ns: the monotonic clock reading at execution
            time, used for the staleness check.
        screenshot_extent: optional ``WindowGeometry`` describing the
            pixel dimensions of the screenshot bitmap. When provided,
            the normalized point is interpreted relative to this
            extent (not to ``captured``). This is used by the phase-0
            orchestrator, which captures the full desktop and then
            converts the detector's hit (normalized to the screenshot)
            directly to desktop pixels.

    Returns:
        A :class:`TranslationResult`. On success, ``outcome ==
        "TRANSLATED"`` and ``screen_point`` is the desktop pixel
        coordinate of the click target. On any refusal, ``outcome`` is
        one of the four refusal literals and ``screen_point`` is
        ``None``.

    Drift semantics:

    * If ``captured.hwnd == 0`` (synthetic simulator window): only the
      staleness check applies — the captured-vs-current translation /
      resize / hwnd-changed checks are skipped, on the assumption
      that the simulator owns its own coordinate space and the tracker
      is not relevant.
    * If ``captured.hwnd != 0`` (real or windowed simulator): all four
      checks apply.
    * The translation ``(dx, dy)`` is computed as
      ``current.x - captured.x`` and ``current.y - captured.y``.
      ``WINDOW_MOVED`` triggers when ``|dx| + |dy|`` exceeds
      ``max_translation_px``.
    * ``WINDOW_RESIZED`` triggers when ``|current.w - captured.w|`` or
      ``|current.h - captured.h|`` exceeds ``max_resize_px``.
    * ``HWND_CHANGED`` triggers when ``current.hwnd != captured.hwnd``
      (and both are non-zero).
    * ``STALE_GEOMETRY`` triggers when ``current.captured_at_ns`` is
      older than ``tolerance.max_age_ns`` relative to ``now_monotonic_ns``.
    """
    # ---- 1. Validate the normalized point (defense in depth). -------
    if (
        math.isnan(normalized.x)
        or math.isnan(normalized.y)
        or not (0.0 <= normalized.x <= 1.0)
        or not (0.0 <= normalized.y <= 1.0)
    ):
        return TranslationResult(
            schema_version=_LEAGUE_WINDOW_SCHEMA,
            outcome="OUT_OF_BOUNDS",
            screen_point=None,
            human_reason=(
                f"normalized point ({normalized.x:.4f}, {normalized.y:.4f}) "
                f"is outside [0.0, 1.0] or non-finite"
            ),
        )

    # ---- 2. Handle synthetic captured windows (hwnd == 0). ----------
    if captured.hwnd == 0:
        # Synthetic simulator windows have no real desktop position.
        # The only check we apply is staleness: refuse if the geometry
        # is too old, even for a synthetic window.
        age_ns = now_monotonic_ns - current.captured_at_ns if current else 0
        if current is None or age_ns > tolerance.max_age_ns:
            return TranslationResult(
                schema_version=_LEAGUE_WINDOW_SCHEMA,
                outcome="STALE_GEOMETRY",
                screen_point=None,
                human_reason=(
                    f"synthetic captured window has no current geometry "
                    f"(or it is {age_ns} ns old, > max_age_ns="
                    f"{tolerance.max_age_ns})"
                ),
            )
        # Translate using the captured geometry alone (no drift check
        # against a real desktop position).
        sx = int(round(captured.x + normalized.x * captured.w))
        sy = int(round(captured.y + normalized.y * captured.h))
        return TranslationResult(
            schema_version=_LEAGUE_WINDOW_SCHEMA,
            outcome="TRANSLATED",
            screen_point=ScreenPoint(x=sx, y=sy),
            human_reason=(
                f"translated (synthetic) normalized ({normalized.x:.4f}, "
                f"{normalized.y:.4f}) against captured "
                f"({captured.x},{captured.y},{captured.w}x{captured.h}) "
                f"to pixel ({sx},{sy})"
            ),
        )

    # ---- 3. Real / windowed simulator — check the tracker. ---------
    if current is None:
        return TranslationResult(
            schema_version=_LEAGUE_WINDOW_SCHEMA,
            outcome="HWND_CHANGED",
            screen_point=None,
            human_reason=(
                f"the captured window (HWND={captured.hwnd:#x}) is no "
                f"longer present on the desktop — refused to translate"
            ),
        )

    if current.hwnd != captured.hwnd:
        return TranslationResult(
            schema_version=_LEAGUE_WINDOW_SCHEMA,
            outcome="HWND_CHANGED",
            screen_point=None,
            human_reason=(
                f"the current window (HWND={current.hwnd:#x}) is not "
                f"the captured one (HWND={captured.hwnd:#x}) — refused"
            ),
        )

    # ---- 4. Staleness check (geometry capture timestamp). ----------
    age_ns = now_monotonic_ns - current.captured_at_ns
    if age_ns > tolerance.max_age_ns:
        return TranslationResult(
            schema_version=_LEAGUE_WINDOW_SCHEMA,
            outcome="STALE_GEOMETRY",
            screen_point=None,
            human_reason=(
                f"current geometry is {age_ns} ns old, exceeds "
                f"max_age_ns={tolerance.max_age_ns}"
            ),
        )

    # ---- 5. Translation check (window moved on the desktop). -------
    dx = current.x - captured.x
    dy = current.y - captured.y
    manhattan = abs(dx) + abs(dy)
    if manhattan > tolerance.max_translation_px:
        return TranslationResult(
            schema_version=_LEAGUE_WINDOW_SCHEMA,
            outcome="WINDOW_MOVED",
            screen_point=None,
            human_reason=(
                f"window moved by ({dx:+d}, {dy:+d}) px, Manhattan="
                f"{manhattan} > max_translation_px={tolerance.max_translation_px}"
            ),
        )

    # ---- 6. Resize check (window grew / shrunk). -------------------
    dw = current.w - captured.w
    dh = current.h - captured.h
    if abs(dw) > tolerance.max_resize_px or abs(dh) > tolerance.max_resize_px:
        return TranslationResult(
            schema_version=_LEAGUE_WINDOW_SCHEMA,
            outcome="WINDOW_RESIZED",
            screen_point=None,
            human_reason=(
                f"window resized by ({dw:+d}, {dh:+d}) px, exceeds "
                f"max_resize_px={tolerance.max_resize_px}"
            ),
        )

    # ---- 7. All checks passed — translate. -------------------------
    if screenshot_extent is not None:
        # The normalized point is relative to the screenshot bitmap, not
        # to the window. Translate against the screenshot's pixel
        # extent (typically anchored at 0,0 of the desktop for a
        # whole-screen capture).
        sx = int(round(screenshot_extent.x + normalized.x * screenshot_extent.w))
        sy = int(round(screenshot_extent.y + normalized.y * screenshot_extent.h))
    else:
        sx = int(round(current.x + normalized.x * current.w))
        sy = int(round(current.y + normalized.y * current.h))
    return TranslationResult(
        schema_version=_LEAGUE_WINDOW_SCHEMA,
        outcome="TRANSLATED",
        screen_point=ScreenPoint(x=sx, y=sy),
        human_reason=(
            f"translated normalized ({normalized.x:.4f}, {normalized.y:.4f}) "
            f"against captured ({captured.x},{captured.y},"
            f"{captured.w}x{captured.h}) + drift ({dx:+d},{dy:+d}) to "
            f"pixel ({sx},{sy})"
        ),
    )


__all__ = [
    "TranslationOutcome",
    "WindowGeometry",
    "DriftTolerance",
    "ScreenPoint",
    "TranslationResult",
    "translate_decision_to_screen",
]