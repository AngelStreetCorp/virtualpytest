"""Minion health bars found by their dark FRAME, not by the fill colour (pure numpy/cv2).

Why: ``perception.find_bars`` keys on the bright team fill, so bars that are almost empty, dim (shadow, fog edge) or under a
spell overlay are never found (elite-replay gate 4: minion recall about 85 %; the owner's live complaint "Garen ignores the
lowest minions"). Every minion bar, full or empty, bright or dim, has the same frame: a dark rectangle about 63 px wide and 6 rows
tall (top and bottom rows dark across the whole width, dark left and right edges). This module finds that rectangle, then reads
the fill inside it.

    bars = find_bar_frames(rgb, exclude=[(x0, y0, x1, y1), ...])   # perception.Bar list, kind "minion"
    bars = verify(rgb, bars, model_path, ctx_of)                   # optional classifier veto (elite / Practice Tool models)

Shared by the elite-replay extractor (scripts/lol_practice/elite_video_extract.py) and the live Garen bot (task121).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .perception import Bar

DARK = 48            # frame pixels are near black (12-30); fill and terrain are brighter
W_MIN, W_MAX = 56, 70  # outer frame width of a minion bar (63 measured at 1920x1200)
H_MIN, H_MAX = 5, 7    # rows from the top frame row to the bottom frame row
EDGE_FRAC = 0.85     # share of a frame row that must be dark
FULL_W = 63
CAP_LUM = 85         # the left cap is light grey (lum 100-200)


def _runs(row: np.ndarray, min_len: int) -> List[Tuple[int, int]]:
    """(start, end) of runs of True of at least ``min_len``."""
    if not row.any():
        return []
    d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
    starts, ends = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
    return [(int(s), int(e - 1)) for s, e in zip(starts, ends) if e - s >= min_len]


def _team(fill_rgb: np.ndarray) -> str:
    """Team from the mean colour of the filled interior: red-ish = 'enemy', blue-ish = 'ally', else 'unknown'."""
    if fill_rgb.size == 0:
        return "unknown"
    r, g, b = fill_rgb.reshape(-1, 3).mean(axis=0)
    if r > b + 25 and r > g + 15:
        return "enemy"
    if b > r + 25:
        return "ally"
    return "unknown"


PRACTICE = {"cap_lum": 49, "reject_green": True, "seed_slack": 1, "exclude_by_centre": True}  # Practice Tool player view: the left interior is the dark-red kill segment (lum ~55),
                                                 # not the replay's grey cap; the own champion's nameplate bar is green


def find_bar_frames(rgb: Any, exclude: Optional[Iterable[Tuple[int, int, int, int]]] = None,
                    roi: Optional[Tuple[int, int, int, int]] = None, bgr: bool = False, cap_lum: int = 85,
                    reject_green: bool = False, seed_slack: int = 0, exclude_by_centre: bool = False) -> List[Bar]:
    """``perception.Bar`` list (kind "minion") of every minion-bar frame; see :func:`find_bar_frames_ex` for the details.
    Practice Tool / live game: ``find_bar_frames(img, ..., **PRACTICE)``."""
    return [d["bar"] for d in find_bar_frames_ex(rgb, exclude, roi, bgr, cap_lum, reject_green, seed_slack, exclude_by_centre)]


def find_bar_frames_ex(rgb: Any, exclude: Optional[Iterable[Tuple[int, int, int, int]]] = None,
                       roi: Optional[Tuple[int, int, int, int]] = None, bgr: bool = False, cap_lum: int = 85,
                       reject_green: bool = False, seed_slack: int = 0, exclude_by_centre: bool = False) -> List[Dict[str, Any]]:
    """Every minion-bar frame in an RGB uint8 array (H, W, 3). ``exclude``: HUD rectangles to ignore (chat, panels, minimap).

    ``roi`` = (x0, y0, x1, y1): search only there; returned coordinates stay absolute. ``bgr``: the buffer is BGR(A) (GDI grabber).
    Returned dicts: {"bar": Bar, "frame": (x0, y0, x1, y1), "fill_lum": mean brightness of the fill, "frame_conf": 0..1 (how
    complete the dark frame is), "unit_hue": "red" | "blue" | None (armour colour of the unit under the bar)}. ``Bar``: kind "minion", x = frame centre, y = first interior row (the row find_bars reports), frac = filled share,
    team = "enemy" (red fill) | "ally" (blue fill) | "unknown" (empty or grey). Champion and turret bars are wider and not returned.
    """
    a = np.asarray(rgb)
    if a.ndim == 3 and a.shape[2] == 4:
        a = a[:, :, :3]
    if bgr:
        a = a[:, :, ::-1]
    ox = oy = 0
    if roi is not None:
        rx0, ry0, rx1, ry1 = roi
        ox, oy = max(0, rx0), max(0, ry0)
        a = a[oy:ry1, ox:rx1]
        if exclude:
            exclude = [(x0 - ox, y0 - oy, x1 - ox, y1 - oy) for x0, y0, x1, y1 in exclude]
    H, Wd = a.shape[:2]
    import cv2
    lum = cv2.cvtColor(np.ascontiguousarray(a), cv2.COLOR_RGB2GRAY).astype(np.int16)
    dark = lum < DARK
    if exclude and not exclude_by_centre:  # mask mode (replay default): a frame touching a zone is lost
        for x0, y0, x1, y1 in exclude:
            dark[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = False
    # seeds: a bright cap pixel (interior row 1) with a dark frame pixel left of it and dark frame rows above it and 30 px right
    bright = lum >= cap_lum
    if seed_slack:  # anti-aliased first interior column: accept the bright pixel up to seed_slack columns further in
        b2 = bright.copy()
        for k in range(1, seed_slack + 1):
            b2[:, :-k] |= bright[:, k:]
        bright = b2
    seed = np.zeros_like(dark)
    seed[1:, 1:-40] = bright[1:, 1:-40] & dark[1:, :-41] & dark[:-1, 1:-40] & dark[:-1, 31:-10]
    ys, xs = np.nonzero(seed)
    out: List[Dict[str, Any]] = []
    seen: List[Tuple[int, int]] = []
    for sy, sx in zip(ys.tolist(), xs.tolist()):
        y, x0 = sy - 1, sx - 1  # top frame row, left frame column
        if y + H_MAX >= H or any(abs(x0 - px) <= 4 and abs(y - py) <= 3 for px, py in seen):
            continue
        run = dark[y, x0:min(Wd, x0 + W_MAX + 4)]
        if run[:W_MIN].mean() < EDGE_FRAC:
            continue
        # right end of the top frame row: last dark column of the run before a 3-px light gap
        gaps = np.nonzero(~run[W_MIN - 4:])[0]
        x1 = x0 + W_MIN - 4 + (int(gaps[0]) - 1 if len(gaps) else len(run) - (W_MIN - 4) - 1)
        if True:
            w = x1 - x0 + 1
            bot = None
            for h in range(H_MIN, H_MAX + 1):
                if dark[y + h, x0:x1 + 1].mean() >= EDGE_FRAC:
                    bot = h
                    break
            if bot is None:
                continue
            # left and right edges dark on the interior rows (1-px tolerance)
            inner = slice(y + 1, y + bot)
            left = dark[inner, max(0, x0 - 1):x0 + 2].any(axis=1).mean()
            right = dark[inner, max(0, x1 - 1):min(Wd, x1 + 2)].any(axis=1).mean()
            if left < 0.75 or right < 0.75:
                continue
            fw = x1 - x0 + 1
            if not (W_MIN <= fw <= W_MAX):
                continue
            # the top frame row must START at x0 and END at x1 (a piece of a wider champion / turret bar continues past them)
            if x0 >= 3 and dark[y, x0 - 3:x0 - 1].all() and dark[y + bot, x0 - 3:x0 - 1].all():
                continue
            if x1 + 3 < Wd and dark[y, x1 + 2:x1 + 4].all() and dark[y + bot, x1 + 2:x1 + 4].all():
                continue
            # signature 1: the bright 3-px cap just inside the left edge on the interior rows (present even on an empty bar)
            cap = lum[y + 1:y + bot, x0 + 1 + seed_slack:x0 + 4 + seed_slack]
            if (cap.mean(axis=1) >= cap_lum).mean() < 0.5:  # 2 of 4 interior rows (the lowest row is often darker)
                continue
            # signature 2: an isolated frame: the rows just outside it are not frame-dark across the width
            above = dark[max(0, y - 1), x0 + 4:x1 - 3].mean()
            below = dark[min(H - 1, y + bot + 1), x0 + 4:x1 - 3].mean()
            if above > 0.7 and below > 0.7:
                continue
            cx = (x0 + x1) // 2
            seen.append((x0, y))
            # interior: skip the 3-px left cap and the edges; fill = columns brighter than the frame
            ix0, ix1 = x0 + 4, x1 - 1
            interior = a[y + 1:y + bot, ix0:ix1].astype(np.int16)
            col_lum = interior.sum(axis=2).mean(axis=0) / 3
            filled = col_lum >= DARK + 6
            idx = np.nonzero(filled)[0]
            frac = round(float((idx.max() + 1) / max(1, len(col_lum))), 2) if len(idx) else 0.0
            team = _team(interior[:, filled]) if len(idx) else "unknown"
            if reject_green and len(idx):
                r_, g_, b_ = interior[:, filled].reshape(-1, 3).mean(axis=0)
                if g_ > r_ + 25 and g_ > b_ + 10:  # the own champion's green nameplate bar
                    continue
            conf = float(min(1.0, (dark[y, x0:x1 + 1].mean() + dark[y + bot, x0:x1 + 1].mean() + left + right) / 4))
            reg = a[min(H, y + 12):min(H, y + 60), max(0, cx - 25):cx + 25].astype(np.int16)
            hue = None
            if reg.size:
                red = ((reg[..., 0] > 120) & (reg[..., 0] > reg[..., 1] + 40) & (reg[..., 0] > reg[..., 2] + 40)).sum()
                blue = ((reg[..., 2] > 120) & (reg[..., 2] > reg[..., 0] + 30)).sum()
                hue = None if max(red, blue) < 25 else ("red" if red > blue else "blue")
            if exclude and exclude_by_centre and any(ex0 <= cx < ex1 and ey0 <= y + 1 < ey1 for ex0, ey0, ex1, ey1 in exclude):
                continue  # centre mode (live game, like find_bars): only a bar CENTRED in a zone is dropped
            out.append({"bar": Bar("minion", cx + ox, int(y + 1) + oy, frac, team, None, 0.0), "frame": (int(x0) + ox, int(y) + oy, int(x1) + ox, int(y + bot) + oy),
                        "fill_lum": float(col_lum[filled].mean()) if len(idx) else 0.0, "frame_conf": round(conf, 2), "unit_hue": hue})
    return out


def verify(rgb: Any, bars: Sequence[Bar], model_path: str, ctx_of: Callable[[Bar], Dict[str, Any]]) -> List[Bar]:
    """Keep the bars the minion-bar classifier accepts (score > 0). ``ctx_of(bar)`` gives the classifier context
    (hp_frac, bordered, siblings, dist_garen, hud_edge, colour)."""
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), *[".."] * 5, "scripts", "lol_practice"))
    from elite_bar_classifier import BarClassifier  # noqa: E402
    clf = BarClassifier(model_path)
    return [b for b in bars if clf.is_minion(rgb, b.x, b.y, ctx_of(b))]
