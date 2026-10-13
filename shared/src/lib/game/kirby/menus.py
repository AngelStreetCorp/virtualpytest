"""
Menu driver for Super Kirby Clash on a Nintendo Switch (TASK-51).

A state machine over BGR frames at 1280x720: from any starting screen
(village, results, reward, dialog, story card, ...) to the start of the
*Hornhead* quest fight. It runs **before** the fight loop of ``runner.py``
and, optionally, again after every fight so the bot can play ``--fights N``
fights in a row without a human on the couch.

Input only through the existing Switch actions via ``io.run_actions`` (a list
of ``{"command": ..., "action_type": "switch", "params": {...}}`` dicts),
exactly like ``runner.py``. All OCR goes through the module-level ``_ocr``
helper so tests can monkeypatch it.

Public surface:

* ``banner_text(img) -> str``            OCR of the red/orange top banner.
* ``region_text(img, name) -> str``     OCR of one small named region (``REGIONS``).
* ``dialog_box(img) -> bool``            the beige story/dialog text box at the bottom.
* ``quests_bubble(img) -> bool``         True when the village interaction bubble reads "quest".
* ``classify(img) -> str``               one of ``fight``, ``black``, ``form_team``, ``game_mode``,
                                         ``select_area``, ``select_quest``, ``change_role``, ``shop``,
                                         ``confirm_setoff``, ``quest_choice``, ``village_at_board``,
                                         ``village``, ``dialog``.
* ``MenuDriver(io, max_steps=120, log=print)``  the state machine; ``to_fight() -> dict``.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Optional

import cv2
import numpy as np
import pytesseract
from shared.src.lib.utils import cv2_io


# --- OCR -------------------------------------------------------------------------

def _ocr(img: np.ndarray, psm: int) -> str:
    """All OCR passes go through this helper so tests can monkeypatch it."""
    config = f"--psm {int(psm)}"
    text = pytesseract.image_to_string(img, config=config)
    return text.strip()


def banner_text(img: np.ndarray) -> str:
    """The white title on the red/orange top banner (e.g. "Form a Team").

    Crop ``img[15:95, 60:480]``, mask white text (``V > 200 and S < 70``),
    invert to black-on-white, resize x2 with ``INTER_NEAREST``, ``--psm 7``.
    On other screens this returns junk like "Bt".
    """
    if img is None:
        return ""
    crop = img[15:95, 60:480]
    if crop.size == 0:
        return ""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = (hsv[:, :, 2] > 200) & (hsv[:, :, 1] < 70)
    bw = np.where(mask, 0, 255).astype(np.uint8)
    bw = cv2.resize(bw, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    return _ocr(bw, 7)


# Small regions read by OCR. Full-frame OCR costs ~10 s on a loaded Pi 4 and splits words
# ("Vig Or)"); a crop costs ~1 s. Boxes are (x0, y0, x1, y1) at 1280x720, measured 2026-10-05.
REGIONS = {
    "vigor": ((780, 20, 900, 70), 7),       # top-right "Vigor" bar: village, Form a Team, quest select
    "confirm": ((380, 260, 900, 380), 6),   # "Are you ready to set off on your quest?"
    "choice": ((410, 240, 870, 480), 6),    # "Play a different quest / Play the same quest / To the Village"
    "quest_card": ((840, 425, 1180, 485), 7),  # Select Quest: boss name on the right card ("Hornhead")
}

# Beige dialog box at the bottom: share of box-coloured pixels in rows 575..700. Measured: 0.94-0.95
# on village story dialogs (which also show the Vigor bar), 0.34-0.42 on the plain village.
DIALOG_BOX_MIN = 0.8


def region_text(img: np.ndarray, name: str) -> str:
    """OCR of one named region (grey, x2), lowercased and whitespace-collapsed."""
    if img is None:
        return ""
    (x0, y0, x1, y1), psm = REGIONS[name]
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return ""
    grey = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None, fx=2, fy=2)
    return re.sub(r"\s+", " ", _ocr(grey, psm).strip().lower())


# Form a Team's "Set Off" button turns bright red when the cursor is on it. Measured: 0.66 of the
# button area bright red when highlighted, 0.01 when the cursor is still on a team card.
SETOFF_BOX = (500, 585, 780, 635)
SETOFF_MIN = 0.3


def setoff_highlighted(img: np.ndarray) -> bool:
    """True when Form a Team's "Set Off" button is the highlighted one."""
    if img is None:
        return False
    x0, y0, x1, y1 = SETOFF_BOX
    hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    h, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    red = ((h <= 8) | (h >= 172)) & (sat > 180) & (val > 170)
    return float(red.mean()) >= SETOFF_MIN


def dialog_box(img: np.ndarray) -> bool:
    """True when the beige story/dialog text box covers the bottom of the screen."""
    if img is None:
        return False
    hsv = cv2.cvtColor(img[575:700, 60:1220], cv2.COLOR_BGR2HSV)
    h, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    box = (h >= 12) & (h <= 32) & (sat >= 30) & (sat <= 130) & (val >= 170)
    return float(box.mean()) >= DIALOG_BOX_MIN


def quests_bubble(img: np.ndarray) -> bool:
    """True when the village interaction bubble reads "quest" (board's "GO Quests,").

    In rows 100..420 find connected components of near-white pixels
    (``V > 225 and S < 30``) with width 100..220, height 40..90, area > 3000.
    Each crop is OCR'd at x2 ``--psm 7``; True if any text contains "quest".
    """
    if img is None:
        return False
    h, w = img.shape[:2]
    y0 = max(0, 100)
    y1 = min(h, 420)
    if y1 <= y0:
        return False
    region = img[y0:y1]
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 2] > 225) & (hsv[:, :, 1] < 30)).astype(np.uint8)
    if mask.sum() == 0:
        return False
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    for i in range(1, num):
        x, y, ww, hh, area = stats[i]
        if area <= 3000:
            continue
        if not (100 <= ww <= 220 and 40 <= hh <= 90):
            continue
        if y + hh > region.shape[0]:
            continue
        if x + ww > region.shape[1]:
            continue
        crop = region[y:y + hh, x:x + ww]
        # Dark text on the white bubble: OCR the plain grey crop (a threshold inverts it).
        grey = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None, fx=2, fy=2)
        text = _ocr(grey, 7).lower()
        if "quest" in text:
            return True
    return False


# --- screen classification ------------------------------------------------------

def classify(img: np.ndarray) -> str:
    """Return the screen class. Order matters: ``fight`` short-circuits everything else, and
    each OCR is a small crop (``region_text``), run only when the cheaper checks did not decide."""
    if img is None:
        return "dialog"
    # 1. in_fight wins (no OCR at all).
    from .vision import in_fight
    if in_fight(img):
        return "fight"
    # 2. Mostly black (transition frame; no OCR).
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    if float(hsv[:, :, 2].mean()) < 20.0:
        return "black"
    # 3. Banner.
    banner = banner_text(img).lower()
    if "form a team" in banner:
        return "form_team"
    if "game mode" in banner:
        return "game_mode"
    if "select area" in banner:
        return "select_area"
    if "select quest" in banner:
        return "select_quest"
    if "change role" in banner or "get ready" in banner:
        return "change_role"   # Kirby's card sub-menus ("Get Ready!" -> "Change Role"): back out
    if any(w in banner for w in ("shoppe", "weapons", "armor", "support", "stickers", "gem apples")):
        return "shop"
    # 4. Yes/No set-off dialog, then the after-quest choice.
    if "set off" in region_text(img, "confirm"):
        return "confirm_setoff"
    if "same quest" in region_text(img, "choice"):
        return "quest_choice"
    # 5. Village (Vigor bar, no banner). A story dialog in the village also shows the bar.
    if "igor" in region_text(img, "vigor"):
        if dialog_box(img):
            return "dialog"
        if quests_bubble(img):
            return "village_at_board"
        return "village"
    # 6. Everything else (story cards, results, rewards, tutorial, "Victory!",
    #    "New quests have appeared") advances with A.
    return "dialog"


# --- menu driver ---------------------------------------------------------------

# Per-step settle (s); the Switch HUD takes ~1 s to redraw after a press.
DEFAULT_SETTLE_S = 1.2

# The same class seen this many times in a row with no progress -> press B once.
STUCK_REPEATS = 8

# Village sweep: rights per sweep, sweeps before giving up.
SWEEP_RIGHTS = 20
MAX_SWEEPS = 2

# A "dialog" frame right after a menu-screen action is usually the menu mid-transition (the banner
# is not readable yet): pressing A there hits whatever the cursor is on (Kirby's card -> Change
# Role). Such a frame gets no input; A is pressed on the next dialog frame. Seen live 2026-10-06.
MENU_CLASSES = ("form_team", "change_role", "game_mode", "select_area", "select_quest", "shop",
                "quest_choice", "village", "village_at_board")

# Frames reach the Pi 1-2 s after the screen (more when the Pi is loaded). After acting on a screen,
# frames of that same screen within REACT_S are the lag, not a screen that ignored the input:
# acting again sent a second B (Form a Team -> back to Select Quest) or a second A (card -> Get
# Ready!). Seen live 2026-10-06. The village sweep is exempt (its steps are meant to repeat).
REACT_S = 3.0

# Polls (x 0.3 s) waiting for a frame newer than the one already acted on.
MAX_STALE_POLLS = 40


class MenuDriver:
    """Drive the Switch from any screen to the start of the Hornhead fight.

    ``io`` must expose ``frame() -> Optional[str]`` and ``run_actions(list) -> dict``.
    For tests a fake IO with a scripted frame sequence stands in.
    """

    def __init__(self, io, max_steps: int = 120, log: Callable[..., None] = print,
                 settle_s: float = DEFAULT_SETTLE_S):
        self.io = io
        self.max_steps = int(max_steps)
        self.log = log
        self.settle_s = float(settle_s)
        self._sweeps = 0            # village sweeps started
        self._rights = SWEEP_RIGHTS  # >= SWEEP_RIGHTS: next village step walks to the left edge

    # --- helpers ----------------------------------------------------------------

    @staticmethod
    def _action(command: str, **params) -> Dict[str, Any]:
        """One Switch action in the executor's shape. ``wait_time`` is the per-action settle (0)."""
        body: Dict[str, Any] = {"command": command, "action_type": "switch"}
        body["params"] = {"wait_time": 0, **params}
        return body

    def _new_frame(self, last_path: Optional[str]):
        """Newest frame whose path differs from ``last_path`` (frames lag ~1 s behind the
        screen, so the frame we just acted on must never be classified twice)."""
        img, path = None, None
        for _ in range(MAX_STALE_POLLS):
            path = self.io.frame()
            if path and path != last_path:
                img = cv2_io.imread(path)
                if img is not None:
                    return img, path
            elif not path:
                return None, None
            time.sleep(0.3)
        return None, path

    def _send(self, actions: List[Dict[str, Any]], screen: str) -> None:
        if screen == "shop":
            # Safety net: never A in the shop (Gem Apples tab can lead to real purchases).
            actions = [a for a in actions if a["command"] != "press:a"]
        if not actions:
            return
        try:
            self.io.run_actions(actions)
        except Exception as e:
            self.log(f"[game_kirby] menu actions {[a.get('command') for a in actions]} failed: {e}")

    def _village_actions(self) -> Optional[List[Dict[str, Any]]]:
        """Sweep the camera across the village until the board's bubble appears.

        Sweep start: walk Kirby to the left edge (stick left 2 s). Then 20 steps of a short
        stick to pan the camera right. Two sweeps max; None = give up.
        """
        if self._rights >= SWEEP_RIGHTS:
            if self._sweeps >= MAX_SWEEPS:
                return None
            self._sweeps += 1
            self._rights = 0
            return [self._action("stick:left,left,2000")]
        self._rights += 1
        return [self._action("stick:left,right,250")]

    def _step_actions(self, screen: str, img: Optional[np.ndarray] = None) -> List[Dict[str, Any]]:
        """The Switch action(s) for this screen class. Empty list = wait, no input."""
        if screen == "dialog":
            return [self._action("press:a")]
        if screen == "confirm_setoff":
            # "Yes" is the default; A accepts it.
            return [self._action("press:a")]
        if screen == "quest_choice":
            # Default highlight is "Play a different quest"; one down -> "Play the same quest".
            return [self._action("press:down"), self._action("press:a")]
        if screen == "form_team":
            # The cursor starts on Kirby's card (A there opens Change Role), and a down sent while the
            # screen slides in is dropped: press A only once "Set Off" is seen highlighted.
            if setoff_highlighted(img):
                return [self._action("press:a")]
            return [self._action("press:down")]
        if screen == "change_role":
            return [self._action("press:b")]
        if screen == "game_mode":
            # Story Quest is the highlighted default.
            return [self._action("press:a")]
        if screen == "select_area":
            # Seaside is the leftmost area.
            return [self._action("press:left"), self._action("press:left"), self._action("press:a")]
        if screen == "select_quest":
            # The list grows as quests unlock and wraps around, and the cursor starts on the last
            # quest played: step up one quest at a time until the card names Hornhead.
            if "ornhead" in region_text(img, "quest_card"):
                return [self._action("press:a")]
            return [self._action("press:up")]
        if screen == "shop":
            return [self._action("press:b")]
        if screen == "village_at_board":
            # Open the quest board.
            return [self._action("press:up")]
        return []   # black: wait

    # --- main loop --------------------------------------------------------------

    def _report(self, t0: float, steps: int, screens: List[str], reached: bool,
                error: Optional[str]) -> Dict[str, Any]:
        return {"reached": reached, "steps": steps, "menu_s": round(time.time() - t0, 2),
                "screens": screens, "error": error, "shots": self.shots}

    def _shot(self, step: int, screen: str) -> None:
        """One report screenshot each time the screen class changes (the menu trail)."""
        evidence = getattr(self.io, "evidence", None)
        if evidence is None:
            return
        path = evidence(f"kirby_menu_{step}_{screen}")
        if path:
            self.shots.append({"path": path, "label": f"step {step} {screen}"})

    def to_fight(self) -> Dict[str, Any]:
        """Loop until ``classify(frame) == "fight"``; return a small report."""
        t0 = time.time()
        screens: List[str] = []
        self.shots: List[Dict[str, Any]] = []
        last_class: Optional[str] = None
        last_path: Optional[str] = None
        same_count = 0
        acted_class: Optional[str] = None
        acted_at = 0.0

        for step in range(1, self.max_steps + 1):
            img, path = self._new_frame(last_path)
            if img is None:
                if path is not None:
                    return self._report(t0, step, screens, False, "menu: no new frame")
                time.sleep(self.settle_s)   # no frame yet, retry
                continue
            last_path = path
            screen = classify(img)
            if not screens or screens[-1] != screen:
                self._shot(step, screen)
            screens.append(screen)

            if screen == "fight":
                return self._report(t0, step, screens, True, None)

            if screen == acted_class and screen != "village" and time.time() - acted_at < REACT_S:
                self.log(f"[game_kirby.menu] step={step} class={screen} action=wait (input in flight)")
                time.sleep(self.settle_s)
                continue

            # Same class again with no progress (black and village are exempt).
            if screen == last_class and screen not in ("black", "village"):
                same_count += 1
            else:
                same_count = 1
            last_class = screen

            if same_count >= STUCK_REPEATS:
                # Backs out of an unexpected sub-menu.
                self.log(f"[game_kirby.menu] step={step} class={screen} stuck, action=press:b")
                self._send([self._action("press:b")], screen)
                same_count = 0
                time.sleep(self.settle_s)
                continue

            prev = screens[-2] if len(screens) > 1 else None
            if screen == "village":
                actions = self._village_actions()
                if actions is None:
                    return self._report(t0, step, screens, False, "quest board not found")
            elif screen == "dialog" and prev in MENU_CLASSES:
                actions = []   # the menu is still sliding: wait one frame before pressing A
            else:
                actions = self._step_actions(screen, img)

            cmd = ", ".join(a["command"] for a in actions) if actions else "wait"
            self.log(f"[game_kirby.menu] step={step} class={screen} action={cmd}")
            self._send(actions, screen)
            if actions:
                acted_class, acted_at = screen, time.time()
            time.sleep(self.settle_s)

        return self._report(t0, self.max_steps, screens, False, "menu: max steps")
