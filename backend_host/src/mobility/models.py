"""
Mobility data models — the language the SafetyGate, the API, and every
adapter speak.

Design notes
------------
- Every numeric field validates ``math.isfinite`` on construction. NaN and
  ±Inf are rejected with ``ValueError`` because a downstream safety decision
  built on a NaN is undefined.
- Dataclasses are frozen so a partially-validated command can't be mutated
  out from under the gate.
- ``to_dict`` / ``from_dict`` use a stable wire format — the field names
  are what gets logged and reported, so they have to be predictable.
- Status enums are string-valued so reports survive JSON round-trips and
  don't depend on enum ordering changes.

Why dataclasses (not Pydantic)
------------------------------
Pydantic would be a new top-level dependency. The platform already has it in
``backend_server``, but ``backend_host`` does not — adding it for one
module is exactly the kind of churn the spec rules out.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Capabilities — explicit, narrow, and documented.
#
# The Mobility feature surfaces five capabilities:
#   telemetry  — read state (position, velocity, sensor health, …)
#   camera     — capture a frame from the rover's camera
#   navigate   — drive to a target pose / waypoint
#   stop       — bring the rover to zero-motion immediately
#   measure    — read a sensor (e.g. distance) at a position
#
# Anything else is rejected by the gate with CAPABILITY_NOT_SUPPORTED. This
# is a deliberate allow-list: a new capability lands here only after the
# SafetyGate knows what to do with it.
# ---------------------------------------------------------------------------
CAPABILITIES: frozenset = frozenset({"telemetry", "camera", "navigate", "stop", "measure"})


def is_valid_capability(cap: str) -> bool:
    return cap in CAPABILITIES


# ---------------------------------------------------------------------------
# RoverCommand — what the operator asks the rover to do.
#
# All units are SI (m, s, rad). Zero-motion = linear=0, angular=0, duration=0.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RoverCommand:
    """A single motion request, validated on construction."""

    linear_velocity_mps: float
    angular_velocity_radps: float
    duration_s: float
    capability: str = "navigate"           # default = navigate; gate may override
    target_x: Optional[float] = None       # geofence reference; None = stay-in-place
    target_y: Optional[float] = None
    operator_id: str = ""                  # required for R7
    authorization_token: str = ""          # required when require_auth_token=True
    nonce: str = ""                        # required when require_auth_token=True
    issued_at_ms: int = 0                  # required when require_auth_token=True
    reason: str = ""                       # free-text operator note; for audit only

    def __post_init__(self) -> None:
        # Finite checks for every numeric field — the gate MUST be able to
        # reason about each value without a NaN escaping into arithmetic.
        _require_finite(self.linear_velocity_mps, "linear_velocity_mps")
        _require_finite(self.angular_velocity_radps, "angular_velocity_radps")
        _require_finite(self.duration_s, "duration_s")
        if self.target_x is not None:
            _require_finite(self.target_x, "target_x")
        if self.target_y is not None:
            _require_finite(self.target_y, "target_y")
        # duration_s MUST be positive — zero is reserved for "stop" only.
        if self.duration_s <= 0:
            raise ValueError(
                f"duration_s must be > 0 (got {self.duration_s}); "
                "use a zero-motion stop command instead"
            )
        if not is_valid_capability(self.capability):
            raise ValueError(
                f"capability {self.capability!r} not in {sorted(CAPABILITIES)}"
            )
        if self.issued_at_ms and self.issued_at_ms < 0:
            raise ValueError(f"issued_at_ms must be >= 0 (got {self.issued_at_ms})")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoverCommand":
        return cls(
            linear_velocity_mps=float(data.get("linear_velocity_mps", 0.0)),
            angular_velocity_radps=float(data.get("angular_velocity_radps", 0.0)),
            duration_s=float(data.get("duration_s", 0.0)),
            capability=str(data.get("capability", "navigate")),
            target_x=_opt_float(data.get("target_x")),
            target_y=_opt_float(data.get("target_y")),
            operator_id=str(data.get("operator_id", "")),
            authorization_token=str(data.get("authorization_token", "")),
            nonce=str(data.get("nonce", "")),
            issued_at_ms=int(data.get("issued_at_ms", 0) or 0),
            reason=str(data.get("reason", "")),
        )

    def is_zero_motion(self) -> bool:
        """True iff this is the canonical stop / hold-still command."""
        return (
            self.linear_velocity_mps == 0.0
            and self.angular_velocity_radps == 0.0
            and self.duration_s > 0
        )

    def with_clipped(
        self,
        linear: Optional[float] = None,
        angular: Optional[float] = None,
        duration: Optional[float] = None,
    ) -> "RoverCommand":
        """Return a new RoverCommand with selected fields replaced.

        Used by the gate when it must ``reduce`` a command rather than deny
        it. The original is never mutated (the dataclass is frozen).
        """
        return RoverCommand(
            linear_velocity_mps=(
                linear if linear is not None else self.linear_velocity_mps
            ),
            angular_velocity_radps=(
                angular if angular is not None else self.angular_velocity_radps
            ),
            duration_s=(
                duration if duration is not None else self.duration_s
            ),
            capability=self.capability,
            target_x=self.target_x,
            target_y=self.target_y,
            operator_id=self.operator_id,
            authorization_token=self.authorization_token,
            nonce=self.nonce,
            issued_at_ms=self.issued_at_ms,
            reason=self.reason,
        )


def zero_motion(operator_id: str = "", reason: str = "safety: zero-motion") -> RoverCommand:
    """Build the canonical zero-motion command (RoverCommand is immutable)."""
    # bypass __post_init__ to allow duration_s=0 for explicit stops, then
    # patch via object.__setattr__ since the dataclass is frozen.
    cmd = RoverCommand(
        linear_velocity_mps=0.0,
        angular_velocity_radps=0.0,
        duration_s=0.001,  # 1ms — gate/contract enforces >0; stop = 1ms hold
        capability="stop",
        operator_id=operator_id,
        reason=reason,
    )
    return cmd


# ---------------------------------------------------------------------------
# RoverState — what telemetry reports back.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RoverState:
    """A snapshot of the rover's state at one moment."""

    position_x: float
    position_y: float
    heading_rad: float            # 0 = +x, pi/2 = +y (right-hand)
    linear_velocity_mps: float
    angular_velocity_radps: float
    battery_pct: float            # 0..100
    sensor_health: Dict[str, str] = field(default_factory=dict)  # sensor -> "ok"|"degraded"|"lost"
    timestamp_ms: int = 0

    def __post_init__(self) -> None:
        _require_finite(self.position_x, "position_x")
        _require_finite(self.position_y, "position_y")
        _require_finite(self.heading_rad, "heading_rad")
        _require_finite(self.linear_velocity_mps, "linear_velocity_mps")
        _require_finite(self.angular_velocity_radps, "angular_velocity_radps")
        _require_finite(self.battery_pct, "battery_pct")
        if not (0.0 <= self.battery_pct <= 100.0):
            raise ValueError(f"battery_pct must be in [0,100], got {self.battery_pct}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoverState":
        return cls(
            position_x=float(data.get("position_x", 0.0)),
            position_y=float(data.get("position_y", 0.0)),
            heading_rad=float(data.get("heading_rad", 0.0)),
            linear_velocity_mps=float(data.get("linear_velocity_mps", 0.0)),
            angular_velocity_radps=float(data.get("angular_velocity_radps", 0.0)),
            battery_pct=float(data.get("battery_pct", 100.0)),
            sensor_health=dict(data.get("sensor_health") or {}),
            timestamp_ms=int(data.get("timestamp_ms", 0) or 0),
        )


# ---------------------------------------------------------------------------
# Mission schema — what the operator hands the runner.
# ---------------------------------------------------------------------------
class MissionPhase(str, Enum):
    PLAN = "plan"
    RUN = "run"
    COMPLETE = "complete"
    CANCEL = "cancel"


@dataclass(frozen=True)
class MobilityMission:
    """A scripted scenario. ``scenario_id`` selects a built-in script or a
    user-defined one. ``seed`` makes the run deterministic.
    """

    mission_id: str
    scenario_id: str
    seed: int = 0
    capabilities: Tuple[str, ...] = ("navigate", "stop", "telemetry", "camera", "measure")
    max_steps: int = 10000
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.mission_id:
            raise ValueError("mission_id is required")
        if not self.scenario_id:
            raise ValueError("scenario_id is required")
        if self.seed < 0:
            raise ValueError(f"seed must be >= 0, got {self.seed}")
        if self.max_steps <= 0:
            raise ValueError(f"max_steps must be > 0, got {self.max_steps}")
        for cap in self.capabilities:
            if not is_valid_capability(cap):
                raise ValueError(f"capability {cap!r} not in {sorted(CAPABILITIES)}")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["capabilities"] = list(self.capabilities)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MobilityMission":
        caps = tuple(data.get("capabilities") or CAPABILITIES)
        return cls(
            mission_id=str(data.get("mission_id", "")),
            scenario_id=str(data.get("scenario_id", "")),
            seed=int(data.get("seed", 0) or 0),
            capabilities=cast_tuple_str(caps),
            max_steps=int(data.get("max_steps", 10000) or 10000),
            metadata=dict(data.get("metadata") or {}),
        )


# ---------------------------------------------------------------------------
# Mission result + observation trace.
# ---------------------------------------------------------------------------
class ResultStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVIEW = "needs_review"
    ERROR = "error"
    CANCELED = "canceled"


@dataclass(frozen=True)
class MobilityObservation:
    """One observation from a run. Ordered chronologically by timestamp_ms."""

    timestamp_ms: int
    position_x: float
    position_y: float
    heading_rad: float
    linear_velocity_mps: float
    angular_velocity_radps: float
    sensor_health: Dict[str, str] = field(default_factory=dict)
    event: str = ""                # free-text: "curb_detected", "obstacle_reroute", …
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_finite(self.position_x, "position_x")
        _require_finite(self.position_y, "position_y")
        _require_finite(self.heading_rad, "heading_rad")
        _require_finite(self.linear_velocity_mps, "linear_velocity_mps")
        _require_finite(self.angular_velocity_radps, "angular_velocity_radps")
        if self.timestamp_ms < 0:
            raise ValueError(f"timestamp_ms must be >= 0, got {self.timestamp_ms}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MobilityObservation":
        return cls(
            timestamp_ms=int(data.get("timestamp_ms", 0) or 0),
            position_x=float(data.get("position_x", 0.0)),
            position_y=float(data.get("position_y", 0.0)),
            heading_rad=float(data.get("heading_rad", 0.0)),
            linear_velocity_mps=float(data.get("linear_velocity_mps", 0.0)),
            angular_velocity_radps=float(data.get("angular_velocity_radps", 0.0)),
            sensor_health=dict(data.get("sensor_health") or {}),
            event=str(data.get("event", "")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class MobilityResult:
    """The summary returned to the API caller once a mission ends."""

    mission_id: str
    scenario_id: str
    status: ResultStatus
    started_at_ms: int
    finished_at_ms: int
    reason: str = ""                          # human-readable, single line
    reason_code: str = ""                     # machine-readable; stable strings
    final_position_x: float = 0.0
    final_position_y: float = 0.0
    distance_traveled_m: float = 0.0
    observations: Tuple[MobilityObservation, ...] = ()
    safety_audit_ids: Tuple[str, ...] = ()
    adapter_id: str = "fake"                  # "fake" / future "gazebo" / "physical_mock"

    def __post_init__(self) -> None:
        _require_finite(self.final_position_x, "final_position_x")
        _require_finite(self.final_position_y, "final_position_y")
        _require_finite(self.distance_traveled_m, "distance_traveled_m")
        if self.finished_at_ms < self.started_at_ms:
            raise ValueError(
                f"finished_at_ms ({self.finished_at_ms}) must be >= "
                f"started_at_ms ({self.started_at_ms})"
            )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["observations"] = [o.to_dict() for o in self.observations]
        d["safety_audit_ids"] = list(self.safety_audit_ids)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MobilityResult":
        status_raw = data.get("status", "error")
        try:
            status = ResultStatus(status_raw)
        except ValueError:
            status = ResultStatus.ERROR
        return cls(
            mission_id=str(data.get("mission_id", "")),
            scenario_id=str(data.get("scenario_id", "")),
            status=status,
            started_at_ms=int(data.get("started_at_ms", 0) or 0),
            finished_at_ms=int(data.get("finished_at_ms", 0) or 0),
            reason=str(data.get("reason", "")),
            reason_code=str(data.get("reason_code", "")),
            final_position_x=float(data.get("final_position_x", 0.0)),
            final_position_y=float(data.get("final_position_y", 0.0)),
            distance_traveled_m=float(data.get("distance_traveled_m", 0.0)),
            observations=tuple(
                MobilityObservation.from_dict(o)
                for o in (data.get("observations") or [])
            ),
            safety_audit_ids=tuple(data.get("safety_audit_ids") or ()),
            adapter_id=str(data.get("adapter_id", "fake")),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _require_finite(value: float, name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number (got {value!r})")


def _opt_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def cast_tuple_str(values: Any) -> Tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        return (values,)
    return tuple(str(v) for v in values)