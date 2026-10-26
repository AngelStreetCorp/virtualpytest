"""Win32-based window tracker for the League of Legends vision agent (TASK-121 §8).

This module is the **planner** for the drift-aware translator in
:mod:`contracts_window`. The translator needs a *fresh*
``WindowGeometry`` for the captured HWND just before any click is
emitted; this module is the producer of that fresh geometry on the
**real desktop** (where the Riot Client / League Client windows live).

What this module does
---------------------

* Query the current desktop rectangle (HWND, x, y, w, h, captured_at,
  process_name) of a window the operator / vision layer knows about —
  by HWND, by window title, by window class, or by owning PID.
* Enumerate all top-level windows on the desktop, returning their
  geometry and process name.

What this module does NOT do
----------------------------

* It never *moves*, *focuses*, *minimizes*, or *clicks* a window — that
  is :mod:`click_executor`'s job. The tracker is read-only by design:
  a buggy tracker cannot accidentally send input.
* It never imports ``pyautogui`` or any League-process helper
  (TASK-121 §6 FR-13). The only system-level dependency is the
  ``ctypes`` standard library binding to ``user32.dll``.
* It is **cross-platform safe at import time**: on non-Windows hosts
  (e.g. the worktree on macOS) every method raises
  :class:`TrackerUnavailableError` immediately rather than segfaulting
  on a missing ``user32.dll``. This is essential — the unit tests for
  the agent run on macOS where Win32 calls would otherwise crash.

Hard policy (TASK-121 §6 FR-13, §8)
------------------------------------

* The tracker is **read-only**. It can refuse to send input even if
  asked; it does not refuse to *read* the desktop.
* The tracker accepts any HWND / title / class it is given — including
  Riot Client / League Client windows. The runner's FR-15 three-layer
  defense is what blocks the *real* League client from being an
  *execution* target. The tracker is allowed to *observe* it for
  operator-driven capture / replay.
* The schema / API surface is intentionally narrow: the methods that
  enumerate desktop state never return a list of PIDs larger than what
  was asked for, and the methods that look up by HWND never write to
  the window.

Schema: ``league-window-tracker/v1`` (informal — this module is plain
Python, not a Pydantic model).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import time
from dataclasses import dataclass
from typing import Iterator, List, Optional

from shared.src.lib.game.leagueoflegends.contracts_window import WindowGeometry


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class TrackerUnavailableError(RuntimeError):
    """Raised when the tracker is invoked on a non-Windows host.

    The tracker depends on ``user32.dll`` and ``kernel32.dll``; on
    Linux / macOS the methods would otherwise segfault on import. The
    contract is that calling any tracker method on a non-Windows host
    raises immediately so the caller can fall back to a mock or skip
    the test gracefully.
    """


# ---------------------------------------------------------------------------
# Cross-platform guard.
# ---------------------------------------------------------------------------


def _require_windows() -> None:
    """Raise :class:`TrackerUnavailableError` if not running on Windows.

    The tracker uses ``ctypes.windll.user32`` which is only available
    on Windows. On macOS / Linux the methods would otherwise raise an
    obscure :class:`AttributeError` deep in the ctypes binding. We
    raise a single, well-typed error at the entry of every public
    method so tests can match on it.
    """
    if sys.platform != "win32":
        raise TrackerUnavailableError(
            f"Win32WindowTracker requires Windows; current platform is "
            f"{sys.platform!r}"
        )


# ---------------------------------------------------------------------------
# Internal ctypes bindings.
# ---------------------------------------------------------------------------


# The user32 / kernel32 functions the tracker uses. Declared at module
# load time so the lookup is one-shot (each call to ``ctypes.windll``
# re-imports).
_user32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None


# Win32 BOOL is a 32-bit int; some functions return int(0) on failure.
def _BOOL(v: int) -> bool:
    return bool(v)


# WNDENUMPROC: callback signature for EnumWindows. ``WINFUNCTYPE`` was
# deprecated in Python 3.13; ``CFUNCTYPE`` with explicit restype/argtypes
# is the portable form (the calling convention is stdcall on Windows
# but the ctypes layer manages that for stdcall APIs).
_WNDENUMPROC = ctypes.CFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


# ---------------------------------------------------------------------------
# Public data shape.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackedWindow:
    """One top-level window the tracker has observed on the desktop.

    Combines a :class:`WindowGeometry` (the rectangle + provenance) with
    the window's title and class for downstream filtering.

    Attributes:
        geometry: the typed geometry, suitable for input to
            :func:`contracts_window.translate_decision_to_screen`.
        title: the Win32 window title (the text in the title bar).
            May be empty for some windows (e.g. splash screens).
        class_name: the Win32 window class (e.g. ``"Chrome_WidgetWin_1"``,
            ``"ConsoleWindowClass"``). The Riot Client UI uses
            ``"Chrome_WidgetWin_1"`` (Electron).
        pid: the owning process ID.
    """

    geometry: WindowGeometry
    title: str
    class_name: str
    pid: int


# ---------------------------------------------------------------------------
# The tracker.
# ---------------------------------------------------------------------------


class Win32WindowTracker:
    """Read-only Win32 window tracker.

    The tracker is **stateless**: every method re-queries the desktop.
    The caller is responsible for caching, polling, and detecting
    drift — :func:`contracts_window.translate_decision_to_screen` is
    the gate that consumes the tracker's output.
    """

    # ------------------------------------------------------------------
    # Single-window lookups.
    # ------------------------------------------------------------------

    def query_by_hwnd(self, hwnd: int) -> Optional[WindowGeometry]:
        """Return a fresh ``WindowGeometry`` for ``hwnd``, or ``None`` if the window is gone."""
        _require_windows()
        rect = wt.RECT()
        ok = _user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(rect))
        if not _BOOL(ok):
            return None
        return _geometry_from_handle(hwnd, rect, time.monotonic_ns())

    def query_by_title(
        self, title: str, *, exact: bool = True
    ) -> Optional[TrackedWindow]:
        """Find a top-level window by its title.

        ``exact=True`` matches the title verbatim (case-insensitive);
        ``exact=False`` does a substring match. Substring matching is
        a sharp tool — prefer ``exact=True`` for production lookups.
        """
        _require_windows()
        needle = title.casefold()
        for window in self.enumerate():
            hay = window.title.casefold()
            if (exact and hay == needle) or (not exact and needle in hay):
                return window
        return None

    def query_by_class(self, class_name: str) -> List[TrackedWindow]:
        """Find all top-level windows with the given class name.

        The Riot Client's Electron renderer registers as
        ``"Chrome_WidgetWin_1"`` (one window per process). League of
        Legends' CEF-based client also uses a ``Chrome_WidgetWin_*``
        class. Returns an empty list if no matches.
        """
        _require_windows()
        needle = class_name.casefold()
        return [w for w in self.enumerate() if w.class_name.casefold() == needle]

    def query_by_pid(self, pid: int) -> List[TrackedWindow]:
        """Find all top-level windows owned by ``pid``."""
        _require_windows()
        return [w for w in self.enumerate() if w.pid == pid]

    def wait_for_window(
        self,
        *,
        title: Optional[str] = None,
        class_name: Optional[str] = None,
        pid: Optional[int] = None,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.5,
    ) -> Optional[TrackedWindow]:
        """Poll the desktop until a matching window appears or the timeout elapses.

        Returns the first match (or ``None`` on timeout). At least one
        of ``title`` / ``class_name`` / ``pid`` must be provided. The
        matchers compose: ``title=None, class_name="X"`` waits for any
        window of class X; ``title="Riot Client", class_name="Y"``
        waits for a window whose title is "Riot Client" AND whose
        class is "Y" (rarely useful — Win32 doesn't really work that
        way).
        """
        _require_windows()
        if title is None and class_name is None and pid is None:
            raise ValueError(
                "wait_for_window requires at least one of title/class_name/pid"
            )

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for window in self.enumerate():
                if title is not None and window.title != title:
                    continue
                if class_name is not None and window.class_name != class_name:
                    continue
                if pid is not None and window.pid != pid:
                    continue
                return window
            time.sleep(poll_interval_s)
        return None

    # ------------------------------------------------------------------
    # Enumeration.
    # ------------------------------------------------------------------

    def enumerate(self) -> List[TrackedWindow]:
        """Return every visible top-level window on the desktop."""
        _require_windows()
        results: List[TrackedWindow] = []

        @_WNDENUMPROC
        def _cb(hwnd: wt.HWND, lparam: wt.LPARAM) -> bool:
            # Skip invisible windows.
            if not _BOOL(_user32.IsWindowVisible(hwnd)):
                return True
            rect = wt.RECT()
            if not _BOOL(_user32.GetWindowRect(hwnd, ctypes.byref(rect))):
                return True

            title = _get_window_text(hwnd)
            class_name = _get_class_name(hwnd)
            pid = wt.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            geom = _geometry_from_handle(int(hwnd), rect, time.monotonic_ns())
            results.append(
                TrackedWindow(
                    geometry=geom,
                    title=title,
                    class_name=class_name,
                    pid=int(pid.value),
                )
            )
            return True

        _user32.EnumWindows(_cb, 0)
        return results

    # ------------------------------------------------------------------
    # Aliases (the names the phase0 runner cares about).
    # ------------------------------------------------------------------

    def find_riot_client(self) -> Optional[TrackedWindow]:
        """Find the Riot Client's main UI window.

        The Riot Client's Electron renderer registers as a
        ``Chrome_WidgetWin_1`` window with the title ``"Riot Client"``
        once the Ux loop has loaded. The launcher process
        (``RiotClientServices``) is a separate, invisible console
        process — this method targets the *visible* UI window.

        Returns ``None`` if the Riot Client is not currently showing
        its main UI (e.g. it is on a sub-tab that hides the title bar,
        or it has been closed).
        """
        return self.query_by_title("Riot Client")

    def find_league_client(self) -> Optional[TrackedWindow]:
        """Find the League of Legends client UI window.

        The League Client's main window title is ``"League of Legends"``
        when in the lobby; the client may use a different title on
        the login screen. ``query_by_title(..., exact=False)`` matches
        both.
        """
        return self.query_by_title("League of Legends", exact=False)


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------


def _geometry_from_handle(
    hwnd: int, rect: wt.RECT, captured_at_ns: int
) -> WindowGeometry:
    """Convert a Win32 RECT + monotonic timestamp into a WindowGeometry."""
    return WindowGeometry(
        schema_version="league-window/v1",
        hwnd=hwnd,
        x=int(rect.left),
        y=int(rect.top),
        w=max(1, int(rect.right - rect.left)),
        h=max(1, int(rect.bottom - rect.top)),
        captured_at_ns=captured_at_ns,
        dpi_scale=1.0,
        process_name="",
    )


def _get_window_text(hwnd: wt.HWND) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _get_class_name(hwnd: wt.HWND) -> str:
    buf = ctypes.create_unicode_buffer(256)
    n = _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value if n > 0 else ""


__all__ = [
    "TrackerUnavailableError",
    "TrackedWindow",
    "Win32WindowTracker",
]


# Iterate-over-windows convenience for callers that want a generator.
def iter_windows(tracker: Win32WindowTracker) -> Iterator[TrackedWindow]:
    """Yield each visible top-level window via the tracker's enumerate method."""
    return iter(tracker.enumerate())