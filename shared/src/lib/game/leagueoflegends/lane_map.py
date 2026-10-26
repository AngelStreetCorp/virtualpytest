"""TASK-132: top-lane geometry on the minimap, for either side, and which enemy turret is the next one.

Positions are normalised minimap coordinates (0,0 = top-left, 1,1 = bottom-right). Summoner's Rift turret coordinates
(game units / 14800, y flipped) for the top lane: blue T1 (981,10441), T2 (1512,6699), T3 (1169,4287); red T1 (4318,13875),
T2 (7943,13411), T3 (10481,13651). The map is symmetric under (x, y) -> (y, x) for the top lane, so a red-side bot uses the
same path walked from the other end. The turret range is 750 units = 0.05 normalised; the bot keeps ``FENCE`` (0.13) away from
the next enemy turret because both v1 turret deaths happened at 0.06-0.09.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

Pt = Tuple[float, float]

BLUE_BASE: Pt = (0.07, 0.93)
RED_BASE: Pt = (0.93, 0.07)
BLUE_TURRETS: List[Pt] = [(0.066, 0.295), (0.102, 0.547), (0.079, 0.710)]  # T1, T2, T3 (top lane)
RED_TURRETS: List[Pt] = [(0.292, 0.063), (0.537, 0.094), (0.708, 0.078)]
CORNER: Pt = (0.075, 0.07)
# the lane, from the blue base to the red base
PATH: List[Pt] = [BLUE_BASE, BLUE_TURRETS[2], BLUE_TURRETS[1], BLUE_TURRETS[0], CORNER] + RED_TURRETS + [RED_BASE]

FENCE = 0.13  # minimum distance to the next standing enemy turret
FARM_BACK = 0.15  # farm this far (along the lane) before the next enemy turret
SAFE_BACK = 0.30
MINIMAP_X, MINIMAP_Y, MINIMAP_W, MINIMAP_H = 1612, 893, 300, 297  # the map inside the minimap frame, 1920x1200


def _path_for(team: str) -> List[Pt]:
    return PATH if team == "ORDER" else list(reversed(PATH))


def enemy_turrets(team: str) -> List[Pt]:
    """Enemy top-lane turrets in the order the bot meets them: T1, T2, T3."""
    return list(RED_TURRETS) if team == "ORDER" else list(BLUE_TURRETS)


def _arc_len(path: List[Pt]) -> List[float]:
    out = [0.0]
    for a, b in zip(path, path[1:]):
        out.append(out[-1] + math.dist(a, b))
    return out


def _point_at(path: List[Pt], arc: float) -> Pt:
    cum = _arc_len(path)
    arc = max(0.0, min(arc, cum[-1]))
    for i in range(1, len(path)):
        if arc <= cum[i]:
            f = (arc - cum[i - 1]) / ((cum[i] - cum[i - 1]) or 1.0)
            return path[i - 1][0] + f * (path[i][0] - path[i - 1][0]), path[i - 1][1] + f * (path[i][1] - path[i - 1][1])
    return path[-1]


def _arc_of(path: List[Pt], p: Pt) -> float:
    cum = _arc_len(path)
    best, best_d = 0.0, 9.0
    for i in range(1, len(path)):
        a, b = path[i - 1], path[i]
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        q = (a[0] + t * dx, a[1] + t * dy)
        d = math.dist(p, q)
        if d < best_d:
            best_d, best = d, cum[i - 1] + t * (cum[i] - cum[i - 1])
    return best


def to_pixels(p: Pt) -> Tuple[int, int]:
    return int(MINIMAP_X + p[0] * MINIMAP_W), int(MINIMAP_Y + p[1] * MINIMAP_H)


def lane_geometry(team: str, turrets_down: int) -> Dict[str, Any]:
    """The next enemy turret (None when all three are down) and where to farm / retreat, as minimap pixels."""
    turrets = enemy_turrets(team)
    if turrets_down >= len(turrets):
        return {"turret": None, "farm_px": to_pixels(_point_at(_path_for(team), _arc_of(_path_for(team), turrets[-1]))),
                "safe_px": to_pixels(_point_at(_path_for(team), _arc_of(_path_for(team), turrets[-1]) - SAFE_BACK))}
    t = turrets[turrets_down]
    path = _path_for(team)
    a = _arc_of(path, t)
    return {"turret": t, "farm_px": to_pixels(_point_at(path, a - FARM_BACK)), "safe_px": to_pixels(_point_at(path, a - SAFE_BACK))}


def too_close(pos: Optional[Pt], turret: Optional[Pt]) -> bool:
    return pos is not None and turret is not None and math.dist(pos, turret) < FENCE


_TURRET_RE = re.compile(r"Turret_T(Order|Chaos)_L(\d)_P(\d)_")


def enemy_top_turrets_down(events: Iterable[Dict[str, Any]], team: str, lane_code: int = 2) -> int:
    """Number of distinct enemy top-lane turrets (Turret_T<Chaos|Order>_L2_P<n>_...) reported dead by ``TurretKilled``."""
    enemy = "Chaos" if team == "ORDER" else "Order"
    names = set()
    for e in events:
        if e.get("EventName") != "TurretKilled":
            continue
        m = _TURRET_RE.match(e.get("TurretKilled") or "")
        if m and m.group(1) == enemy and int(m.group(2)) == lane_code:
            names.add(e["TurretKilled"])
    return len(names)


BASE_RADIUS = 0.2  # normalised minimap distance from our own base centre that counts as "in the fountain area"


def at_base(pos: Optional[Pt], team: str) -> bool:
    """True when the minimap camera box is on our own base (blue bottom-left, red top-right)."""
    return pos is not None and math.dist(pos, BLUE_BASE if team == "ORDER" else RED_BASE) < BASE_RADIUS
