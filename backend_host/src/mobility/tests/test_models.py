"""
Model tests — serialization, validation, capability allow-list.

The models carry the contract between the API, the SafetyGate, and the
adapter. A regression here means either a route is producing a malformed
command or the gate is reasoning about a NaN, both of which would be
silent bugs at runtime.
"""
from __future__ import annotations

import math

import pytest

from backend_host.src.mobility.models import (
    CAPABILITIES,
    MissionPhase,
    MobilityMission,
    MobilityObservation,
    MobilityResult,
    ResultStatus,
    RoverCommand,
    RoverState,
    is_valid_capability,
    zero_motion,
)


# ---------------------------------------------------------------------------
# Capability allow-list
# ---------------------------------------------------------------------------


def test_capabilities_contain_expected_set():
    assert CAPABILITIES == frozenset({"telemetry", "camera", "navigate", "stop", "measure"})


@pytest.mark.parametrize("cap", ["telemetry", "camera", "navigate", "stop", "measure"])
def test_valid_capabilities_accepted(cap):
    assert is_valid_capability(cap) is True


@pytest.mark.parametrize("cap", ["drive", "fly", "swim", "", "STOP", "telemetry1"])
def test_invalid_capabilities_rejected(cap):
    assert is_valid_capability(cap) is False


# ---------------------------------------------------------------------------
# RoverCommand — validation
# ---------------------------------------------------------------------------


def _base_cmd(**overrides):
    base = dict(
        linear_velocity_mps=0.5,
        angular_velocity_radps=0.1,
        duration_s=2.0,
        capability="navigate",
        operator_id="alice",
    )
    base.update(overrides)
    return RoverCommand(**base)


def test_rover_command_accepts_valid():
    cmd = _base_cmd()
    assert cmd.linear_velocity_mps == 0.5
    assert cmd.capability == "navigate"


@pytest.mark.parametrize(
    "field,value",
    [
        ("linear_velocity_mps", math.nan),
        ("angular_velocity_radps", math.nan),
        ("duration_s", math.nan),
        ("target_x", math.nan),
        ("target_y", math.nan),
    ],
)
def test_rover_command_rejects_nan(field, value):
    kwargs = {field: value}
    with pytest.raises(ValueError, match="finite"):
        _base_cmd(**kwargs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("linear_velocity_mps", math.inf),
        ("angular_velocity_radps", -math.inf),
        ("duration_s", math.inf),
        ("target_x", math.inf),
        ("target_y", -math.inf),
    ],
)
def test_rover_command_rejects_infinity(field, value):
    with pytest.raises(ValueError, match="finite"):
        _base_cmd(**{field: value})


@pytest.mark.parametrize("duration", [0.0, -1.0, -0.001])
def test_rover_command_rejects_nonpositive_duration(duration):
    with pytest.raises(ValueError, match="duration_s"):
        _base_cmd(duration_s=duration)


def test_zero_motion_factory_returns_stop_capability():
    cmd = zero_motion(operator_id="alice", reason="test")
    assert cmd.linear_velocity_mps == 0.0
    assert cmd.angular_velocity_radps == 0.0
    assert cmd.capability == "stop"


def test_rover_command_is_zero_motion():
    assert _base_cmd(linear_velocity_mps=0.0, angular_velocity_radps=0.0).is_zero_motion() is True


def test_rover_command_is_not_zero_motion_when_moving():
    assert _base_cmd().is_zero_motion() is False


def test_rover_command_rejects_unknown_capability():
    with pytest.raises(ValueError, match="capability"):
        _base_cmd(capability="fly")


def test_rover_command_rejects_negative_issued_at():
    with pytest.raises(ValueError, match="issued_at_ms"):
        _base_cmd(issued_at_ms=-1)


def test_rover_command_target_none_is_allowed():
    cmd = _base_cmd(target_x=None, target_y=None)
    assert cmd.target_x is None and cmd.target_y is None


# ---------------------------------------------------------------------------
# RoverCommand — serialization
# ---------------------------------------------------------------------------


def test_rover_command_round_trip():
    original = _base_cmd(
        target_x=10.0,
        target_y=20.0,
        nonce="abc123",
        authorization_token="xyz",
        issued_at_ms=1_700_000_000_000,
        reason="manual override",
    )
    payload = original.to_dict()
    rebuilt = RoverCommand.from_dict(payload)
    assert rebuilt == original


def test_rover_command_from_dict_empty_payload_raises():
    """``from_dict({})`` produces ``duration_s=0.0`` which fails the
    validator. Empty payloads are always a programming error — the
    constructor's ``__post_init__`` is the right place to fail loudly.
    """
    with pytest.raises(ValueError, match="duration_s"):
        RoverCommand.from_dict({})


def test_rover_command_from_dict_partial_payload_uses_zero_durations():
    """A partial payload that supplies a positive duration_s survives the
    validator. The remaining fields fall back to their defaults."""
    cmd = RoverCommand.from_dict({"duration_s": 1.0})
    assert cmd.duration_s == 1.0
    assert cmd.linear_velocity_mps == 0.0
    assert cmd.capability == "navigate"


def test_rover_command_with_clipped_returns_new_instance():
    original = _base_cmd(linear_velocity_mps=2.0, angular_velocity_radps=1.0)
    clipped = original.with_clipped(linear=1.0)
    assert clipped.linear_velocity_mps == 1.0
    assert clipped.angular_velocity_radps == 1.0  # unchanged
    assert original.linear_velocity_mps == 2.0      # original preserved


# ---------------------------------------------------------------------------
# RoverState
# ---------------------------------------------------------------------------


def _base_state(**overrides):
    base = dict(
        position_x=1.0,
        position_y=2.0,
        heading_rad=0.5,
        linear_velocity_mps=0.0,
        angular_velocity_radps=0.0,
        battery_pct=87.5,
        sensor_health={"lidar": "ok"},
    )
    base.update(overrides)
    return RoverState(**base)


def test_rover_state_accepts_valid():
    s = _base_state()
    assert s.battery_pct == 87.5


def test_rover_state_rejects_out_of_range_battery():
    with pytest.raises(ValueError, match="battery_pct"):
        _base_state(battery_pct=120.0)
    with pytest.raises(ValueError, match="battery_pct"):
        _base_state(battery_pct=-5.0)


def test_rover_state_round_trip():
    s = _base_state()
    rebuilt = RoverState.from_dict(s.to_dict())
    assert rebuilt == s


# ---------------------------------------------------------------------------
# MobilityMission
# ---------------------------------------------------------------------------


def test_mission_accepts_valid():
    m = MobilityMission(mission_id="m1", scenario_id="sidewalk_100m", seed=42)
    assert m.seed == 42


def test_mission_requires_mission_id():
    with pytest.raises(ValueError, match="mission_id"):
        MobilityMission(mission_id="", scenario_id="sidewalk_100m")


def test_mission_requires_scenario_id():
    with pytest.raises(ValueError, match="scenario_id"):
        MobilityMission(mission_id="m1", scenario_id="")


def test_mission_rejects_negative_seed():
    with pytest.raises(ValueError, match="seed"):
        MobilityMission(mission_id="m1", scenario_id="s", seed=-1)


def test_mission_rejects_zero_max_steps():
    with pytest.raises(ValueError, match="max_steps"):
        MobilityMission(mission_id="m1", scenario_id="s", max_steps=0)


def test_mission_rejects_unknown_capability():
    with pytest.raises(ValueError, match="capability"):
        MobilityMission(
            mission_id="m1",
            scenario_id="s",
            capabilities=("navigate", "fly"),
        )


def test_mission_round_trip():
    m = MobilityMission(
        mission_id="m1",
        scenario_id="sidewalk_100m",
        seed=42,
        capabilities=("navigate", "stop"),
        max_steps=500,
        metadata={"requested_by": "alice"},
    )
    rebuilt = MobilityMission.from_dict(m.to_dict())
    assert rebuilt == m


# ---------------------------------------------------------------------------
# MobilityObservation
# ---------------------------------------------------------------------------


def test_observation_rejects_negative_timestamp():
    with pytest.raises(ValueError, match="timestamp_ms"):
        MobilityObservation(
            timestamp_ms=-1,
            position_x=0.0,
            position_y=0.0,
            heading_rad=0.0,
            linear_velocity_mps=0.0,
            angular_velocity_radps=0.0,
        )


def test_observation_round_trip():
    o = MobilityObservation(
        timestamp_ms=100,
        position_x=1.0,
        position_y=2.0,
        heading_rad=0.5,
        linear_velocity_mps=0.0,
        angular_velocity_radps=0.0,
        event="curb_detected",
    )
    rebuilt = MobilityObservation.from_dict(o.to_dict())
    assert rebuilt == o


# ---------------------------------------------------------------------------
# MobilityResult
# ---------------------------------------------------------------------------


def test_result_accepts_valid():
    r = MobilityResult(
        mission_id="m1",
        scenario_id="sidewalk_100m",
        status=ResultStatus.PASS,
        started_at_ms=100,
        finished_at_ms=200,
    )
    assert r.status is ResultStatus.PASS


def test_result_rejects_finished_before_started():
    with pytest.raises(ValueError, match="finished_at_ms"):
        MobilityResult(
            mission_id="m1",
            scenario_id="s",
            status=ResultStatus.PASS,
            started_at_ms=200,
            finished_at_ms=100,
        )


def test_result_round_trip():
    r = MobilityResult(
        mission_id="m1",
        scenario_id="sidewalk_100m",
        status=ResultStatus.NEEDS_REVIEW,
        started_at_ms=100,
        finished_at_ms=200,
        reason="sensor dropout",
        reason_code="SENSOR_DROPPOUT",
        observations=(),
    )
    rebuilt = MobilityResult.from_dict(r.to_dict())
    assert rebuilt == r
    assert rebuilt.status is ResultStatus.NEEDS_REVIEW


def test_result_from_dict_unknown_status_falls_back_to_error():
    r = MobilityResult.from_dict(
        {
            "mission_id": "m1",
            "scenario_id": "s",
            "status": "garbage",
        }
    )
    assert r.status is ResultStatus.ERROR


def test_result_status_enum_values_are_strings():
    # Reports survive JSON round-trips; enum members must be string-valued.
    for s in ResultStatus:
        assert isinstance(s.value, str)


# ---------------------------------------------------------------------------
# Module import is a no-op when the flag is off
# ---------------------------------------------------------------------------


def test_importing_mobility_with_flag_off_does_not_enable(monkeypatch):
    """A bare ``import backend_host.src.mobility`` must NOT switch anything on."""
    monkeypatch.delenv("VPT_MOBILITY_ENABLED", raising=False)
    import importlib

    importlib.reload(importlib.import_module("backend_host.src.mobility"))
    from backend_host.src.mobility import is_enabled

    assert is_enabled() is False


def test_importing_mobility_does_not_import_optional_heavy_deps(monkeypatch):
    """Importing the package must not pull in ROS 2, Gazebo, or anything
    that isn't stdlib + the host's core deps. We probe for a few sentinel
    module names that future PRs (2/3/4) will introduce; their absence
    today is the proof.
    """
    import sys

    forbidden = [
        "rclpy",          # ROS 2 Python client
        "rospy",          # ROS 1 Python client
        "gazebo",         # Gazebo bindings (any sub-module)
        "geometry_msgs",  # ROS 2 geometry messages
        "tf2_ros",        # ROS 2 transforms
    ]
    leaked = [m for m in forbidden if m in sys.modules]
    assert leaked == [], f"Optional heavy deps leaked into sys.modules: {leaked}"