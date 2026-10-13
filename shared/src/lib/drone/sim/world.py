"""Simulator world: room, furniture, poses and start/hide spots. Units are cm, origin bottom-left corner."""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

Color = Tuple[int, int, int]  # BGR

# One saturated, distinct colour per class (perception.SimColorDetector matches on these hues).
CLASS_COLORS: Dict[str, Color] = {
    "sofa": (30, 30, 220),     # red
    "tv": (220, 80, 0),        # blue
    "plant": (0, 190, 0),      # green
    "chair": (0, 215, 235),    # yellow
    "table": (210, 0, 210),    # magenta
}


@dataclass
class SimObject:
    name: str
    cls: str
    x: float          # centre on the floor
    y: float
    w: float          # extent along x
    d: float          # extent along y
    h: float          # height
    color: Color
    z0: float = 0.0   # bottom above the floor

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        return self.x - self.w / 2, self.x + self.w / 2, self.y - self.d / 2, self.y + self.d / 2


@dataclass
class Room:
    width: float = 600.0
    depth: float = 500.0
    height: float = 250.0
    objects: List[SimObject] = field(default_factory=list)


@dataclass
class Pose:
    x: float
    y: float
    z: float
    yaw_deg: float  # 0 = +y (north), clockwise positive like Tello cw

    def copy(self) -> "Pose":
        return Pose(self.x, self.y, self.z, self.yaw_deg)


def default_room() -> Room:
    """Living room split by a tall bookshelf divider (gap on the east side).

    South half (start spots): the chair only. North half, hidden from the south behind the divider: the sofa
    and, in the north-west corner (reached through the gap, then west along the corridor between divider and
    sofa), the TV on the west wall, the plant and the table. The start spots face the south wall.
    """
    c = CLASS_COLORS
    return Room(objects=[
        SimObject("shelf", "shelf", 190, 280, 380, 30, 200, (60, 90, 120)),
        SimObject("sofa", "sofa", 225, 455, 150, 70, 80, c["sofa"]),
        SimObject("tv", "tv", 8, 380, 14, 70, 60, c["tv"], z0=35),
        SimObject("plant", "plant", 40, 470, 40, 40, 100, c["plant"]),
        SimObject("chair", "chair", 430, 160, 50, 50, 90, c["chair"]),
        SimObject("table", "table", 105, 470, 60, 60, 60, c["table"]),
    ])


START_SPOTS: Dict[int, Pose] = {
    1: Pose(100, 100, 0, 180),  # facing the south wall, 1 m away
    2: Pose(500, 100, 0, 180),
}

# Hiding spots in the north half, behind the divider as seen from the south and from the start spots.
HIDE_SPOTS: List[Tuple[float, float]] = [(350, 430), (400, 380), (100, 340), (540, 350)]
