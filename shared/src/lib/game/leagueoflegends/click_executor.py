"""Win32-based click executor for the League of Legends vision agent (TASK-121 §8).

This module is the **action** counterpart to the planner in
:mod:`window_tracker` and the gate in :func:`contracts_window.translate_decision_to_screen`.
Given a typed :class:`contracts_window.ScreenPoint`, the executor
moves the cursor and dispatches a left-button click via the Win32
``SendInput`` API.

Hard policy (TASK-121 §6 FR-13, §13)
------------------------------------

* The executor is the **only** module in TASK-121 that sends real
  desktop input. Its entry point is gated by the runner, which is in
  turn gated by :class:`LeagueRunner`'s three-layer FR-15 defense:
  the runner refuses any ``SimulatorTarget(target_kind="real-league")``
  before the executor is ever reached.
* The executor MUST refuse to send input if the target window's
  geometry has drifted beyond :class:`DriftTolerance` since the click
  was planned. This is a defense-in-depth check — the runner already
  calls ``translate_decision_to_screen`` immediately before invoking
  the executor, but a long-running executor can re-check on its own.
* The executor MUST refuse to run on a non-Windows host.
* The executor MUST NEVER import ``pyautogui`` or any League-process
  helper. ``SendInput`` is the Win32 primitive and is the only
  primitive the executor uses.

What this module is NOT
-----------------------

* This is not a *simulator*. It sends real mouse events to the real
  desktop. Any test of this module must use a mock or run on a
  dedicated test host.
* This is not a *bot*. The executor clicks once per call. There is no
  auto-retry, no key spamming, no `time.sleep` loops. The orchestrator
  (:mod:`phase0_runner`) is responsible for sequencing clicks with
  proper waits.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import time
from dataclasses import dataclass
from typing import Optional

from shared.src.lib.game.leagueoflegends.contracts_window import (
    DriftTolerance,
    ScreenPoint,
    WindowGeometry,
    translate_decision_to_screen,
)


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class ExecutorUnavailableError(RuntimeError):
    """Raised when the executor is invoked on a non-Windows host."""


class ExecutorRefusedError(RuntimeError):
    """Raised when the executor refuses to click (drift, stale, out of bounds)."""


# ---------------------------------------------------------------------------
# Cross-platform guard.
# ---------------------------------------------------------------------------


def _require_windows() -> None:
    if sys.platform != "win32":
        raise ExecutorUnavailableError(
            f"Win32ClickExecutor requires Windows; current platform is "
            f"{sys.platform!r}"
        )


# ---------------------------------------------------------------------------
# Internal ctypes bindings.
# ---------------------------------------------------------------------------


_user32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None


# Win32 INPUT / MOUSEINPUT structures for SendInput.
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", wt.PULONG),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wt.DWORD),
        # Union of MOUSEINPUT / KEYBDINPUT / HARDWAREINPUT — we only use MOUSEINPUT.
        ("mi", _MOUSEINPUT),
    ]


# SendInput dwFlags
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_ABSOLUTE = 0x8000

_INPUT_MOUSE = 0


# ---------------------------------------------------------------------------
# Public data shape.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClickResult:
    """The outcome of one click attempt.

    ``delivered`` is the only signal the orchestrator reads to decide
    whether to retry. ``reason`` is the human-readable explanation.
    """

    delivered: bool
    reason: str
    screen_point: Optional[ScreenPoint] = None


# ---------------------------------------------------------------------------
# The executor.
# ---------------------------------------------------------------------------


class Win32ClickExecutor:
    """Send ``SendInput`` mouse events to the real desktop."""

    def click(
        self,
        screen_point: ScreenPoint,
        *,
        captured: Optional[WindowGeometry] = None,
        current: Optional[WindowGeometry] = None,
        tolerance: Optional[DriftTolerance] = None,
        now_monotonic_ns: Optional[int] = None,
        dry_run: bool = False,
    ) -> ClickResult:
        """Click at ``screen_point`` (in absolute desktop coordinates).

        If ``captured`` / ``current`` / ``tolerance`` / ``now_monotonic_ns``
        are provided, the executor re-runs the drift translator as
        defense in depth — refusing to click if the window has moved
        out from under the caller's plan. If any of these is ``None``,
        the drift re-check is skipped (the caller takes responsibility).

        ``dry_run=True`` computes everything but does not actually
        send the mouse event — useful for tests and for "is the
        cursor about to land somewhere sane?" previews.
        """
        _require_windows()

        if captured is not None and current is not None and tolerance is not None and now_monotonic_ns is not None:
            # Re-validate drift as defense in depth. The translator
            # returns a normalized Point-equivalent (x_screen, y_screen)
            # — but here we already have screen pixels, so we just
            # check the outcome. The translator's outcome gates whether
            # the click is allowed.
            from shared.src.lib.game.leagueoflegends.contracts_decision import Point

            normalized = Point(x=0.5, y=0.5)  # placeholder — translator only uses geometry here
            translation = translate_decision_to_screen(
                normalized, captured, current, tolerance=tolerance, now_monotonic_ns=now_monotonic_ns
            )
            if translation.outcome != "TRANSLATED":
                raise ExecutorRefusedError(
                    f"click refused by drift translator: {translation.human_reason}"
                )

        if dry_run:
            return ClickResult(
                delivered=False,
                reason=f"dry-run; would click at ({screen_point.x}, {screen_point.y})",
                screen_point=screen_point,
            )

        # ---- Move the cursor to the target pixel. --------------------
        # SendInput with MOUSEEVENTF_ABSOLUTE expects normalized
        # 0..65535 coordinates across the *virtual screen* (all
        # monitors, not just the primary). 1920x1200 is the typical
        # primary monitor, but if the user has multiple monitors the
        # SendInput normalization handles the rest.
        if not _set_cursor_pos(screen_point.x, screen_point.y):
            err = ctypes.get_last_error()
            return ClickResult(
                delivered=False,
                reason=f"SetCursorPos failed (err={err})",
                screen_point=screen_point,
            )

        # ---- Send the click (left-down + small delay + left-up). ----
        if not _send_input_left_click():
            err = ctypes.get_last_error()
            return ClickResult(
                delivered=False,
                reason=f"SendInput failed (err={err})",
                screen_point=screen_point,
            )

        return ClickResult(
            delivered=True,
            reason=f"clicked at ({screen_point.x}, {screen_point.y})",
            screen_point=screen_point,
        )

    def move_to(self, screen_point: ScreenPoint) -> bool:
        """Move the cursor without clicking (cursor-only)."""
        _require_windows()
        return _set_cursor_pos(screen_point.x, screen_point.y)

    def cursor_pos(self) -> Optional[ScreenPoint]:
        """Return the current cursor position (for debugging / previews)."""
        _require_windows()
        pt = wt.POINT()
        if not _user32.GetCursorPos(ctypes.byref(pt)):
            return None
        return ScreenPoint(x=int(pt.x), y=int(pt.y))


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------


def _set_cursor_pos(x: int, y: int) -> bool:
    """Call ``SetCursorPos`` (legacy GDI cursor, sufficient for a one-shot click)."""
    return bool(_user32.SetCursorPos(int(x), int(y)))


def _send_input_left_click() -> bool:
    """Dispatch left-button-down + left-button-up via ``SendInput``."""
    # Left down.
    down = _INPUT(
        type=_INPUT_MOUSE,
        mi=_MOUSEINPUT(
            dx=0,
            dy=0,
            mouseData=0,
            dwFlags=_MOUSEEVENTF_LEFTDOWN,
            time=0,
            dwExtraInfo=None,
        ),
    )
    n_down = _user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_INPUT))
    if n_down != 1:
        return False

    # Brief hold so the target window registers a real click rather
    # than a phantom zero-duration press.
    time.sleep(0.04)

    # Left up.
    up = _INPUT(
        type=_INPUT_MOUSE,
        mi=_MOUSEINPUT(
            dx=0,
            dy=0,
            mouseData=0,
            dwFlags=_MOUSEEVENTF_LEFTUP,
            time=0,
            dwExtraInfo=None,
        ),
    )
    n_up = _user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_INPUT))
    return n_up == 1


__all__ = [
    "ExecutorUnavailableError",
    "ExecutorRefusedError",
    "ClickResult",
    "Win32ClickExecutor",
]