"""
Drone safety guards, applied before every SDK command (games and the platform controller).

The guard dead-reckons the drone pose from its start spot with Tello semantics (yaw 0 = +y,
clockwise positive, forward = along yaw, right = yaw + 90) and refuses or clips any command that
would leave the geofence, exceed the max height, close in on a peer, or fly on a low battery.
check() never sends anything; the caller sends cmd_to_send and then calls apply() with it.
"""

import math
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .roommap import CLEARANCE_CM, RoomMap

from .sim.world import Pose

MIN_MOVE_CM = 20  # Tello refuses moves below 20 cm
MAX_MOVE_CM = 500
MIN_FLY_Z = 30  # never descend below this while flying (landing is a separate command)
TAKEOFF_Z = 80
RC_MAX = 60  # joystick (`rc`) channel cap, of the SDK's -100..100
YAW_FRESH_S = 0.3  # trust the IMU yaw only this long after the last command finished
FENCE_SLACK_CM = 3  # dead reckoning is rounded to whole cm; standing on the fence line is not a violation


@dataclass
class SafetyLimits:
    room_w: float = 600
    room_d: float = 500
    margin: float = 50
    max_h: float = 150
    min_sep: float = 100
    bat_takeoff: int = 40
    bat_land: int = 20
    cmd_timeout_s: float = 10
    takeoff_timeout_s: float = 20
    room_map: Optional[RoomMap] = None  # obstacles; a dict (JSON from the controller `configure`) is converted

    def __post_init__(self):
        if isinstance(self.room_map, dict):
            self.room_map = RoomMap.from_dict(self.room_map)


_MOVES = {"forward": 0.0, "right": 90.0, "back": 180.0, "left": 270.0}


def _heading(yaw_deg: float, offset_deg: float = 0.0) -> Tuple[float, float]:
    a = math.radians(yaw_deg + offset_deg)
    return math.sin(a), math.cos(a)


def parse_command(cmd: str) -> Tuple[str, Optional[int]]:
    parts = cmd.strip().split()
    if not parts:
        return "", None
    try:
        return parts[0].lower(), int(float(parts[1])) if len(parts) > 1 else None
    except ValueError:
        return parts[0].lower(), None


class SafetyGuard:
    def __init__(self, limits: SafetyLimits, start_pose: Pose,
                 peers: Optional[Callable[[], List[Pose]]] = None,
                 telemetry: Optional[Callable[[], dict]] = None):
        self.limits = limits
        self.pose = Pose(start_pose.x, start_pose.y, start_pose.z, start_pose.yaw_deg)
        self.peers = peers or (lambda: [])
        self.telemetry = telemetry or (lambda: {})
        self._yaw_offset: Optional[float] = None
        self._applied_at = 0.0

    @property
    def flying(self) -> bool:
        return self.pose.z > 5

    def inside(self, x: float, y: float) -> bool:
        m, L = self.limits.margin, self.limits
        k = FENCE_SLACK_CM
        return m - k <= x <= L.room_w - m + k and m - k <= y <= L.room_d - m + k

    def sync_yaw(self, tel: dict) -> None:
        """The IMU yaw (state `yaw`, zero where the drone was powered on) is far better than the sum of the
        commanded turns, which drift a few percent each. Anchor it to the known start heading while landed."""
        yaw = tel.get("yaw")
        if yaw is None:
            return
        if self._yaw_offset is None:
            self._yaw_offset = self.pose.yaw_deg - yaw
        elif self.flying and time.time() - self._applied_at >= YAW_FRESH_S:
            # (the state datagram can be up to 100 ms old: right after a turn it still shows the old heading)
            self.pose.yaw_deg = (yaw + self._yaw_offset) % 360

    def check(self, cmd: str) -> Tuple[bool, Optional[str], str]:
        """(allowed, cmd_to_send, reason). Not allowed with cmd_to_send == 'land' means: land now."""
        verb, n = parse_command(cmd)
        lim = self.limits
        tel = self.telemetry() or {}
        self.sync_yaw(tel)
        bat = tel.get("bat")
        if verb in ("land", "emergency", "stop", "command", "streamon", "streamoff") or cmd.strip().endswith("?"):
            return True, cmd, "ok"
        if verb == "rc":
            return self._check_rc(cmd, tel)
        if verb == "takeoff":
            if self.flying:
                return False, None, "already flying"
            if bat is not None and bat < lim.bat_takeoff:
                return False, None, f"battery {bat}% below takeoff floor {lim.bat_takeoff}%"
            return True, cmd, "ok"
        if verb not in ("up", "down", "cw", "ccw", *_MOVES):
            return False, None, f"command '{verb}' not allowed by guard"
        if not self.flying:
            return False, None, "not flying"
        if bat is not None and bat <= lim.bat_land:
            return False, "land", f"battery {bat}% at land floor {lim.bat_land}%"
        if n is None:
            return False, None, "missing argument"
        if verb in ("cw", "ccw"):
            if not 1 <= n <= 360:
                return False, None, "rotation out of range"
            return True, cmd, "ok"
        if n < MIN_MOVE_CM:
            return False, None, f"move {n} cm below the {MIN_MOVE_CM} cm minimum"
        n = min(n, MAX_MOVE_CM)
        if verb in ("up", "down"):
            return self._check_vertical(verb, n, tel)
        return self._check_horizontal(verb, n)

    def _check_rc(self, cmd: str, tel: dict):
        """Joystick `rc lr fb ud yaw`. Sticks have no distance, so the geofence and the dead-reckoned
        pose cannot follow them: the guard caps every channel at RC_MAX, keeps the height between
        MIN_FLY_Z and max_h from the measured height, and lands at the battery floor. Centred
        sticks (`rc 0 0 0 0`) are always allowed: that is the stop."""
        parts = cmd.split()
        try:
            lr, fb, ud, yaw = (int(float(v)) for v in parts[1:5])
        except ValueError:
            return False, None, "rc needs four numbers"
        if len(parts) != 5:
            return False, None, "rc needs four numbers"
        if (lr, fb, ud, yaw) == (0, 0, 0, 0):
            return True, "rc 0 0 0 0", "ok"
        if not self.flying:
            return False, None, "not flying"
        bat = tel.get("bat")
        if bat is not None and bat <= self.limits.bat_land:
            return False, "land", f"battery {bat}% at land floor {self.limits.bat_land}%"
        clip = lambda v: max(-RC_MAX, min(RC_MAX, v))  # noqa: E731
        lr, fb, ud, yaw = clip(lr), clip(fb), clip(ud), clip(yaw)
        h = float(tel.get("h", self.pose.z) or 0)
        reason = "ok"
        if ud > 0 and h >= self.limits.max_h:
            ud, reason = 0, f"max height {self.limits.max_h:g} cm reached"
        elif ud < 0 and h <= MIN_FLY_Z:
            ud, reason = 0, f"min flying height {MIN_FLY_Z} cm reached"
        return True, f"rc {lr} {fb} {ud} {yaw}", reason

    def _check_vertical(self, verb: str, n: int, tel: dict):
        lim = self.limits
        if verb == "up":
            z = max(self.pose.z, float(tel.get("h", 0) or 0))
            room = lim.max_h - z
            if room < MIN_MOVE_CM:
                return False, None, f"max height {lim.max_h:g} cm reached"
            if n > room:
                return True, f"up {int(room)}", f"clipped to max height {lim.max_h:g} cm"
            return True, f"up {n}", "ok"
        room = self.pose.z - MIN_FLY_Z
        if room < MIN_MOVE_CM:
            return False, None, f"min flying height {MIN_FLY_Z} cm reached"
        if n > room:
            return True, f"down {int(room)}", f"clipped to min flying height {MIN_FLY_Z} cm"
        return True, f"down {n}", "ok"

    def _check_horizontal(self, verb: str, n: int):
        p = self.pose
        dx, dy = _heading(p.yaw_deg, _MOVES[verb])
        tx, ty = p.x + dx * n, p.y + dy * n
        d = float(n)
        reason = "ok"
        if not self.inside(tx, ty):
            if not self.inside(p.x, p.y):
                return False, None, "geofence: start outside the fence and move leaves it"
            d = self._clip_distance(p.x, p.y, dx, dy, n)
            if d < MIN_MOVE_CM:
                return False, None, "geofence: blocked"
            d = math.floor(d)
            reason = f"clipped to {int(d)} cm by the geofence"
            tx, ty = p.x + dx * d, p.y + dy * d
        rm = self.limits.room_map
        if rm is not None:
            hit = rm.first_hit(p.x, p.y, tx, ty, CLEARANCE_CM, p.z)
            if hit is not None and hit[0] < d:
                d = math.floor(hit[0])
                if d < MIN_MOVE_CM:
                    return False, None, f"obstacle: {hit[1].name} in the way"
                reason = f"clipped to {int(d)} cm before the {hit[1].name}"
                tx, ty = p.x + dx * d, p.y + dy * d
        for peer in self.peers():
            if peer.z <= 5:
                continue  # landed peers are not in the way of the flight plan
            now = math.hypot(peer.x - p.x, peer.y - p.y)
            new = math.hypot(peer.x - tx, peer.y - ty)
            if new < self.limits.min_sep and new < now:
                return False, None, f"separation: would be {new:.0f} cm from the other drone"
        return True, f"{verb} {int(d)}", reason

    def _clip_distance(self, x: float, y: float, dx: float, dy: float, n: float) -> float:
        L = self.limits
        t = n
        for pos, dv, lo, hi in ((x, dx, L.margin, L.room_w - L.margin), (y, dy, L.margin, L.room_d - L.margin)):
            if dv > 1e-9:
                t = min(t, (hi - pos) / dv)
            elif dv < -1e-9:
                t = min(t, (lo - pos) / dv)
        return max(t, 0.0)

    def apply(self, cmd_sent: str) -> None:
        self._applied_at = time.time()
        verb, n = parse_command(cmd_sent)
        p = self.pose
        if verb == "takeoff":
            p.z = TAKEOFF_Z
        elif verb in ("land", "emergency"):
            p.z = 0
        elif n is None:
            return
        elif verb == "cw":
            p.yaw_deg = (p.yaw_deg + n) % 360
        elif verb == "ccw":
            p.yaw_deg = (p.yaw_deg - n) % 360
        elif verb == "up":
            p.z += n
        elif verb == "down":
            p.z = max(0, p.z - n)
        elif verb in _MOVES:
            dx, dy = _heading(p.yaw_deg, _MOVES[verb])
            p.x += dx * n
            p.y += dy * n
