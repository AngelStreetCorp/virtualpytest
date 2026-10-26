"""Leave a running Practice Tool game the way a player does: Esc -> Exit Game -> Leave.

Run in the user's session (see create_exit_task.ps1). Safety: it only acts when the Live Client Data API says the game
mode is PRACTICETOOL, so it can never leave a real match. Coordinates are fractions of the screen (measured on 1920x1200).
Writes C:\\virtualpytest\\exit-result.json.
"""
import ctypes
import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\virtualpytest\virtualpytest")
from shared.src.lib.game.leagueoflegends.process_utils import is_running  # noqa: E402

OUT = Path(r"C:\virtualpytest\exit-result.json")
EXIT_GAME = (0.305, 0.778)  # bottom-left button of the Esc menu
LEAVE = (0.427, 0.452)  # confirm dialog
user32 = ctypes.windll.user32


def game_mode() -> str | None:
    try:
        with urllib.request.urlopen(
            "https://127.0.0.1:2999/liveclientdata/gamestats", context=ssl._create_unverified_context(), timeout=5
        ) as r:
            return json.loads(r.read().decode()).get("gameMode")
    except Exception:
        return None


def key_esc() -> None:
    user32.keybd_event(0x1B, 0x01, 0, 0)
    time.sleep(0.1)
    user32.keybd_event(0x1B, 0x01, 2, 0)


def click(frac: tuple[float, float]) -> None:
    w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    user32.SetCursorPos(int(frac[0] * w), int(frac[1] * h))
    time.sleep(0.3)
    user32.mouse_event(2, 0, 0, 0, 0)
    time.sleep(0.1)
    user32.mouse_event(4, 0, 0, 0, 0)


def main() -> int:
    if not is_running("League of Legends.exe"):
        OUT.write_text(json.dumps({"ok": True, "detail": "no game running"}))
        return 0
    mode = game_mode()
    if mode != "PRACTICETOOL":
        OUT.write_text(json.dumps({"ok": False, "detail": f"refused: game mode is {mode!r}, not PRACTICETOOL"}))
        return 1
    try:  # an open shop swallowed the Esc and the clicks of an earlier exit: close it first
        import numpy as np
        from PIL import ImageGrab
        from shared.src.lib.game.leagueoflegends.perception import shop_is_open
        for _ in range(3):
            if not shop_is_open(np.asarray(ImageGrab.grab(all_screens=True).convert("RGB"))):
                break
            user32.keybd_event(0x19, 0x19, 0, 0)  # P toggles the shop
            time.sleep(0.1)
            user32.keybd_event(0x19, 0x19, 2, 0)
            time.sleep(1.0)
    except Exception:  # noqa: BLE001
        pass
    key_esc()
    time.sleep(1.5)
    click(EXIT_GAME)
    time.sleep(1.5)
    click(LEAVE)
    for _ in range(30):
        if not is_running("League of Legends.exe"):
            OUT.write_text(json.dumps({"ok": True, "detail": "game exited"}))
            return 0
        time.sleep(2)
    OUT.write_text(json.dumps({"ok": False, "detail": "game still running 60 s after Leave"}))
    return 1


if __name__ == "__main__":
    sys.exit(main())
