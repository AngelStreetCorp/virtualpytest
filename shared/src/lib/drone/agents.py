"""
Agents decide one action per turn from a frame and the dead-reckoned pose. They only claim; the
referee decides the win.

Actions are SDK commands (cw/ccw n, forward n, ...), claim, and hold (the hider, once in place).
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from .roommap import Obstacle
from .perception import Detection, Detector, parse_json_object
from .safety import SafetyLimits
from .sim.world import Pose

MENU = ["cw 30", "ccw 30", "forward 50", "back 50", "left 50", "right 50", "up 30", "down 30", "claim"]
GRID_CM = 150
FOV_DEG = 82.6
MAX_LEG_CM = 150
PLAN_INSET_CM = 10  # plan this far inside the fence: a degree of yaw error over a long leg is several cm
ARRIVE_CM = 30


@dataclass
class Decision:
    action: str
    detection: Optional[Detection] = None
    note: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    ai_calls: int = 0


def bearing_deg(pose: Pose, x: float, y: float) -> float:
    return math.degrees(math.atan2(x - pose.x, y - pose.y)) % 360


def turn_command(pose: Pose, bearing: float, step: int = 90) -> Optional[str]:
    diff = (bearing - pose.yaw_deg + 540) % 360 - 180
    if abs(diff) < 12:
        return None
    n = int(min(abs(diff), step))
    return f"cw {n}" if diff > 0 else f"ccw {n}"


def goto_step(pose: Pose, x: float, y: float, arrive_cm: float = 40, max_leg: int = 100) -> Optional[str]:
    """Next turn or forward command towards (x, y); None when arrived."""
    dist = math.hypot(x - pose.x, y - pose.y)
    if dist < arrive_cm:
        return None
    turn = turn_command(pose, bearing_deg(pose, x, y))
    if turn:
        return turn
    return f"forward {int(min(dist, max_leg))}"


class Navigator:
    """Travels to a goal as turn + forward legs along an A* path through the room map (straight line without one)."""
    MAX_REPLANS = 3

    def __init__(self, limits: SafetyLimits):
        self.limits = limits
        self.goal: Optional[Tuple[float, float]] = None
        self.path: List[Tuple[float, float]] = []
        self.replans = 0
        self.failed = False
        self.peers = lambda: []  # other drones' dead-reckoned poses, set by the game

    def set_goal(self, pose: Pose, goal: Tuple[float, float]) -> bool:
        self.goal, self.replans, self.failed = goal, 0, False
        return self._plan(pose)

    def _plan(self, pose: Pose) -> bool:
        rm = self.limits.room_map
        if rm is None:
            self.path = [self.goal]
            return True
        z = max(pose.z, 80.0)
        path = None
        flying = [p for p in self.peers() if p.z > 5]
        if flying:  # route round the other drone first, through it only if there is no other way
            half = max(self.limits.min_sep - 35, 20)
            peer_obs = [Obstacle("peer", p.x - half, p.x + half, p.y - half, p.y + half, 1000) for p in flying]
            path = rm.with_extra(peer_obs).plan((pose.x, pose.y), self.goal, self.limits.margin + PLAN_INSET_CM, z)
        if path is None:
            path = rm.plan((pose.x, pose.y), self.goal, self.limits.margin + PLAN_INSET_CM, z)
        if path is None:
            self.path, self.failed = [], True
            return False
        self.path = path
        return True

    def blocked(self, pose: Pose) -> None:
        """A move was refused or clipped: plan again from where the drone really is."""
        self.replans += 1
        if self.replans > self.MAX_REPLANS or not self._plan(pose):
            self.failed = True
            self.path = []

    def clear(self) -> None:
        self.replans = 0

    def step(self, pose: Pose) -> Optional[str]:
        """Next command; None when arrived (or failed)."""
        while self.path:
            cmd = goto_step(pose, *self.path[0], arrive_cm=ARRIVE_CM, max_leg=MAX_LEG_CM)
            if cmd is not None:
                return cmd
            self.path.pop(0)
        return None


def _fence_cells(limits: SafetyLimits) -> List[Tuple[float, float]]:
    def axis(lo, hi):
        n = max(1, math.ceil((hi - lo) / GRID_CM))
        return [lo + (hi - lo) * i / n for i in range(n + 1)]
    return [(x, y) for x in axis(limits.margin, limits.room_w - limits.margin)
            for y in axis(limits.margin, limits.room_d - limits.margin)]


class ScanAgent:
    name = "scan"

    MAX_APPROACH = 8
    MAX_BLOCKED = 3
    FRAME_W, FOCAL_PX = 960, 545

    def __init__(self, perception: Detector, limits: SafetyLimits, claim_conf: float = 0.5, spin_steps: int = 8,
                 spin_deg: int = 45):
        self.perception = perception
        self.limits = limits
        self.claim_conf = claim_conf
        self.spin_steps = spin_steps
        self.spin_deg = spin_deg  # the camera sees 82 deg, so 45 deg steps overlap
        self.target = ""
        self.nav = Navigator(limits)
        self.visited: List[Tuple[float, float]] = []
        self.spins_left = spin_steps
        self.waypoint: Optional[Tuple[float, float]] = None
        self.skip_claims = 0
        self.approaching = 0
        self.weak_ignore = 0
        self.blocked_run = 0
        self.chooser = None  # LlmAgent: picks the next waypoint among the candidates
        self.last_choice: Optional[dict] = None  # what the chooser spent: calls, tokens, reason
        self.seen: List[Tuple[int, str]] = []  # (heading, what perception saw) since the last waypoint choice
        self.ai_calls = self.tokens_in = self.tokens_out = 0

    def start(self, target: str) -> None:
        self.target = target
        self.seen = []
        self.approaching = 0
        self.blocked_run = 0
        self.visited = []
        self.spins_left = self.spin_steps
        self.waypoint = None

    def rejected(self) -> None:
        """The referee refused our claim: look elsewhere for a couple of turns."""
        self.skip_claims = 2

    def set_peers(self, peers) -> None:
        self.nav.peers = peers

    def _note(self, det: Optional[Detection]) -> str:
        if getattr(self.perception, "costly", False):
            note = getattr(self.perception, "last_note", "")
            if note:
                return note
        return f"{det.label} ({det.confidence:.2f})" if det else ""

    def decide(self, frame: Optional[np.ndarray], pose: Pose, blocked: Optional[str] = None) -> Decision:
        # A paid detector (VLM) looks at scan frames only: one per heading, plus while closing in on a sighting.
        look = (not getattr(self.perception, "costly", False) or self.waypoint is None
                or self.approaching > 0 or not self.nav.path)
        det = self.perception.detect(frame, self.target) if frame is not None and look else None
        if look and frame is not None and self.waypoint is None:
            self.seen.append((int(round(pose.yaw_deg)) % 360, self._note(det)))
        if det and det.confidence < self.claim_conf and self.weak_ignore > 0:
            self.weak_ignore -= 1  # a faint sighting we could not get closer to: keep exploring
            det = None
        cut = False
        if det and self.skip_claims == 0:
            # Far away (low confidence): centre it and close in before claiming; claim when sure or stuck.
            x, y, w, h = det.bbox
            # touching the side: not fully in view, centre it first (a model's rough box says nothing about that)
            cut = bool(getattr(self.perception, "reliable_bbox", True)) and (x <= 3 or x + w >= self.FRAME_W - 3)
            if det.confidence < self.claim_conf and (self.approaching >= self.MAX_APPROACH or blocked):
                self.approaching, self.weak_ignore = 0, 8  # could not get closer: not a sighting
                det = None
            elif (det.confidence >= self.claim_conf and not cut) or self.approaching >= self.MAX_APPROACH or blocked:
                self.approaching = 0
                return Decision("claim", det, f"{det.label} seen ({det.confidence:.2f})")
        if det and self.skip_claims == 0:
            self.approaching += 1
            x = det.bbox[0]
            off = math.degrees(math.atan((det.bbox[0] + det.bbox[2] / 2 - self.FRAME_W / 2) / self.FOCAL_PX))
            if abs(off) > 6 or cut:
                off = off if abs(off) > 6 else (-10 if x <= 3 else 10)
                return Decision(f"cw {int(abs(off))}" if off > 0 else f"ccw {int(abs(off))}", det,
                                f"{det.label} far ({det.confidence:.2f}), centring")
            return Decision("forward 50", det, f"{det.label} far ({det.confidence:.2f}), approaching")
        self.approaching = 0
        if self.skip_claims:
            self.skip_claims -= 1
        if blocked and self.waypoint:
            self.blocked_run += 1
            self.nav.blocked(pose)
            if self.nav.failed or self.blocked_run >= self.MAX_BLOCKED:
                self.visited.append(self.waypoint)  # cannot get there: give the cell up
                self.waypoint = None
                self.spins_left = self.spin_steps
        elif not blocked:
            self.blocked_run = 0
            self.nav.clear()
        if self.waypoint is None and self.spins_left > 0:
            self.spins_left -= 1
            return Decision(f"cw {self.spin_deg}", det, f"scan {self.spin_steps - self.spins_left}/{self.spin_steps}")
        if self.waypoint is None:
            self.waypoint = self._next_waypoint(pose)
            if self.waypoint is None:
                self.visited = []
                self.spins_left = self.spin_steps
                return Decision(f"cw {self.spin_deg}", det, "all cells visited, restarting")
            self.blocked_run = 0
            self.nav.set_goal(pose, self.waypoint)
            choice, self.last_choice = self.last_choice, None
            if choice:
                step = self.nav.step(pose)
                return Decision(step or f"cw {self.spin_deg}", det, choice["note"], choice["tokens_in"],
                                choice["tokens_out"], choice["calls"])
        step = self.nav.step(pose)
        if step is None:
            self.visited.append(self.waypoint)
            self.waypoint = None
            self.spins_left = self.spin_steps - 1
            self.seen = [(int(round(pose.yaw_deg)) % 360, self._note(det))]
            return Decision(f"cw {self.spin_deg}", det, "arrived, scanning")
        return Decision(step, det, f"to waypoint {self.waypoint[0]:.0f},{self.waypoint[1]:.0f}")

    def _candidates(self, pose: Pose) -> List[Tuple[Tuple[float, float], float]]:
        """Reachable, unvisited waypoints as ((x, y), route distance in cm), nearest first."""
        rm = self.limits.room_map
        cells = _fence_cells(self.limits)
        if rm is None:
            cells = [c for c in cells if all(math.hypot(c[0] - v[0], c[1] - v[1]) > GRID_CM * 0.6
                                            for v in self.visited)]
            return sorted(((c, math.hypot(c[0] - pose.x, c[1] - pose.y)) for c in cells), key=lambda t: t[1])
        dist, _parent, _s, _g = rm.search((pose.x, pose.y), self.limits.margin + PLAN_INSET_CM, max(pose.z, 80.0))
        if not dist:
            return []
        xs, ys = rm._grid
        reach = [(xs[i], ys[j]) for (i, j) in dist]
        found = {}
        for c in cells:
            node = min(reach, key=lambda n: (n[0] - c[0]) ** 2 + (n[1] - c[1]) ** 2)
            if math.hypot(node[0] - c[0], node[1] - c[1]) > GRID_CM:
                continue  # that cell is inside furniture or unreachable
            if any(math.hypot(node[0] - v[0], node[1] - v[1]) <= GRID_CM * 0.6 for v in self.visited):
                continue
            found[node] = dist[(xs.index(node[0]), ys.index(node[1]))]
        return sorted(found.items(), key=lambda t: t[1])

    def _next_waypoint(self, pose: Pose) -> Optional[Tuple[float, float]]:
        self.visited.append((pose.x, pose.y))
        cands = self._candidates(pose)
        if not cands:
            return None
        self.last_choice = None
        if self.chooser is not None:
            idx = self.chooser(pose, cands, list(self.seen))
            if idx is not None:
                return cands[idx][0]
        return cands[0][0]


class LlmAgent:
    """ScanAgent plus a language model that picks WHERE to search next.

    The scan agent keeps all motion (45 deg scans, A* legs, centre-and-approach, claim). At each
    decision point (the start, and every finished scan without a claim) one text-only call gets the target,
    the room map, the pose, the visited waypoints, the reachable candidate waypoints and what perception
    saw during the last scan, and answers {"waypoint_id", "reason"}. An unusable answer falls back to the
    scan agent's nearest unvisited waypoint.
    """
    name = "llm"
    NEAR_CM = 130
    MAX_CANDIDATES = 16

    def __init__(self, limits: SafetyLimits, fallback: ScanAgent, usage: str = "vision.drone"):
        self.limits = limits
        self.scan = self.fallback = fallback
        self.usage = usage
        self.target = ""
        self.fallbacks = 0
        self.models: set = set()
        self.ai_calls = self.tokens_in = self.tokens_out = 0
        fallback.chooser = self._choose

    def start(self, target: str) -> None:
        self.target = target
        self.scan.start(target)

    def rejected(self) -> None:
        self.scan.rejected()

    def set_peers(self, peers) -> None:
        self.scan.set_peers(peers)

    def decide(self, frame, pose: Pose, blocked: Optional[str] = None) -> Decision:
        return self.scan.decide(frame, pose, blocked)

    def _near(self, x: float, y: float) -> str:
        rm = self.limits.room_map
        if rm is None:
            return ""
        close = sorted(((rm._dist(o, x, y), o.name) for o in rm.obstacles), key=lambda t: t[0])
        return ", ".join(f"{n} {d:.0f} cm" for d, n in close if d <= self.NEAR_CM)

    def _target_text(self) -> str:
        if self.target.isdigit():
            return (f"the other drone (recognised by its marker id {self.target}); it is hiding somewhere in the "
                    f"room, most likely behind tall furniture or in a far corner")
        return f"the {self.target}"

    def _prompt(self, pose: Pose, cands, seen) -> str:
        rm = self.limits.room_map
        lines = [
            f"You plan the search of a small indoor drone. Goal: find {self._target_text()}.",
            f"Room map: {rm.summary() if rm else 'unknown'}.",
            "x grows east, y grows north, origin at the south-west corner. Use commonsense about where things are "
            "(a sofa stands against a wall, a TV hangs on a wall, a plant stands in a corner, a hider hides behind "
            "tall furniture) and about what a drone could not see yet.",
            f"The drone is at x={pose.x:.0f} y={pose.y:.0f}, heading {pose.yaw_deg:.0f} deg (0 = north, clockwise).",
            "Already searched (full 360 deg scan done): " + (
                "; ".join(f"({x:.0f},{y:.0f})" for x, y in self.scan.visited) or "nothing yet"),
            "What the camera saw during the last scan (heading: note): " + (
                "; ".join(f"{h}: {n}" for h, n in seen if n) or "nothing relevant"),
            "Candidate waypoints (id, x, y, route distance, near):"]
        for i, (xy, d) in enumerate(cands):
            lines.append(f"  {i}: x={xy[0]:.0f} y={xy[1]:.0f} route={d:.0f} cm near: {self._near(*xy) or 'open floor'}")
        lines.append('Pick the ONE waypoint most likely to show the target next. Answer JSON only: '
                     '{"waypoint_id": <id>, "reason": "short"}')
        return "\n".join(lines)

    def _choose(self, pose: Pose, cands, seen) -> Optional[int]:
        """Index into cands, or None to let the scan agent take its nearest unvisited waypoint."""
        from shared.src.lib.ai import gateway
        shown = cands[:self.MAX_CANDIDATES]
        res = gateway.complete(self.usage, self._prompt(pose, shown, seen), max_tokens=300)
        u = res.get("usage") or {}
        tin, tout = int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
        self.ai_calls += 1
        self.tokens_in += tin
        self.tokens_out += tout
        if res.get("model"):
            self.models.add(f"{res.get('provider_used', '?')}/{res['model']}")
        data = parse_json_object(res.get("content", "")) if res.get("success") else None
        try:
            idx = int((data or {}).get("waypoint_id"))
        except (TypeError, ValueError):
            idx = -1
        if not 0 <= idx < len(shown):
            self.fallbacks += 1
            why = res.get("error") or f"unusable answer {str(res.get('content', ''))[:60]!r}"
            self.scan.last_choice = {"calls": 1, "tokens_in": tin, "tokens_out": tout,
                                     "note": f"LLM planner failed ({why}); nearest unvisited waypoint instead"}
            return None
        xy = shown[idx][0]
        self.scan.last_choice = {"calls": 1, "tokens_in": tin, "tokens_out": tout,
                                 "note": f"LLM picks waypoint {idx} ({xy[0]:.0f},{xy[1]:.0f}): "
                                         f"{str((data or {}).get('reason', ''))[:160]}"}
        return idx


class HiderAgent:
    name = "hider"

    def __init__(self, limits: SafetyLimits, seeker_start: Pose, hide_spots: Optional[List[Tuple[float, float]]] = None,
                 start: Optional[Pose] = None):
        self.limits = limits
        self.seeker_start = seeker_start
        self.start_xy = (start.x, start.y) if start else None
        self.nav = Navigator(limits)
        self.spot = self._choose(hide_spots)
        self.pending = True
        self.ai_calls = self.tokens_in = self.tokens_out = 0

    def _clamp(self, x: float, y: float) -> Tuple[float, float]:
        L = self.limits
        return (min(max(x, L.margin), L.room_w - L.margin), min(max(y, L.margin), L.room_d - L.margin))

    def _choose(self, hide_spots) -> Tuple[float, float]:
        L = self.limits
        if hide_spots:
            cands = [self._clamp(*s) for s in hide_spots]
        else:
            cands = [(L.margin, L.margin), (L.room_w - L.margin, L.margin),
                     (L.margin, L.room_d - L.margin), (L.room_w - L.margin, L.room_d - L.margin)]
        if L.room_map is not None and self.start_xy is not None:
            reach = L.room_map.reachable_nodes(self.start_xy, L.margin + PLAN_INSET_CM)
            snapped = []
            for c in cands:
                node = min(reach, key=lambda n: (n[0] - c[0]) ** 2 + (n[1] - c[1]) ** 2) if reach else None
                if node and math.hypot(node[0] - c[0], node[1] - c[1]) <= GRID_CM:
                    snapped.append(node)
            cands = snapped or cands
        s = self.seeker_start

        def in_view(c) -> bool:
            diff = (bearing_deg(s, *c) - s.yaw_deg + 540) % 360 - 180
            return abs(diff) < FOV_DEG / 2 + 10

        def dist(c) -> float:
            return math.hypot(c[0] - s.x, c[1] - s.y)

        hidden = [c for c in cands if not in_view(c) and dist(c) > 150]
        return max(hidden or cands, key=dist)

    def start(self, target: str = "") -> None:
        self.pending = True

    def set_peers(self, peers) -> None:
        self.nav.peers = peers

    def rejected(self) -> None:
        pass

    def decide(self, frame, pose: Pose, blocked: Optional[str] = None) -> Decision:
        if self.pending:
            self.pending = False
            self.nav.set_goal(pose, self.spot)
        elif blocked:
            self.nav.blocked(pose)
        else:
            self.nav.clear()
        if self.nav.failed:
            return Decision("hold", None, "no route to the hiding spot, holding here")
        step = self.nav.step(pose)
        if step is None:
            return Decision("hold", None, f"at hiding spot {self.spot[0]:.0f},{self.spot[1]:.0f}")
        return Decision(step, None, f"to hiding spot {self.spot[0]:.0f},{self.spot[1]:.0f}")
