"""
Mission loader and the built-in sidewalk-100m scenario.

A mission is a scripted sequence of ``MobilityMission`` definitions.
This module owns:

- the canonical sidewalk-100m scenario (3 curbs, 1 ramp, 2 obstacles,
  destination),
- a deterministic seed→scenario mapping (same seed ⇒ same scenario,
  different seed ⇒ a different randomised scenario),
- a tiny ``MissionScript`` dataclass that the fake adapter executes.

PR 2's Gazebo adapter will read the same ``MissionScript`` format, so the
sidewalk scenario is portable across adapters.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import MobilityMission


# ---------------------------------------------------------------------------
# Scripted elements — what the fake (and future Gazebo) adapter encounters.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ScriptedCurb:
    position_x: float
    position_y: float
    width_m: float = 0.15       # height of the curb (m)
    speed_factor: float = 0.3   # rover slows to 30% over a curb


@dataclass(frozen=True)
class ScriptedRamp:
    position_x: float
    position_y: float
    width_m: float = 1.5        # length of the ramp (m)
    speed_factor: float = 1.2   # ramps are flat; model speed bump from incline


@dataclass(frozen=True)
class ScriptedObstacle:
    position_x: float
    position_y: float
    radius_m: float = 0.4
    reroutable: bool = True     # True = adapter can go around; False = forces stop


@dataclass(frozen=True)
class ScriptedDestination:
    position_x: float
    position_y: float
    tolerance_m: float = 1.0    # how close counts as "arrived"


@dataclass(frozen=True)
class MissionScript:
    """A scripted scenario. Reusable across adapters.

    ``length_m`` is the total length of the sidewalk; positions are
    measured along the x axis (the rover travels in +x). The y axis is
    used for obstacles that force a lateral detour.
    """

    scenario_id: str
    length_m: float
    curbs: Tuple[ScriptedCurb, ...]
    ramps: Tuple[ScriptedRamp, ...]
    obstacles: Tuple[ScriptedObstacle, ...]
    destination: ScriptedDestination
    seed: int = 0
    metadata: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.length_m <= 0:
            raise ValueError(f"length_m must be > 0 (got {self.length_m})")
        if not self.destination:
            raise ValueError("mission script must have a destination")
        # Sanity: every scripted element must lie within the sidewalk.
        for curb in self.curbs:
            if not (0 <= curb.position_x <= self.length_m):
                raise ValueError(
                    f"curb at x={curb.position_x} outside [0, {self.length_m}]"
                )
        for ramp in self.ramps:
            if not (0 <= ramp.position_x <= self.length_m):
                raise ValueError(
                    f"ramp at x={ramp.position_x} outside [0, {self.length_m}]"
                )
        for obstacle in self.obstacles:
            if not (0 <= obstacle.position_x <= self.length_m):
                raise ValueError(
                    f"obstacle at x={obstacle.position_x} outside "
                    f"[0, {self.length_m}]"
                )


# ---------------------------------------------------------------------------
# Built-in scenarios
# ---------------------------------------------------------------------------
def sidewalk_100m(seed: int = 0) -> MissionScript:
    """The canonical 100 m sidewalk mission.

    Three curbs at 20 m, 50 m, 80 m. One ramp between 35 m and 36.5 m
    (the ramp's position_x is its start). Two obstacles at 45 m and
    70 m — both reroutable. Destination at 100 m.

    The seed parameter randomises the lateral offset of each obstacle
    so two seeded runs are visibly different (the obstacles' y
    components shift ±0.3 m). The canonical mission is always
    passable: the fake detours around every obstacle.

    Non-reroutable-obstacle behaviour is exercised by
    :mod:`test_fake_adapter` with a custom script.
    """
    rng = random.Random(seed)
    obstacle_1_y = 0.0 + rng.uniform(-0.2, 0.2)
    obstacle_2_y = 0.0 + rng.uniform(-0.2, 0.2)
    return MissionScript(
        scenario_id="sidewalk_100m",
        length_m=100.0,
        curbs=(
            ScriptedCurb(position_x=20.0, position_y=0.0),
            ScriptedCurb(position_x=50.0, position_y=0.0),
            ScriptedCurb(position_x=80.0, position_y=0.0),
        ),
        ramps=(ScriptedRamp(position_x=35.0, position_y=0.0),),
        obstacles=(
            ScriptedObstacle(
                position_x=45.0,
                position_y=obstacle_1_y,
                radius_m=0.4,
                reroutable=True,
            ),
            ScriptedObstacle(
                position_x=70.0,
                position_y=obstacle_2_y,
                radius_m=0.4,
                reroutable=True,
            ),
        ),
        destination=ScriptedDestination(position_x=100.0, position_y=0.0),
        seed=seed,
        metadata={"description": "100m sidewalk: 3 curbs, 1 ramp, 2 obstacles"},
    )


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
_BUILTINS: Dict[str, callable] = {
    "sidewalk_100m": sidewalk_100m,
}


def load_script(mission: MobilityMission) -> MissionScript:
    """Resolve a ``MobilityMission`` to a ``MissionScript``.

    PR 1 supports the built-in ``sidewalk_100m`` scenario only. PR 2+
    will extend this with user-defined scenarios stored in the DB.
    Unknown scenario ids raise ``ValueError`` so the API layer can map
    them to a 400.
    """
    builder = _BUILTINS.get(mission.scenario_id)
    if builder is None:
        raise ValueError(
            f"unknown scenario {mission.scenario_id!r}; "
            f"built-ins are {sorted(_BUILTINS)}"
        )
    return builder(seed=mission.seed)


def list_builtin_scenarios() -> List[str]:
    """Names of all built-in scenarios. PR 1 has exactly one."""
    return sorted(_BUILTINS)