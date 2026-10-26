"""TASK-131 goal 4: where is the player? Read the minimap in a game screenshot (read-only).

Two steps: :func:`find_marker` finds the player's marker in the minimap crop; :func:`zone_of` turns the
normalised position (0,0 = top-left, 1,1 = bottom-right; blue base bottom-left, red base top-right) into a
zone name: ``base``, ``top``, ``mid``, ``bot``, ``river``, ``jungle``. :func:`evaluate` scores the reader
against hand-labelled frames (goal 4 needs >= 90 % on 50 frames).

The minimap rectangle was measured on the recorded vpt-windows runs (960x600 shots of the 1920x1200 client,
default minimap size; every shot has the same size). The player is found by the white CAMERA RECTANGLE the
client draws on the minimap: it is centred on the player's champion (the champion icon itself is a portrait
with a blue ring, so a colour blob cannot tell the player from the allies). ``find_marker`` keeps the old
colour-blob finder as a fallback when no camera rectangle is visible.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

# fraction of the screenshot: (x0, y0, x1, y1)
# the map square without its frame, measured on 960x600 shots of the vpt-windows client
DEFAULT_MINIMAP_RECT = (0.836, 0.742, 0.992, 0.984)

Point = Tuple[float, float]
_TOP: List[Point] = [(0.07, 0.93), (0.07, 0.10), (0.10, 0.07), (0.93, 0.07)]
_BOT: List[Point] = [(0.07, 0.93), (0.90, 0.93), (0.93, 0.90), (0.93, 0.07)]
_MID: List[Point] = [(0.07, 0.93), (0.93, 0.07)]
_RIVER: List[Point] = [(0.07, 0.07), (0.93, 0.93)]
LANE_WIDTH = 0.085
RIVER_WIDTH = 0.07
BASE_RADIUS = 0.20


def _dist_seg(p: Point, a: Point, b: Point) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _dist_line(p: Point, pts: Sequence[Point]) -> float:
    return min(_dist_seg(p, pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def zone_of(x: float, y: float) -> str:
    p = (x, y)
    if math.hypot(x - 0.07, y - 0.93) <= BASE_RADIUS or math.hypot(x - 0.93, y - 0.07) <= BASE_RADIUS:
        return "base"
    lanes = {"top": _dist_line(p, _TOP), "mid": _dist_line(p, _MID), "bot": _dist_line(p, _BOT)}
    lane, d = min(lanes.items(), key=lambda kv: kv[1])
    if d <= LANE_WIDTH:
        return lane
    if _dist_line(p, _RIVER) <= RIVER_WIDTH:
        return "river"
    return "jungle"


def crop_minimap(img: Any, rect: Tuple[float, float, float, float] = DEFAULT_MINIMAP_RECT) -> Any:
    h, w = img.shape[:2]
    return img[int(rect[1] * h):int(rect[3] * h), int(rect[0] * w):int(rect[2] * w)]


# camera rectangle size as a fraction of the minimap crop (median over the recorded runs)
CAM_W, CAM_H = 0.27, 0.165


def find_camera_box(minimap_bgr: Any) -> Optional[Point]:
    """Player position from the camera box: :func:`_box_centre`, pulled half-way to any map edge the box rests on.

    The camera stops at the map edge, so against an edge the player is somewhere in the outer half of the box, not
    at its centre (measured: a Garen in the top lane at x = 0.09 gave a centre of 0.16, which read as river).
    """
    c = _box_centre(minimap_bgr)
    if c is None:
        return None
    x, y = c
    eps = 0.04
    if x - CAM_W / 2 <= eps:
        x -= CAM_W / 4
    elif x + CAM_W / 2 >= 1 - eps:
        x += CAM_W / 4
    if y - CAM_H / 2 <= eps:
        y -= CAM_H / 4
    elif y + CAM_H / 2 >= 1 - eps:
        y += CAM_H / 4
    return min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)


def _box_centre(minimap_bgr: Any) -> Optional[Point]:
    """Normalised centre of the white camera rectangle (thin light-grey outline) on the minimap crop.

    The rectangle marks the player only while the camera is locked on the champion (Y). The account starts with
    the camera free, parked on the home corner, so a box at (0.14, 0.92) can mean "camera not locked yet"; the
    bot locks it first thing, and a screenshot alone cannot tell the two apart.

    Long horizontal and vertical light-grey runs are kept (this drops portraits, text and terrain), the biggest
    cluster of them is the rectangle. When the rectangle sits against the map edge it is cut off by the crop;
    the centre is then rebuilt from the sides that are visible and the known rectangle size.
    """
    import cv2
    import numpy as np

    mx = minimap_bgr.max(axis=2).astype(int)
    mn = minimap_bgr.min(axis=2).astype(int)
    # thin line brighter than its surroundings (a top-hat), light grey: the outline is anti-aliased and dim
    bg = cv2.medianBlur(minimap_bgr.min(axis=2), 9).astype(int)
    mask = (((mn - bg) >= 25) & (mx - mn <= 45) & (mn >= 110)).astype(np.uint8)
    h, w = mask.shape
    hl = cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((1, 3), np.uint8)), cv2.MORPH_OPEN, np.ones((1, max(5, int(0.10 * w))), np.uint8))
    vl = cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 1), np.uint8)), cv2.MORPH_OPEN, np.ones((max(5, int(0.07 * h)), 1), np.uint8))
    # a full rectangle = two equal horizontal edges one box height apart; this survives a path line or ping that
    # touches the outline and would merge it into a bigger blob
    nh, _l, hs, _hc = cv2.connectedComponentsWithStats(hl, connectivity=8)
    edges = [tuple(hs[i][:4]) for i in range(1, nh) if 0.8 * CAM_W * w <= hs[i][2] <= 1.15 * CAM_W * w and hs[i][3] <= 4]
    for i, (xa, ya, wa, _ha) in enumerate(edges):
        for xb, yb, wb, _hb in edges[i + 1:]:
            if abs(xa - xb) <= 3 and abs(wa - wb) <= 4 and 0.8 * CAM_H * h <= abs(ya - yb) <= 1.2 * CAM_H * h:
                return ((xa + xb) / 2 + wa / 2) / w, (ya + yb) / 2 / h
    # box against the top or bottom edge of the map: only one horizontal edge is on the crop
    lone = [e for e in edges if e[1] <= 1.1 * CAM_H * h or e[1] >= h - 1.1 * CAM_H * h]
    if len(lone) == 1:
        xa, ya, wa, _ha = lone[0]
        return (xa + wa / 2) / w, (ya - CAM_H * h / 2 if ya < h / 2 else ya + CAM_H * h / 2) / h
    lines = cv2.dilate(cv2.bitwise_or(hl, vl), np.ones((3, 3), np.uint8))
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(lines, connectivity=8)
    best = None
    for i in range(1, n):
        x, y, bw, bh, _a = stats[i]
        if bw > 1.15 * CAM_W * w or bh > 1.25 * CAM_H * h or bw < 0.10 * w or bh < 0.05 * h:
            continue
        if best is None or bw * bh > best[2] * best[3]:
            best = (x, y, bw, bh)
    if best is None:
        return None
    x, y, bw, bh = best
    cx, cy = x + bw / 2, y + bh / 2
    m = 3
    if bw < 0.9 * CAM_W * w:  # one vertical side cut off by the crop
        cx = x + CAM_W * w / 2 if x <= m else x + bw - CAM_W * w / 2
    if bh < 0.9 * CAM_H * h:
        cy = y + CAM_H * h / 2 if y <= m else y + bh - CAM_H * h / 2
    return (min(max(cx / w, 0.0), 1.0), min(max(cy / h, 0.0), 1.0))


def find_marker(minimap_bgr: Any, team: str = "ORDER") -> Optional[Point]:
    """Normalised (x, y) of the largest blob in the team's border colour (blue ORDER / red CHAOS) that
    also carries a bright ring (the active player's marker is outlined in white/gold). None when absent."""
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(minimap_bgr, cv2.COLOR_BGR2HSV)
    if team == "ORDER":
        mask = cv2.inRange(hsv, (95, 120, 120), (125, 255, 255))
    else:
        m1 = cv2.inRange(hsv, (0, 140, 140), (8, 255, 255))
        m2 = cv2.inRange(hsv, (172, 140, 140), (180, 255, 255))
        mask = cv2.bitwise_or(m1, m2)
    ring = cv2.inRange(hsv, (0, 0, 220), (180, 60, 255))
    ring = cv2.dilate(ring, np.ones((5, 5), np.uint8))
    mask = cv2.bitwise_and(mask, ring)
    n, _lab, stats, cent = cv2.connectedComponentsWithStats(mask)
    best, area = None, 6
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] > area:
            best, area = cent[i], stats[i, cv2.CC_STAT_AREA]
    if best is None:
        return None
    h, w = minimap_bgr.shape[:2]
    return (float(best[0]) / w, float(best[1]) / h)


def zone_from_screenshot(img: Any, team: str = "ORDER", rect=DEFAULT_MINIMAP_RECT) -> Optional[str]:
    crop = crop_minimap(img, rect)
    pos = find_camera_box(crop) or find_marker(crop, team)
    return None if pos is None else zone_of(*pos)


def evaluate(labelled: Sequence[Dict[str, Any]], team: str = "ORDER", rect=DEFAULT_MINIMAP_RECT) -> Dict[str, Any]:
    """``labelled`` = [{"image": <bgr array>, "zone": "top"}]. Agreement with the hand label."""
    ok = sum(1 for f in labelled if zone_from_screenshot(f["image"], team, rect) == f["zone"])
    return {"frames": len(labelled), "agree": ok, "agreement": ok / len(labelled) if labelled else 0.0}
