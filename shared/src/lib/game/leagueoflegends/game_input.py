"""TASK-132: in-game input for the Garen bot, behind one guard.

Authority (owner, 2026-10-18; TASK-121 FR-15 / section 13): bot input on the real client is allowed only in a Practice Tool
game (queue 3140) on ``vpt-windows``. Every call here first runs :class:`PracticeGuard`: ``League of Legends.exe`` must be
running AND the Live Client Data API must report ``gameMode == "PRACTICETOOL"``; otherwise :class:`InputRefused` is raised
and nothing is sent. Keys are sent as hardware scan codes (physical key positions), so a French AZERTY layout, where
Q/W/E/R are labelled A/Z/E/R, works unchanged.
"""

from __future__ import annotations

import ctypes
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

GAMESTATS_URL = "https://127.0.0.1:2999/liveclientdata/gamestats"

# Physical keys as PS/2 set-1 scan codes (position, not label).
SCAN = {
    "Q": 0x10, "W": 0x11, "E": 0x12, "R": 0x13, "Y": 0x15, "P": 0x19,
    "D": 0x20, "F": 0x21, "B": 0x30,
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07, "7": 0x08,
    "SPACE": 0x39, "ESC": 0x01, "CTRL": 0x1D, "L": 0x26, "ENTER": 0x1C,
}


class InputRefused(RuntimeError):
    """Input was refused because the game is not a Practice Tool game."""


class PracticeGuard:
    """True only while a PRACTICETOOL game is running. Cached for ``ttl_s`` seconds."""

    def __init__(
        self,
        game_mode_fn: Optional[Callable[[], Optional[str]]] = None,
        running_fn: Optional[Callable[[], bool]] = None,
        ttl_s: float = 1.0,
        foreground_fn: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._mode = game_mode_fn or _live_game_mode
        self._running = running_fn or _game_running
        self._foreground = foreground_fn or _game_in_foreground
        self._ttl = ttl_s
        self._checked_at = -1e9
        self._ok = False

    def check_game_only(self) -> None:
        """Like :meth:`check` but without the foreground test (used to bring the window forward)."""
        if not (bool(self._running()) and self._mode() == "PRACTICETOOL"):
            raise InputRefused("game is not a running PRACTICETOOL game: input refused")

    def check(self) -> None:
        now = time.monotonic()
        if now - self._checked_at >= self._ttl:
            self._ok = bool(self._running()) and self._mode() == "PRACTICETOOL"
            self._checked_at = now
        if not self._ok:
            raise InputRefused("game is not a running PRACTICETOOL game: input refused")
        if not self._foreground():
            raise InputRefused("the game window is not in the foreground: input refused")


def _live_game_mode() -> Optional[str]:
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(GAMESTATS_URL, context=ctx, timeout=3) as r:
            return json.loads(r.read().decode()).get("gameMode")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _game_running() -> bool:
    from .process_utils import is_running

    return is_running("League of Legends.exe")


def _game_in_foreground() -> bool:
    """True when the League game window is the foreground window; tries to bring it forward once. Always True off Windows."""
    if sys.platform != "win32":
        return True
    u = ctypes.windll.user32
    hwnd = u.FindWindowW(None, "League of Legends (TM) Client")
    if not hwnd:
        return False
    if u.GetForegroundWindow() == hwnd:
        return True
    u.keybd_event(0x12, 0, 0, 0)  # a tap of Alt lets SetForegroundWindow through
    u.keybd_event(0x12, 0, 2, 0)
    u.ShowWindow(hwnd, 9)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    return u.GetForegroundWindow() == hwnd


# --- SendInput plumbing (Windows only) -------------------------------------------------------------------------------

_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_SCANCODE = 0x0008
_MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
_MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010


def _require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("game_input requires Windows")


class GameInput:
    """Keys and mouse for the Practice Tool game. All coordinates are absolute screen pixels."""

    def __init__(self, guard: Optional[PracticeGuard] = None, dry_run: bool = False) -> None:
        self._guard = guard or PracticeGuard()
        self._dry = dry_run
        self.log: list = []
        self.on_input: Optional[Callable[..., None]] = None  # turn_log.TurnLog.add_input: sees every input, sent or dry-run

    def focus_game(self) -> bool:
        """Bring the game window to the foreground (refused unless a Practice Tool game runs). True when it is in front."""
        self._guard.check_game_only()
        return self._guard._foreground()

    def _send_key(self, scan: int, up: bool) -> None:
        _require_windows()
        flags = _KEYEVENTF_SCANCODE | (_KEYEVENTF_KEYUP if up else 0)
        ctypes.windll.user32.keybd_event(0, scan, flags, 0)

    def key(self, name: str, hold_s: float = 0.05, ctrl: bool = False) -> None:
        self._guard.check()
        self.log.append(("key", name, ctrl))
        self._notify("key", key=name, ctrl=ctrl)
        if self._dry:
            return
        if ctrl:
            self._send_key(SCAN["CTRL"], False)
            time.sleep(0.03)
        self._send_key(SCAN[name], False)
        time.sleep(hold_s)
        self._send_key(SCAN[name], True)
        if ctrl:
            time.sleep(0.03)
            self._send_key(SCAN["CTRL"], True)

    def _notify(self, kind: str, **kw: object) -> None:
        if self.on_input is not None:
            try:
                self.on_input(kind, **kw)
            except Exception:  # noqa: BLE001 - observers never break input
                pass

    def move_to(self, x: int, y: int) -> None:
        self._guard.check()
        self._notify("move", x=x, y=y)
        if not self._dry:
            _require_windows()
            ctypes.windll.user32.SetCursorPos(int(x), int(y))

    def _mouse(self, down: int, up: int, x: int, y: int) -> None:
        self._guard.check()
        if self._dry:
            return
        _require_windows()
        u = ctypes.windll.user32
        u.SetCursorPos(int(x), int(y))
        time.sleep(0.03)
        u.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.04)
        u.mouse_event(up, 0, 0, 0, 0)

    def right_click(self, x: int, y: int) -> None:
        self.log.append(("right", x, y))
        self._notify("right_click", x=x, y=y)
        self._mouse(_MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP, x, y)

    def left_click(self, x: int, y: int) -> None:
        self.log.append(("left", x, y))
        self._notify("left_click", x=x, y=y)
        self._mouse(_MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP, x, y)

    def type_text(self, text: str, delay_s: float = 0.04) -> None:
        """Type ``text`` as Unicode characters (layout independent: works on AZERTY)."""
        self._guard.check()
        self.log.append(("type", text))
        self._notify("type_text", text=text)
        if self._dry:
            return
        _require_windows()
        for ch in text:
            _send_unicode(ch, up=False)
            _send_unicode(ch, up=True)
            time.sleep(delay_s)


def _send_unicode(ch: str, up: bool) -> None:
    class _KI(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_void_p)]

    class _U(ctypes.Union):
        _fields_ = [("ki", _KI), ("pad", ctypes.c_byte * 32)]

    class _IN(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

    flags = 0x0004 | (0x0002 if up else 0)  # KEYEVENTF_UNICODE | KEYUP
    inp = _IN(1, _U(ki=_KI(0, ord(ch), flags, 0, None)))
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
