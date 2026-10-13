"""
Mission Pad support for the Tello Talent.

The plain Tello has no GPS and no real position sensing. The Tello
Talent's downward camera recognises ``Mission Pad`` markers (ArUco-style
ids 1-8) and reports the offset from the pad in the state datagram:
``mid`` (id), ``mx``/``my``/``mz`` (centimetres, in the Tello's body
frame). When a pad is detected, the controller can snap the
dead-reckoned pose to ``(known_pad_position + reported_offset)`` so the
logged position is no longer drifting.

This is room-specific. A room is a list of pads with known world
coordinates. The mapping ``pad_id -> (x, y, z)`` is in centimetres and
matches the SafetyGuard room layout (so a guard reference point and a
pad share the same coordinate system).

If the Tello isn't a Talent (no ``mid``/``mx``/``my``/``mz`` in the
state datagram), or no pads are configured, the snap is a no-op and
``pose_source`` stays as ``"dead_reckoned"``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class MissionPadConfig:
    """Known positions of every Mission Pad in the room, keyed by id (1-8)."""
    pads: Dict[int, Tuple[float, float, float]] = field(default_factory=dict)

    def position_of(self, pad_id: int) -> Optional[Tuple[float, float, float]]:
        return self.pads.get(int(pad_id))


def is_mission_pad_visible(state: Dict[str, Any]) -> bool:
    """True if the state datagram carries a pad id and the three offsets."""
    if not isinstance(state, dict):
        return False
    if state.get("mid") is None:
        return False
    return all(k in state for k in ("mx", "my", "mz"))


def snap_pose(
    state: Dict[str, Any],
    current_pose: Any,
    config: MissionPadConfig,
) -> Optional[Any]:
    """Return a new pose snapped to ``config.pads[mid] + (mx, my, mz)``.

    Returns ``None`` if the snap is not applicable (no pad, unknown pad,
    or no current pose to construct the replacement).
    """
    if current_pose is None:
        return None
    if not is_mission_pad_visible(state):
        return None
    try:
        pad_id = int(state["mid"])
        mx = float(state["mx"])
        my = float(state["my"])
        mz = float(state["mz"])
    except (TypeError, ValueError):
        return None
    pad_pos = config.position_of(pad_id)
    if pad_pos is None:
        return None
    px, py, pz = pad_pos
    # Replace fields on a copy of the current pose. The dead-reckoned pose
    # in the project (shared/src/lib/drone/sim/world.py) is a dataclass-
    # like object with x/y/z/yaw_deg; fall back to attribute names with
    # a dict shape if a different pose type is passed.
    new_x = px + mx
    new_y = py + my
    new_z = pz + mz
    yaw = getattr(current_pose, "yaw_deg", None)
    if yaw is None and isinstance(current_pose, dict):
        yaw = current_pose.get("yaw", 0.0)
    yaw = float(yaw if yaw is not None else 0.0)

    if hasattr(current_pose, "__dict__") and not isinstance(current_pose, dict):
        # dataclass-like: build a new instance. Tello's world.Pose is the
        # canonical shape; if a different class is passed and we can't
        # construct it, return None and let the caller keep the current
        # pose.
        cls = type(current_pose)
        try:
            return cls(new_x, new_y, new_z, yaw)
        except Exception:
            return None
    if isinstance(current_pose, dict):
        out = dict(current_pose)
        out["x"] = new_x
        out["y"] = new_y
        out["z"] = new_z
        out["yaw"] = yaw
        return out
    return None
