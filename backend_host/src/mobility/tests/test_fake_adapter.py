"""
FakeMobilityController tests — scripted mission + fault injection + determinism.

The fake adapter must:

- complete the scripted sidewalk-100m mission deterministically given a seed;
- react to every injected fault (sensor dropout, heartbeat loss, adapter exception);
- produce a stable observation trace for the same seed;
- produce a different trace for a different seed (entropy).
"""
from __future__ import annotations

import os
import threading
import time

import pytest

from backend_host.src.mobility.adapters.fake import FakeMobilityController
from backend_host.src.mobility.auth import OperatorRegistry
from backend_host.src.mobility.config import MobilityConfig
from backend_host.src.mobility.controller import BaseMobilityController
from backend_host.src.mobility.missions import sidewalk_100m
from backend_host.src.mobility.models import (
    MobilityMission,
    MobilityResult,
    ResultStatus,
    RoverCommand,
    RoverState,
)
from backend_host.src.mobility.safety import SafetyContext, SafetyGate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg() -> MobilityConfig:
    return MobilityConfig(
        enabled=True,
        max_speed_mps=1.0,
        max_turn_radps=0.5,
        max_duration_s=10.0,
        geofence_min_x=0.0,
        geofence_max_x=200.0,
        geofence_min_y=0.0,
        geofence_max_y=50.0,
        heartbeat_timeout_ms=2000,
        require_auth_token=False,
        auth_token_max_age_s=5,
        nonce_window=100,
    )


@pytest.fixture
def ops():
    o = OperatorRegistry()
    o.authorize("bob")
    return o


@pytest.fixture
def gate(cfg, ops):
    return SafetyGate(config=cfg, operators=ops)


@pytest.fixture
def mission() -> MobilityMission:
    return MobilityMission(
        mission_id="m1", scenario_id="sidewalk_100m", seed=0
    )


@pytest.fixture
def script():
    return sidewalk_100m(seed=0)


@pytest.fixture
def fake(cfg, gate, script) -> FakeMobilityController:
    f = FakeMobilityController(config=cfg, gate=gate, script=script)
    f.connect()
    return f


def _drive_to_destination(fake: FakeMobilityController, mission: MobilityMission) -> MobilityResult:
    """Drive the fake forward in 1-second chunks until it reaches the destination.

    This mirrors the API layer's "run mission" loop without going through
    Flask: every chunk is a separate ``execute_command`` call so the
    safety gate is exercised between steps.
    """
    cmd = RoverCommand(
        linear_velocity_mps=1.0,
        angular_velocity_radps=0.0,
        duration_s=1.0,
        capability="navigate",
        operator_id="bob",
    )
    for _ in range(mission.max_steps):
        decision = fake.execute_command(cmd)
        if decision.verdict == "deny" and decision.reason_code in (
            "ESTOP_ENGAGED",
            "HEARTBEAT_LOST",
            "OBSTACLE_STOP",
        ):
            break
        state = fake.telemetry()
        if state.position_x >= 100.0:
            break
    return fake.build_result(mission_id=mission.mission_id, scenario_id=mission.scenario_id)


# ---------------------------------------------------------------------------
# Mission completion
# ---------------------------------------------------------------------------


def test_mission_completes_with_destination_reached(fake, mission):
    result = _drive_to_destination(fake, mission)
    assert result.status == ResultStatus.PASS
    assert result.reason_code == "DESTINATION_REACHED"
    assert result.final_position_x == pytest.approx(100.0, abs=1.0)


def test_mission_trace_includes_curbs_ramp_obstacles_destination(fake, mission):
    _drive_to_destination(fake, mission)
    events = [o.event for o in fake.observations]
    # 3 curbs
    curb_events = [e for e in events if e.startswith("curb:")]
    assert len(curb_events) == 3
    # 1 ramp
    ramp_events = [e for e in events if e.startswith("ramp:")]
    assert len(ramp_events) == 1
    # 2 reroutable obstacles
    reroute = [e for e in events if e.startswith("obstacle_reroute:")]
    assert len(reroute) == 2
    # No obstacle_stop events on the canonical (passable) mission
    stop = [e for e in events if e.startswith("obstacle_stop:")]
    assert len(stop) == 0
    # destination reached
    assert "destination_reached" in events


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_same_seed_same_trace(cfg, gate, ops, mission):
    a = FakeMobilityController(cfg, gate, sidewalk_100m(seed=42))
    b = FakeMobilityController(cfg, gate, sidewalk_100m(seed=42))
    a.connect()
    b.connect()
    ra = _drive_to_destination(a, mission)
    rb = _drive_to_destination(b, mission)
    assert ra.status == rb.status
    assert ra.final_position_x == pytest.approx(rb.final_position_x, abs=0.01)
    assert a.trace_hash() == b.trace_hash()


def test_different_seed_different_obstacle_offset(cfg, gate):
    s1 = sidewalk_100m(seed=0)
    s2 = sidewalk_100m(seed=99_999)
    reroutable_1 = next(o for o in s1.obstacles if o.reroutable)
    reroutable_2 = next(o for o in s2.obstacles if o.reroutable)
    assert reroutable_1.position_y != reroutable_2.position_y


# ---------------------------------------------------------------------------
# Fault injection
# ---------------------------------------------------------------------------


def test_sensor_dropout_results_in_needs_review(cfg, gate, mission):
    script = sidewalk_100m(seed=0)
    fake = FakeMobilityController(
        cfg, gate, script, faults=["sensor_dropout"]
    )
    fake.connect()
    result = _drive_to_destination(fake, mission)
    assert result.status == ResultStatus.NEEDS_REVIEW
    assert result.reason_code == "SENSOR_DROPOUT"


def test_heartbeat_loss_forces_fail(cfg, gate, mission):
    """Heartbeat dead → next gate evaluation denies → run aborts fail."""
    script = sidewalk_100m(seed=0)
    fake = FakeMobilityController(
        cfg, gate, script, heartbeat_alive=False
    )
    fake.connect()
    result = _drive_to_destination(fake, mission)
    # Heartbeat is lost on the first heartbeat call, so the next
    # navigate command is denied with HEARTBEAT_LOST.
    deny_decisions = [
        d for d in fake.audit_log
        if d.verdict == "deny" and d.reason_code == "HEARTBEAT_LOST"
    ]
    assert deny_decisions, "expected at least one HEARTBEAT_LOST deny"
    assert result.status in (ResultStatus.FAIL, ResultStatus.NEEDS_REVIEW)


def test_adapter_exception_propagates_as_deny(cfg, gate, mission):
    script = sidewalk_100m(seed=0)

    class ExplodingFake(FakeMobilityController):
        def _execute_command(self, cmd):  # type: ignore[override]
            raise RuntimeError("hardware fault")

    fake = ExplodingFake(cfg, gate, script)
    fake.connect()
    cmd = RoverCommand(
        linear_velocity_mps=0.5,
        angular_velocity_radps=0.0,
        duration_s=1.0,
        capability="navigate",
        operator_id="bob",
    )
    decision = fake.execute_command(cmd)
    assert decision.verdict == "deny"
    assert decision.reason_code == "ADAPTER_EXCEPTION"
    # Subsequent decisions still work — the host didn't crash.
    cmd2 = RoverCommand(
        linear_velocity_mps=0.5,
        angular_velocity_radps=0.0,
        duration_s=1.0,
        capability="navigate",
        operator_id="bob",
    )
    decision2 = fake.execute_command(cmd2)
    assert decision2.verdict in ("allow", "reduce", "deny")  # no crash


# ---------------------------------------------------------------------------
# Stop semantics
# ---------------------------------------------------------------------------


def test_stop_works_after_obstacle(cfg, gate):
    """A non-reroutable obstacle forces stop. Verify with a custom script
    so the canonical sidewalk-100m (always passable) stays clean."""
    from backend_host.src.mobility.missions import (
        MissionScript,
        ScriptedCurb,
        ScriptedDestination,
        ScriptedObstacle,
    )

    script = MissionScript(
        scenario_id="obstacle_blocked",
        length_m=10.0,
        curbs=(),
        ramps=(),
        obstacles=(
            ScriptedObstacle(
                position_x=5.0,
                position_y=0.0,
                radius_m=0.4,
                reroutable=False,
            ),
        ),
        destination=ScriptedDestination(position_x=10.0, position_y=0.0),
    )
    fake = FakeMobilityController(cfg, gate, script)
    fake.connect()
    cmd = RoverCommand(
        linear_velocity_mps=1.0,
        angular_velocity_radps=0.0,
        duration_s=1.0,
        capability="navigate",
        operator_id="bob",
    )
    # Drive enough steps to reach the obstacle at x=5.
    hit_obstacle = False
    for _ in range(20):
        fake.execute_command(cmd)
        if fake._final_reason_code == "OBSTACLE_STOP":
            hit_obstacle = True
            break
    assert hit_obstacle, "rover should have hit the non-reroutable obstacle"
    # An explicit stop() should succeed even though the run is "stopped".
    decision = fake.stop()
    assert decision.verdict in ("allow", "reduce")


def test_stop_works_with_e_stop_engaged(cfg, gate, script):
    fake = FakeMobilityController(cfg, gate, script)
    fake.connect()
    fake.context.estop_engaged = True
    decision = fake.stop()
    assert decision.verdict == "allow"


# ---------------------------------------------------------------------------
# Sensor methods
# ---------------------------------------------------------------------------


def test_camera_returns_png_path(fake):
    path = fake.camera()
    assert path is not None
    assert path.endswith(".png")
    assert os.path.exists(path)
    with open(path, "rb") as fh:
        sig = fh.read(8)
    assert sig == b"\x89PNG\r\n\x1a\n"


def test_measure_returns_distance_to_destination(fake):
    """At (0,0), the distance to (100,0) is 100 m."""
    assert fake.measure() == pytest.approx(100.0, abs=0.001)
    fake._ctx.current_position = (50.0, 0.0)
    assert fake.measure() == pytest.approx(50.0, abs=0.001)


def test_telemetry_reports_current_state(fake):
    state = fake.telemetry()
    assert state.position_x == 0.0
    assert state.battery_pct == 100.0


# ---------------------------------------------------------------------------
# Adapter is an instance of the MobilityController Protocol
# ---------------------------------------------------------------------------


def test_fake_adapter_satisfies_protocol(fake):
    from backend_host.src.mobility.controller import MobilityController

    assert isinstance(fake, MobilityController)


# ---------------------------------------------------------------------------
# Thread safety smoke
# ---------------------------------------------------------------------------


def test_concurrent_execute_commands_are_safe(fake, mission):
    cmd = RoverCommand(
        linear_velocity_mps=0.5,
        angular_velocity_radps=0.0,
        duration_s=0.1,
        capability="navigate",
        operator_id="bob",
    )
    decisions: list = []
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        decisions.append(fake.execute_command(cmd))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(decisions) == 4


# ---------------------------------------------------------------------------
# Audit log / observations
# ---------------------------------------------------------------------------


def test_audit_log_records_every_decision(fake, mission):
    _drive_to_destination(fake, mission)
    log = fake.audit_log
    assert len(log) >= 1
    for d in log:
        assert len(d.audit_id) == 32


def test_observations_are_chronological(fake, mission):
    _drive_to_destination(fake, mission)
    timestamps = [o.timestamp_ms for o in fake.observations]
    assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# E-stop integration
# ---------------------------------------------------------------------------


def test_e_stop_during_navigate_denies(fake):
    cmd = RoverCommand(
        linear_velocity_mps=0.5,
        angular_velocity_radps=0.0,
        duration_s=1.0,
        capability="navigate",
        operator_id="bob",
    )
    fake.context.estop_engaged = True
    decision = fake.execute_command(cmd)
    assert decision.verdict == "deny"
    assert decision.reason_code == "ESTOP_ENGAGED"


# ---------------------------------------------------------------------------
# Final result fields
# ---------------------------------------------------------------------------


def test_result_distance_traveled_is_nonnegative(fake, mission):
    result = _drive_to_destination(fake, mission)
    assert result.distance_traveled_m >= 0.0


def test_result_includes_safety_audit_ids(fake, mission):
    result = _drive_to_destination(fake, mission)
    assert len(result.safety_audit_ids) >= 1
    for aid in result.safety_audit_ids:
        assert len(aid) == 32