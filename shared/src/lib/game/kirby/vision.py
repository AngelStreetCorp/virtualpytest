"""
Pure vision on BGR numpy frames captured from the Nintendo Switch HDMI feed at 1280x720.

The thresholds were measured on real fight frames: Kirby is the bright pink/magenta blob in the
foreground, the boss is a blue-purple body behind him, the HP bars sit in rows 668..680 of the
bottom HUD (Kirby's on the left, the CPU teammate's on the right); the fight is on while Kirby's
bar is on screen. Every function is pure: BGR in, numbers out.
"""

from __future__ import annotations

import cv2
import numpy as np
from typing import Optional, Tuple

# HP bar column ranges, measured on the fight HUD.
KIRBY_BAR: Tuple[int, int] = (157, 350)
MATE_BAR: Tuple[int, int] = (488, 640)

# The HP bar is green when healthy and turns yellow, then red, when low: hue ranges (OpenCV, 0..179)
# that count as "filled", with the saturation / value floors shared by both.
HP_HUE_RANGES: Tuple[Tuple[int, int], ...] = ((0, 40), (50, 85))
HP_MIN_SAT = 120
HP_MIN_VAL = 120

# In fight = Kirby's pink name plate around his HP bar is on screen. Measured 2026-10-05 on 9 fight
# frames (4,169-5,581 plate pixels) and 33 non-fight frames (village, menus, results, "TIME'S UP": 0).
# The HP bar alone is not enough: its yellow/red hues also match the beige village floor and menus.
PLATE_BOX = (140, 640, 370, 690)   # x0, y0, x1, y1
PLATE_MIN_PIXELS = 2000

# Minimum pixels needed to trust a detection (below this, the read returns None).
KIRBY_MIN_PIXELS = 150
BOSS_MIN_PIXELS = 2000


def _mask(hsv: np.ndarray, h_low: int, h_high: int, s_min: int, v_min: int) -> np.ndarray:
    """HSV mask that also handles the hue wrap-around (Kirby's magenta spans both ends)."""
    if h_low <= h_high:
        h = ((hsv[:, :, 0] >= h_low) & (hsv[:, :, 0] <= h_high))
    else:
        h = ((hsv[:, :, 0] >= h_low) | (hsv[:, :, 0] <= h_high))
    return h & (hsv[:, :, 1] >= s_min) & (hsv[:, :, 2] >= v_min)


def kirby_x(img: np.ndarray) -> Optional[int]:
    """Median x of Kirby's pink body, restricted to rows above the HUD (y < 560)."""
    if img is None:
        return None
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    body = hsv[:560]
    mask = _mask(body, 160, 3, 150, 180)
    pixels = int(mask.sum())
    if pixels < KIRBY_MIN_PIXELS:
        return None
    ys, xs = np.where(mask)
    return int(np.median(xs))


def boss_x(img: np.ndarray) -> Optional[int]:
    """Median x of the boss's blue-purple body (rows 250..560, x < 1200)."""
    if img is None:
        return None
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    region = hsv[250:560, :1200]
    mask = _mask(region, 105, 150, 90, 60)
    pixels = int(mask.sum())
    if pixels < BOSS_MIN_PIXELS:
        return None
    ys, xs = np.where(mask)
    return int(np.median(xs))


def hp(img: np.ndarray, x0: int, x1: int) -> Optional[float]:
    """Filled fraction of an HP bar, columns [x0, x1), rows 668..680.

    A column is filled when any pixel is bright and saturated in a hue of the bar's colours (green,
    yellow, red). Returns None when no column is filled (the bar is absent).
    """
    if img is None or x1 <= x0:
        return None
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    strip = hsv[668:680, x0:x1]
    mask = np.zeros(strip.shape[:2], dtype=bool)
    for h_low, h_high in HP_HUE_RANGES:
        mask |= _mask(strip, h_low, h_high, HP_MIN_SAT + 1, HP_MIN_VAL + 1)
    cols = np.where(mask.any(axis=0))[0]
    if len(cols) == 0:
        return None
    return max(0.0, min(1.0, int(cols[-1]) / float(x1 - x0)))


def in_fight(img: np.ndarray) -> bool:
    """True when Kirby's pink HP plate is on screen. The clock icon is not used: it turns grey during banners."""
    if img is None:
        return False
    x0, y0, x1, y1 = PLATE_BOX
    hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    return int(_mask(hsv, 160, 3, 150, 150).sum()) >= PLATE_MIN_PIXELS


def read(img: np.ndarray) -> dict:
    """All five reads the bot + Jev need in one frame."""
    return {
        "kirby_x": kirby_x(img),
        "boss_x": boss_x(img),
        "kirby_hp": hp(img, *KIRBY_BAR),
        "mate_hp": hp(img, *MATE_BAR),
        "in_fight": in_fight(img),
    }