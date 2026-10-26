"""TASK-135: danger / safe zones around Garen, from what the bot sees on one frame. Pure: no input, no I/O, no game state changes.

Geometry is the 1920x1200 screen with the camera locked on Garen (feet at ``PLAYER_XY``); about 1 screen px per game unit
(garen_bot.TURRET_RANGE_PX relies on the same). :func:`compute_zones` returns the zone dicts of
``docs/agent/game/lol/OVERLAY_CONTRACT.md`` (normalised 0..1, circle radius relative to the frame width). The reach constants are
estimates from the ranges in ``docs/agent/game/lol/aggro.md``; they are corrected there, not here, when measured.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .perception import HUD_Y, PLAYER_XY, Bar

FRAME_W, FRAME_H = 1920, 1200
# Measured on run garen-run-20261019-055521 (809 turns, tools/zone_hit_rate.py): within 223 px (110 range + both radii) of the nearest
# enemy minion Garen took 32 % of the damage; within 350 px 84 % (in 21 % of the turns); within 550 px 93 %; 663 and 800 add nothing.
# Minions walk up between two ticks, so the melee zone is wider than range + radii.
MELEE_REACH_PX = 350
CASTER_REACH_PX = 550  # caster attack range; a bar does not tell caster from melee, so every enemy minion also gets this caution ring
CHAMPION_THREAT_PX = 600  # an enemy champion's usual poke / engage reach
TURRET_RANGE_PX = 800  # 750 units plus Garen's size (same value as garen_bot.TURRET_RANGE_PX)
TURRET_MIN_ALLIES = 3  # allied minions inside the turret range that make entering it acceptable
TURRET_BAR_DY = 90  # the turret bar sits this far above the turret centre
TANK_ALLIES = 1  # allied minions inside an enemy minion's reach: it hits them first (priority list in aggro.md)
SAFE_MARGIN_PX = 60
GRID_PX = 80
SAFE_MAX_DIST_PX = 900
MAX_MINION_ZONES = 6  # the nearest enemy minions only: more would not change the picture and bloats the log


def _circle(zid: str, kind: str, level: str, cx: float, cy: float, r_px: float, reason: str) -> Dict[str, Any]:
    return {"id": zid, "kind": kind, "level": level, "shape": "circle",
            "x": round(cx / FRAME_W, 4), "y": round(cy / FRAME_H, 4), "r": round(r_px / FRAME_W, 4), "reason": reason}


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _is_minion(b: Bar) -> bool:
    return b.kind == "minion"


def _minion_reach(b: Bar) -> int:
    return CASTER_REACH_PX if b.minion_type == "caster" else MELEE_REACH_PX  # type unknown (None) = assume the short reach


def threat_zones(enemies: Sequence[Bar], allies: Sequence[Bar]) -> List[Dict[str, Any]]:
    """Danger / caution circles: enemy turrets, enemy minions, enemy champions."""
    out: List[Dict[str, Any]] = []
    ally_min = [b for b in allies if _is_minion(b)]
    for n, t in enumerate((b for b in enemies if b.kind == "turret"), 1):
        c = (float(t.x), float(t.y + TURRET_BAR_DY))
        inside = sum(1 for a in ally_min if _dist((a.x, a.body[1]), c) <= TURRET_RANGE_PX)
        ok = inside >= TURRET_MIN_ALLIES
        out.append(_circle(f"tur{n}", "enemy_turret", "caution" if ok else "danger", c[0], c[1], TURRET_RANGE_PX,
                           f"enemy turret range, {inside} of {TURRET_MIN_ALLIES} allied minions inside"))
    pos = (float(PLAYER_XY[0]), float(PLAYER_XY[1]))
    near = sorted((b for b in enemies if _is_minion(b)), key=lambda b: _dist((b.x, b.body[1]), pos))[:MAX_MINION_ZONES]
    for n, m in enumerate(near, 1):
        c = (float(m.x), float(m.body[1]))
        reach = _minion_reach(m)
        tank = sum(1 for a in ally_min if _dist((a.x, a.body[1]), c) <= reach)
        kind = m.minion_type or "melee"
        out.append(_circle(f"min{n}", "enemy_minion_threat", "caution" if tank >= TANK_ALLIES else "danger", c[0], c[1], reach,
                           f"enemy {kind} minion reach, {tank} allied minions in it" + (" (they are hit first)" if tank >= TANK_ALLIES else "")))
        if m.minion_type != "melee" and m.minion_type != "cannon":
            out.append(_circle(f"poke{n}", "enemy_caster_reach", "caution", c[0], c[1], CASTER_REACH_PX,
                               "caster attack range" + (" (type unknown: could be a caster)" if m.minion_type is None else "")))
    for n, ch in enumerate((b for b in enemies if b.kind == "champion"), 1):
        c = (float(ch.x), float(ch.body[1]))
        out.append(_circle(f"champ{n}", "enemy_champion", "danger", c[0], c[1], CHAMPION_THREAT_PX, "enemy champion threat range"))
    return out


def _blocked(pt: Tuple[float, float], zones: Sequence[Dict[str, Any]]) -> bool:
    for z in zones:
        if z["shape"] != "circle" or z["level"] == "safe":
            continue
        if _dist(pt, (z["x"] * FRAME_W, z["y"] * FRAME_H)) <= z["r"] * FRAME_W + SAFE_MARGIN_PX:
            return True
    return False


def safe_spots(zones: Sequence[Dict[str, Any]], allies: Sequence[Bar], retreat_dir: Optional[Tuple[float, float]] = None,
               count: int = 2) -> List[Dict[str, Any]]:
    """Up to ``count`` safe circles: grid points on screen outside every danger / caution circle, nearest to Garen first, our side
    (``retreat_dir``: screen direction towards our base) and next to allied minions preferred."""
    pos = (float(PLAYER_XY[0]), float(PLAYER_XY[1]))
    ally_pts = [(float(a.x), float(a.body[1])) for a in allies if _is_minion(a)]
    scored: List[Tuple[float, Tuple[float, float], bool]] = []
    for gx in range(GRID_PX, FRAME_W - GRID_PX + 1, GRID_PX):
        for gy in range(GRID_PX, HUD_Y - GRID_PX + 1, GRID_PX):
            pt = (float(gx), float(gy))
            d = _dist(pt, pos)
            if d > SAFE_MAX_DIST_PX or _blocked(pt, zones):
                continue
            score = -d
            if retreat_dir is not None:
                n = math.hypot(*retreat_dir) or 1.0
                score += 0.5 * ((gx - pos[0]) * retreat_dir[0] + (gy - pos[1]) * retreat_dir[1]) / n
            behind = any(_dist(pt, a) <= 300 for a in ally_pts)
            score += 150.0 if behind else 0.0
            scored.append((score, pt, behind))
    scored.sort(key=lambda r: -r[0])
    picked: List[Tuple[float, float, bool]] = []
    for _, pt, behind in scored:
        if all(_dist(pt, (p[0], p[1])) >= 300 for p in picked):
            picked.append((pt[0], pt[1], behind))
        if len(picked) >= count:
            break
    return [_circle(f"safe{n}", "safe", "safe", p[0], p[1], GRID_PX, "outside every danger zone" + (", next to allied minions" if p[2] else ""))
            for n, p in enumerate(picked, 1)]


def retreat_point(zones: Sequence[Dict[str, Any]]) -> Optional[Tuple[int, int]]:
    """Screen pixel to right-click for a retreat: the centre of the first ``safe`` circle (best first), None when no safe spot is on
    screen (the caller then keeps its minimap safe point). Pure; the caller decides whether to use it."""
    for z in zones:
        if z["kind"] == "safe" and z["shape"] == "circle":
            return int(z["x"] * FRAME_W), int(z["y"] * FRAME_H)
    return None


def compute_zones(enemies: Sequence[Bar], allies: Sequence[Bar], retreat_dir: Optional[Tuple[float, float]] = None) -> List[Dict[str, Any]]:
    """All zones of one frame: threats first, then the safe spots."""
    threats = threat_zones(enemies, allies)
    return threats + safe_spots(threats, allies, retreat_dir)


def standing_in(zones: Sequence[Dict[str, Any]]) -> List[str]:
    """Ids of the danger / caution zones that contain Garen right now."""
    pos = (float(PLAYER_XY[0]), float(PLAYER_XY[1]))
    return [z["id"] for z in zones if z["shape"] == "circle" and z["level"] != "safe"
            and _dist(pos, (z["x"] * FRAME_W, z["y"] * FRAME_H)) <= z["r"] * FRAME_W]
