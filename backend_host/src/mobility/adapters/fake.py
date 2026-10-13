"""
``FakeMobilityController`` — the deterministic in-process rover.

PR 1 ships this adapter only. PR 2 introduces a Gazebo / ROS 2 adapter
that reads the same :class:`MissionScript` and satisfies the same
:class:`MobilityController` Protocol — that is how the contract tests
will pin cross-adapter behaviour.

Determinism
-----------
A run is parameterised by ``seed`` (via :func:`missions.sidewalk_100m`).
Given the same seed:

- the obstacle's lateral offset is identical,
- the observation trace is identical,
- the final position is identical,
- the result is identical (``pass`` / ``needs_review`` / ``fail``).

Different seeds produce observably different traces (verified by hashed
trace comparison in :mod:`test_fake_adapter`).

Behaviour
---------
- The rover moves forward at the commanded linear velocity for
  ``cmd.duration_s`` of simulated time, advancing along +x.
- Curbs slow the rover (``speed_factor = 0.3``) for the duration of the
  curb's footprint.
- Ramps speed it up (``speed_factor = 1.2``).
- The reroutable obstacle forces a small lateral detour (+0.3 m in y).
- The non-reroutable obstacle forces a stop; the run ends with
  ``fail`` unless the operator clears the obstacle.
- A sensor dropout fault (injectable via ``faults=``) marks the run
  ``needs_review``.
- Heartbeat loss (injectable via ``heartbeat_alive=False``) forces the
  gate to issue a zero-motion pulse; the run ends ``fail``.

Camera / measure
----------------
``camera()`` writes a 1×1 black PNG to a temp path and returns the
path. ``measure()`` returns the rover's distance from the destination
(0 at destination).
"""
from __future__ import annotations

import hashlib
import os
import struct
import tempfile
import time
import zlib
from typing import List, Optional

from ..config import MobilityConfig
from ..controller import BaseMobilityController
from ..missions import MissionScript, ScriptedCurb, ScriptedObstacle, ScriptedRamp
from ..models import MobilityResult, ResultStatus, RoverCommand, RoverState
from ..safety import SafetyGate


# ---------------------------------------------------------------------------
# PNG writer — 1×1 black image. No external dependency on PIL.
# ---------------------------------------------------------------------------
def _write_black_png(path: str) -> str:
    """Write a 1×1 black PNG to ``path``. Returns the path.

    The PNG signature + IHDR + IDAT + IEND are produced inline. PR 2
    will replace this with a real camera frame; for PR 1 the
    "I have a camera" placeholder is enough.
    """
    signature = b"\x89PNG\r\n\x1a\n"

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(
            ">I", crc
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)  # 1×1, 8-bit gray
    raw = b"\x00\x00"  # filter byte + 1 pixel
    idat = zlib.compress(raw)
    with open(path, "wb") as fh:
        fh.write(signature)
        fh.write(chunk(b"IHDR", ihdr))
        fh.write(chunk(b"IDAT", idat))
        fh.write(chunk(b"IEND", b""))
    return path


# ---------------------------------------------------------------------------
# The fake adapter
# ---------------------------------------------------------------------------
class FakeMobilityController(BaseMobilityController):
    """Deterministic fake — see module docstring."""

    adapter_id: str = "fake"

    def __init__(
        self,
        config: MobilityConfig,
        gate: SafetyGate,
        script: MissionScript,
        *,
        heartbeat_alive: bool = True,
        faults: Optional[List[str]] = None,
        clock=None,
    ) -> None:
        super().__init__(config=config, gate=gate, initial_position=(0.0, 0.0))
        self._script = script
        self._heartbeat_alive = heartbeat_alive
        self._faults = set(faults or [])
        self._clock = clock or time.time
        self._max_speed_factor = 1.0      # affected by curbs/ramps
        self._active_obstacle_detour: Optional[float] = None
        self._stopped = False
        self._started_at_ms = int(time.time() * 1000)
        self._final_status = ResultStatus.PASS
        self._final_reason_code = ""
        self._final_reason = ""
        self._distance_traveled_m = 0.0
        self._hit_obstacle = False
        self._completed_obstacles = set()
        self._initial_observation_count = 0
        self._completed_curbs: set = set()
        self._completed_ramps: set = set()
        self._heartbeat_lost_seen = False

    # ---- connect / heartbeat --------------------------------------------

    def connect(self) -> bool:
        ok = super().connect()
        if ok:
            self._record_observation(
                timestamp_ms=int(self._clock() * 1000),
                position=(0.0, 0.0),
                heading=0.0,
                event="connected",
            )
        return ok

    def heartbeat(self) -> None:
        if not self._heartbeat_alive:
            # Simulate a stale adapter — the gate will treat this as
            # HEARTBEAT_LOST on the next non-stop command.
            self._heartbeat_lost_seen = True
            self._ctx.last_heartbeat_ms = 0
            if not self._stopped:
                self._stopped = True
                self._set_final(
                    ResultStatus.FAIL,
                    "HEARTBEAT_LOST",
                    "adapter heartbeat stopped responding",
                )
            return
        super().heartbeat()

    # ---- _execute_command: the simulated motion -----------------------

    def _execute_command(self, cmd: RoverCommand) -> None:
        if self._stopped:
            return
        # Heartbeat on every step: if the fake is "alive" this refreshes
        # the timestamp; if not, this marks the run as HEARTBEAT_LOST
        # and stops further commands.
        self.heartbeat()
        if self._stopped:
            return
        now_ms = int(self._clock() * 1000)

        # Update the simulated position based on the commanded motion
        # for the duration. Linear is along +x (the rover drives
        # forward); angular temporarily nudges the heading.
        prev = self._ctx.current_position
        effective_speed = (
            cmd.linear_velocity_mps * self._max_speed_factor
        )
        distance = effective_speed * cmd.duration_s
        new_x = prev[0] + distance
        new_y = prev[1]

        # Curbs: slow the rover if we're crossing one. Set the speed
        # factor for the duration of the curb's footprint; restore
        # after the rover exits. Each curb fires exactly once.
        for curb in self._script.curbs:
            if curb in self._completed_curbs:
                continue
            if (
                prev[0] < curb.position_x <= new_x
                or prev[0] == curb.position_x
            ):
                self._completed_curbs.add(curb)
                if "sensor_dropout" in self._faults:
                    self._set_final(
                        ResultStatus.NEEDS_REVIEW,
                        "SENSOR_DROPOUT",
                        "sensor dropout over curb",
                    )
                self._max_speed_factor = min(
                    self._max_speed_factor, curb.speed_factor
                )
                self._record_observation(
                    timestamp_ms=now_ms,
                    position=(new_x, new_y),
                    heading=0.0,
                    event=f"curb:{curb.position_x}",
                )
                # Restore the speed factor after the curb's footprint.
                self._max_speed_factor = 1.0
                break

        # Ramps: speed up the rover for the ramp's footprint.
        for ramp in self._script.ramps:
            if ramp in self._completed_ramps:
                continue
            if prev[0] < ramp.position_x <= new_x:
                self._completed_ramps.add(ramp)
                self._max_speed_factor = ramp.speed_factor
                self._record_observation(
                    timestamp_ms=now_ms,
                    position=(new_x, new_y),
                    heading=0.0,
                    event=f"ramp:{ramp.position_x}",
                )
                self._max_speed_factor = 1.0
                break

        # Obstacles: reroutable → lateral detour; non-reroutable → stop.
        for obstacle in self._script.obstacles:
            if (
                obstacle.position_x - obstacle.radius_m
                <= new_x
                <= obstacle.position_x + obstacle.radius_m
                and obstacle not in self._completed_obstacles
            ):
                self._completed_obstacles.add(obstacle)
                if obstacle.reroutable:
                    new_y = obstacle.position_y + 0.5
                    self._record_observation(
                        timestamp_ms=now_ms,
                        position=(new_x, new_y),
                        heading=0.0,
                        event=f"obstacle_reroute:{obstacle.position_x}",
                    )
                else:
                    self._hit_obstacle = True
                    self._stopped = True
                    self._set_final(
                        ResultStatus.FAIL,
                        "OBSTACLE_STOP",
                        f"non-reroutable obstacle at x={obstacle.position_x}",
                    )
                    self._record_observation(
                        timestamp_ms=now_ms,
                        position=(prev[0], prev[1]),
                        heading=0.0,
                        event=f"obstacle_stop:{obstacle.position_x}",
                    )
                    return
                break

        # Destination: stop and mark PASS when within tolerance. The
        # PASS verdict can be overridden by a sticky NEEDS_REVIEW
        # (e.g. sensor_dropout set above), and heartbeat loss promotes
        # the run to FAIL/NEEDS_REVIEW.
        dest = self._script.destination
        if abs(new_x - dest.position_x) <= dest.tolerance_m:
            self._stopped = True
            self._set_final(
                ResultStatus.PASS,
                "DESTINATION_REACHED",
                f"reached destination at x={dest.position_x}",
            )
            self._record_observation(
                timestamp_ms=now_ms,
                position=(new_x, new_y),
                heading=0.0,
                event="destination_reached",
            )
            self._distance_traveled_m = new_x
            self._ctx.current_position = (new_x, new_y)
            return

        # Cap at the script's end.
        if new_x >= self._script.length_m:
            self._stopped = True
            self._set_final(
                ResultStatus.FAIL,
                "END_OF_SCRIPT",
                f"end of sidewalk at x={self._script.length_m}",
            )
            self._distance_traveled_m = self._script.length_m
            self._ctx.current_position = (self._script.length_m, new_y)
            return

        self._distance_traveled_m = new_x
        self._ctx.current_position = (new_x, new_y)
        self._record_observation(
            timestamp_ms=now_ms,
            position=(new_x, new_y),
            heading=0.0,
        )

    # ---- sensor methods ------------------------------------------------

    def camera(self) -> Optional[str]:
        """Return a path to a 1×1 black PNG (placeholder)."""
        tmp = tempfile.NamedTemporaryFile(
            prefix="mobility_camera_", suffix=".png", delete=False
        )
        tmp.close()
        return _write_black_png(tmp.name)

    def measure(self) -> float:
        """Distance from the rover's current position to the destination."""
        pos = self._ctx.current_position
        dest = self._script.destination
        dx = pos[0] - dest.position_x
        dy = pos[1] - dest.position_y
        return (dx * dx + dy * dy) ** 0.5

    # ---- result accessor -----------------------------------------------

    def build_result(self, mission_id: str, scenario_id: str) -> MobilityResult:
        """Compose a MobilityResult from the run's accumulated state."""
        finished_at_ms = int(self._clock() * 1000)
        return MobilityResult(
            mission_id=mission_id,
            scenario_id=scenario_id,
            status=self._final_status,
            started_at_ms=self._started_at_ms,
            finished_at_ms=finished_at_ms,
            reason=self._final_reason,
            reason_code=self._final_reason_code,
            final_position_x=self._ctx.current_position[0],
            final_position_y=self._ctx.current_position[1],
            distance_traveled_m=self._distance_traveled_m,
            observations=tuple(
                self.observations[self._initial_observation_count:]
            ),
            safety_audit_ids=tuple(d.audit_id for d in self.audit_log),
            adapter_id=self.adapter_id,
        )

    # ---- helpers -------------------------------------------------------

    def _set_final(
        self, status: ResultStatus, code: str, reason: str
    ) -> None:
        """Status stickiness rules.

        - FAIL sticks: nothing else can override a FAIL.
        - NEEDS_REVIEW sticks against PASS but FAIL can override it.
        - PASS only fires if nothing else has fired.
        """
        if self._final_status == ResultStatus.FAIL:
            return
        if self._final_status == ResultStatus.NEEDS_REVIEW and status == ResultStatus.PASS:
            return
        self._final_status = status
        self._final_reason_code = code
        self._final_reason = reason

    def trace_hash(self) -> str:
        """SHA-256 of the run's observation events. Used to verify
        deterministic traces across runs.
        """
        h = hashlib.sha256()
        for obs in self.observations:
            h.update(obs.event.encode("utf-8"))
            h.update(struct.pack(">ff", obs.position_x, obs.position_y))
        return h.hexdigest()