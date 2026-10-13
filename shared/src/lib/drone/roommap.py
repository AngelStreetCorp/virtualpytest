"""
RoomMap: the room as the safety guard and the planners see it. On a real flight the operator writes it
(a JSON file); in the simulator it is derived from the simulated room.

JSON: {"width": 600, "depth": 500, "obstacles": [{"name": "shelf", "x0": 0, "x1": 380, "y0": 285, "y1": 315, "h": 200}]}
Units are cm, origin at the bottom-left corner of the room; h is the top of the obstacle above the floor.
"""

import heapq
import json
import math
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Tuple

CLEARANCE_CM = 30      # guard keeps the drone this far from an obstacle
ABOVE_CM = 30          # and flies over it only when this much higher than its top
PLAN_EXTRA_CM = 5      # the planner stays a little further off than the guard clips
GRID_CM = 25


@dataclass
class Obstacle:
    name: str
    x0: float
    x1: float
    y0: float
    y1: float
    h: float


@dataclass
class RoomMap:
    width: float = 600
    depth: float = 500
    obstacles: List[Obstacle] = field(default_factory=list)

    # ---------- io ---------------------------------------------------------
    def to_dict(self) -> dict:
        return {"width": self.width, "depth": self.depth, "obstacles": [asdict(o) for o in self.obstacles]}

    @classmethod
    def from_dict(cls, data: dict) -> "RoomMap":
        return cls(float(data["width"]), float(data["depth"]),
                   [Obstacle(str(o["name"]), float(o["x0"]), float(o["x1"]), float(o["y0"]), float(o["y1"]),
                             float(o["h"])) for o in data.get("obstacles", [])])

    @classmethod
    def load(cls, path: str) -> "RoomMap":
        with open(path) as f:
            return cls.from_dict(json.load(f))

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
            f.write("\n")

    @classmethod
    def from_sim_room(cls, room) -> "RoomMap":
        obs = []
        for o in room.objects:
            x0, x1, y0, y1 = o.bounds
            obs.append(Obstacle(o.name, x0, x1, y0, y1, o.z0 + o.h))
        return cls(room.width, room.depth, obs)

    def summary(self) -> str:
        parts = [f"{o.name} x {o.x0:.0f}..{o.x1:.0f}, y {o.y0:.0f}..{o.y1:.0f}, {o.h:.0f} cm high"
                 for o in self.obstacles]
        return f"room {self.width:g} x {self.depth:g} cm; obstacles: " + ("; ".join(parts) or "none")

    # ---------- geometry ---------------------------------------------------
    def blocking(self, z: float) -> List[Obstacle]:
        """Obstacles in the way of a drone flying at height z."""
        return [o for o in self.obstacles if z < o.h + ABOVE_CM]

    def inside(self, x: float, y: float, inflate: float, z: float = 0.0) -> Optional[Obstacle]:
        for o in self.blocking(z):
            if o.x0 - inflate < x < o.x1 + inflate and o.y0 - inflate < y < o.y1 + inflate:
                return o
        return None

    def first_hit(self, x0: float, y0: float, x1: float, y1: float, inflate: float = CLEARANCE_CM,
                  z: float = 0.0) -> Optional[Tuple[float, Obstacle]]:
        """Distance along the segment at which it first enters an inflated obstacle, or None.
        An obstacle the start is already inside only counts when the move ends closer to it."""
        length = math.hypot(x1 - x0, y1 - y0)
        if length < 1e-9:
            return None
        best: Optional[Tuple[float, Obstacle]] = None
        dx, dy = x1 - x0, y1 - y0
        for o in self.blocking(z):
            bx0, bx1, by0, by1 = o.x0 - inflate, o.x1 + inflate, o.y0 - inflate, o.y1 + inflate
            if bx0 < x0 < bx1 and by0 < y0 < by1:
                # already inside the clearance band (dead reckoning drifted): moving along it or away is fine
                if self._dist(o, x1, y1) < self._dist(o, x0, y0) - 1.0:
                    return 0.0, o
                continue
            t0, t1 = 0.0, 1.0
            for p, d, lo, hi in ((x0, dx, bx0, bx1), (y0, dy, by0, by1)):
                if abs(d) < 1e-9:
                    if not lo < p < hi:
                        t0, t1 = 1.0, 0.0
                        break
                    continue
                ta, tb = (lo - p) / d, (hi - p) / d
                if ta > tb:
                    ta, tb = tb, ta
                t0, t1 = max(t0, ta), min(t1, tb)
            if t0 < t1 and (best is None or t0 * length < best[0]):
                best = (t0 * length, o)
        return best

    @staticmethod
    def _dist(o: Obstacle, x: float, y: float) -> float:
        return math.hypot(max(o.x0 - x, 0, x - o.x1), max(o.y0 - y, 0, y - o.y1))

    # ---------- planning ---------------------------------------------------
    def nodes(self, margin: float, cell: float = GRID_CM) -> Tuple[List[float], List[float]]:
        def axis(size):
            n = int((size - 2 * margin) // cell)
            return [margin + i * cell for i in range(n + 1)]
        return axis(self.width), axis(self.depth)

    def _free_node(self, x, y, z, inflate) -> bool:
        return self.inside(x, y, inflate, z) is None

    def search(self, start: Tuple[float, float], margin: float, z: float = 80.0, cell: float = GRID_CM,
               goal: Optional[Tuple[float, float]] = None):
        """Dijkstra over free 8-connected grid nodes (obstacles inflated).
        Returns (dist, parent, start_node, goal_node); stops early at the goal."""
        inflate = CLEARANCE_CM + PLAN_EXTRA_CM
        xs, ys = self.nodes(margin, cell)
        free = {(i, j) for i, x in enumerate(xs) for j, y in enumerate(ys) if self._free_node(x, y, z, inflate)}
        if not free:
            return {}, {}, None, None

        def nearest(p):
            return min(free, key=lambda n: (xs[n[0]] - p[0]) ** 2 + (ys[n[1]] - p[1]) ** 2)

        s = nearest(start)
        g = nearest(goal) if goal else None
        dist, parent = {s: 0.0}, {}
        heap = [(0.0, s)]
        while heap:
            d, n = heapq.heappop(heap)
            if d > dist.get(n, 1e18):
                continue
            if g is not None and n == g:
                break
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    m = (n[0] + di, n[1] + dj)
                    if (di == 0 and dj == 0) or m not in free:
                        continue
                    if di and dj and not ((n[0] + di, n[1]) in free and (n[0], n[1] + dj) in free):
                        continue
                    nd = d + math.hypot(di, dj) * cell
                    if nd < dist.get(m, 1e18):
                        dist[m], parent[m] = nd, n
                        heapq.heappush(heap, (nd, m))
        self._grid = (xs, ys)
        return dist, parent, s, g

    def with_extra(self, extra: List[Obstacle]) -> "RoomMap":
        return RoomMap(self.width, self.depth, list(self.obstacles) + extra)

    def plan(self, start: Tuple[float, float], goal: Tuple[float, float], margin: float, z: float = 80.0,
             cell: float = GRID_CM) -> Optional[List[Tuple[float, float]]]:
        """Corner points from start to (the nearest free node to) goal; collinear nodes merged. None if unreachable."""
        dist, parent, s, g = self.search(start, margin, z, cell, goal)
        if s is None or g not in dist:
            return None
        xs, ys = self._grid
        nodes = [g]
        while nodes[-1] != s:
            nodes.append(parent[nodes[-1]])
        nodes.reverse()
        pts = [(xs[i], ys[j]) for i, j in nodes]
        out = [pts[0]]
        for k in range(1, len(pts) - 1):
            a, b, c = out[-1], pts[k], pts[k + 1]
            if abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) > 1e-6 or \
                    (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) < 0:
                out.append(b)
        if len(pts) > 1:
            out.append(pts[-1])
        return out

    def reachable_nodes(self, start: Tuple[float, float], margin: float, z: float = 80.0,
                        cell: float = GRID_CM) -> List[Tuple[float, float]]:
        dist, _parent, s, _ = self.search(start, margin, z, cell)
        if s is None:
            return []
        xs, ys = self._grid
        return [(xs[i], ys[j]) for (i, j) in dist]
