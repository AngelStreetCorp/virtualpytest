"""
SafetyGate tests — every rule (R1..R12), every edge case.

The gate is the only authority for rover motion. A regression here means
a silent safety violation: the rover moves when it shouldn't, or doesn't
move when it must. Each test pins one rule + one edge case so a failure
maps to a known rule.

Test strategy
-------------
- The gate is evaluated against an in-process ``SafetyContext`` and a
  pre-authorized operator (``bob``). ``TokenVerifier`` uses the platform
  API key by default; we mint tokens with the same secret.
- ``on_command`` is captured to verify the R11 zero-motion pulse fires
  on every deny.
- Tests are organized by rule (R1..R12) so a failure tells the operator
  which rule broke.
"""
from __future__ import annotations

import math
import threading
from typing import List

import pytest

from backend_host.src.mobility.auth import OperatorRegistry, TokenVerifier
from backend_host.src.mobility.config import MobilityConfig
from backend_host.src.mobility.models import (
    RoverCommand,
    RoverState,
    zero_motion,
)
from backend_host.src.mobility.safety import (
    ALLOW,
    DENY,
    REDUCE,
    SafetyContext,
    SafetyDecision,
    SafetyGate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg() -> MobilityConfig:
    """A permissive config — fast turn-around, but with all bounds finite."""
    return MobilityConfig(
        enabled=True,
        max_speed_mps=1.0,
        max_turn_radps=0.5,
        max_duration_s=10.0,
        geofence_min_x=0.0,
        geofence_max_x=100.0,
        geofence_min_y=0.0,
        geofence_max_y=100.0,
        heartbeat_timeout_ms=2000,
        require_auth_token=False,
        auth_token_max_age_s=5,
        nonce_window=100,
    )


@pytest.fixture
def zero_motion_calls() -> List[tuple]:
    return []


@pytest.fixture
def gate(cfg, zero_motion_calls):
    ops = OperatorRegistry()
    ops.authorize("bob", label="test operator")
    verifier = TokenVerifier(
        max_age_s=cfg.auth_token_max_age_s, nonce_window=cfg.nonce_window
    )

    def _on_command(cmd: RoverCommand, decision: SafetyDecision) -> None:
        zero_motion_calls.append((cmd, decision))

    return SafetyGate(
        config=cfg,
        operators=ops,
        token_verifier=verifier,
        on_command=_on_command,
    )


@pytest.fixture
def ctx() -> SafetyContext:
    """Default context — fresh heartbeat, no e-stop, healthy connection.

    ``last_heartbeat_ms`` is intentionally set to "now" so a default
    gate evaluation has a recent heartbeat. The ``gate.evaluate`` call
    uses ``time.time()`` when ``now_ms`` isn't passed, so a small
    positive value keeps the gap within the 2000 ms timeout for the
    duration of the test.
    """
    import time

    now = int(time.time() * 1000)
    return SafetyContext(
        connection_healthy=True,
        last_heartbeat_ms=now,
        estop_engaged=False,
        current_position=(5.0, 5.0),
    )


def _now_ms() -> int:
    """Inline clock for tests that build their own SafetyContext."""
    import time

    return int(time.time() * 1000)


def fresh_ctx(**overrides) -> SafetyContext:
    """Build a SafetyContext with a fresh heartbeat.

    Use this whenever a test constructs its own context — the default
    ``last_heartbeat_ms=0`` is treated as "stale forever" by the gate,
    which is correct production behaviour but unhelpful in unit tests.
    """
    base = dict(
        connection_healthy=True,
        last_heartbeat_ms=_now_ms(),
        estop_engaged=False,
        current_position=(5.0, 5.0),
    )
    base.update(overrides)
    return SafetyContext(**base)


def _good_cmd(**overrides) -> RoverCommand:
    base = dict(
        linear_velocity_mps=0.5,
        angular_velocity_radps=0.1,
        duration_s=2.0,
        capability="navigate",
        operator_id="bob",
    )
    base.update(overrides)
    return RoverCommand(**base)


# ---------------------------------------------------------------------------
# Audit ID
# ---------------------------------------------------------------------------


def test_every_decision_has_audit_id(gate, ctx):
    decision = gate.evaluate(_good_cmd(), ctx)
    assert len(decision.audit_id) == 32
    assert all(c in "0123456789abcdef" for c in decision.audit_id)


def test_audit_ids_are_unique_across_calls(gate, ctx):
    ids = {gate.evaluate(_good_cmd(), ctx).audit_id for _ in range(50)}
    assert len(ids) == 50


# ---------------------------------------------------------------------------
# R1 — feature off
# ---------------------------------------------------------------------------


def test_r1_feature_disabled_deny(cfg, ctx, zero_motion_calls):
    cfg_disabled = MobilityConfig(**{**cfg.__dict__, "enabled": False})
    gate = SafetyGate(
        config=cfg_disabled,
        operators=OperatorRegistry(),
        token_verifier=TokenVerifier(),
        on_command=lambda c, d: zero_motion_calls.append((c, d)),
    )
    decision = gate.evaluate(_good_cmd(), ctx)
    assert decision.verdict == DENY
    assert decision.reason_code == "FEATURE_DISABLED"
    assert zero_motion_calls, "R11 must fire on deny"


# ---------------------------------------------------------------------------
# R2 — finiteness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value,expected_code",
    [
        ("linear_velocity_mps", math.nan, "NON_FINITE_LINEAR_VELOCITY_MPS"),
        ("angular_velocity_radps", math.nan, "NON_FINITE_ANGULAR_VELOCITY_RADPS"),
        ("duration_s", math.nan, "NON_FINITE_DURATION_S"),
    ],
)
def test_r2_nan_in_constructor_rejected(field, value, expected_code):
    """Models reject NaN on construction — the gate never sees one."""
    with pytest.raises(ValueError, match="finite"):
        _good_cmd(**{field: value})


def test_r2_infinity_in_constructor_rejected():
    with pytest.raises(ValueError, match="finite"):
        _good_cmd(linear_velocity_mps=math.inf)


# ---------------------------------------------------------------------------
# R3 — speed
# ---------------------------------------------------------------------------


def test_r3_speed_clipped_to_max(gate, ctx, zero_motion_calls):
    decision = gate.evaluate(_good_cmd(linear_velocity_mps=2.5), ctx)
    assert decision.verdict == REDUCE
    assert decision.commanded.linear_velocity_mps == pytest.approx(1.0)
    assert "LINEAR_CLIPPED_TO_MAX" in decision.reason_code
    assert not zero_motion_calls, "R3 is reduce, not deny; no zero-motion pulse"


def test_r3_speed_clipped_negative_direction(gate, ctx):
    decision = gate.evaluate(_good_cmd(linear_velocity_mps=-2.5), ctx)
    assert decision.verdict == REDUCE
    assert decision.commanded.linear_velocity_mps == pytest.approx(-1.0)


def test_r3_speed_disabled_when_max_is_zero(cfg, ctx, zero_motion_calls):
    cfg_zero = MobilityConfig(**{**cfg.__dict__, "max_speed_mps": 0.0})
    ops = OperatorRegistry()
    ops.authorize("bob")
    gate = SafetyGate(
        config=cfg_zero,
        operators=ops,
        token_verifier=TokenVerifier(),
        on_command=lambda c, d: zero_motion_calls.append((c, d)),
    )
    decision = gate.evaluate(_good_cmd(linear_velocity_mps=0.0), ctx)
    assert decision.verdict == DENY
    assert decision.reason_code == "LINEAR_DISABLED"


# ---------------------------------------------------------------------------
# R4 — turn rate
# ---------------------------------------------------------------------------


def test_r4_turn_clipped_to_max(gate, ctx):
    decision = gate.evaluate(_good_cmd(angular_velocity_radps=2.0), ctx)
    assert decision.verdict == REDUCE
    assert decision.commanded.angular_velocity_radps == pytest.approx(0.5)
    assert "TURN_CLIPPED_TO_MAX" in decision.reason_code


def test_r4_turn_disabled_when_max_is_zero(cfg, ctx):
    cfg_zero = MobilityConfig(**{**cfg.__dict__, "max_turn_radps": 0.0})
    ops = OperatorRegistry()
    ops.authorize("bob")
    gate = SafetyGate(config=cfg_zero, operators=ops)
    decision = gate.evaluate(_good_cmd(), ctx)
    assert decision.verdict == DENY
    assert decision.reason_code == "TURN_DISABLED"


# ---------------------------------------------------------------------------
# R5 — duration
# ---------------------------------------------------------------------------


def test_r5_duration_clipped_to_max(gate, ctx):
    decision = gate.evaluate(_good_cmd(duration_s=60.0), ctx)
    assert decision.verdict == REDUCE
    assert decision.commanded.duration_s == pytest.approx(10.0)
    assert "DURATION_CLIPPED_TO_MAX" in decision.reason_code


def test_r5_nonpositive_duration_rejected_in_constructor():
    with pytest.raises(ValueError, match="duration_s"):
        _good_cmd(duration_s=0.0)


# ---------------------------------------------------------------------------
# R6 — geofence
# ---------------------------------------------------------------------------


def test_r6_geofence_target_out_of_bounds(gate, ctx, zero_motion_calls):
    decision = gate.evaluate(
        _good_cmd(target_x=200.0, target_y=50.0), ctx
    )
    assert decision.verdict == DENY
    assert decision.reason_code == "GEOFENCE_TARGET_OUT_OF_BOUNDS"
    assert zero_motion_calls


def test_r6_geofence_rover_out_of_bounds(gate, zero_motion_calls):
    ctx = fresh_ctx(current_position=(500.0, 500.0))
    decision = gate.evaluate(_good_cmd(), ctx)
    assert decision.verdict == DENY
    assert decision.reason_code == "GEOFENCE_ROVER_OUT_OF_BOUNDS"
    assert zero_motion_calls


def test_r6_geofence_unconfigured_deny(cfg, zero_motion_calls):
    cfg_empty = MobilityConfig(
        **{**cfg.__dict__, "geofence_min_x": 0.0, "geofence_max_x": 0.0,
           "geofence_min_y": 0.0, "geofence_max_y": 0.0}
    )
    gate = SafetyGate(
        config=cfg_empty,
        operators=OperatorRegistry(),
        token_verifier=TokenVerifier(),
        on_command=lambda c, d: zero_motion_calls.append((c, d)),
    )
    ctx = fresh_ctx(current_position=(1.0, 1.0))
    decision = gate.evaluate(_good_cmd(), ctx)
    assert decision.verdict == DENY
    assert decision.reason_code == "GEOFENCE_UNCONFIGURED"


def test_r6_geofence_target_none_skips_target_check(gate, ctx):
    decision = gate.evaluate(_good_cmd(target_x=None, target_y=None), ctx)
    assert decision.verdict == ALLOW


# ---------------------------------------------------------------------------
# R7 — operator authorization + token
# ---------------------------------------------------------------------------


def test_r7_unauthorized_operator_deny(gate, zero_motion_calls):
    decision = gate.evaluate(_good_cmd(operator_id="mallory"), fresh_ctx())
    assert decision.verdict == DENY
    assert decision.reason_code == "OPERATOR_UNAUTHORIZED"
    assert zero_motion_calls


# Token-based tests use a gate configured with require_auth_token=True.
# The secret is set explicitly so both the gate's verifier and the test's
# verifier agree on the HMAC key (the env-derived default may be unset in CI).
@pytest.fixture
def token_gate(cfg):
    cfg_with_tokens = MobilityConfig(**{**cfg.__dict__, "require_auth_token": True})
    ops = OperatorRegistry()
    ops.authorize("bob")
    verifier = TokenVerifier(
        secret="test-shared-secret",
        max_age_s=cfg.auth_token_max_age_s,
        nonce_window=cfg.nonce_window,
    )
    gate = SafetyGate(
        config=cfg_with_tokens,
        operators=ops,
        token_verifier=verifier,
    )
    return gate, verifier


def test_r7_token_missing_deny(token_gate):
    gate, _ = token_gate
    decision = gate.evaluate(_good_cmd(), fresh_ctx())
    assert decision.verdict == DENY
    assert decision.reason_code == "AUTH_TOKEN_INVALID"


def test_r7_token_stale_deny(token_gate):
    gate, verifier = token_gate
    token = verifier.mint("bob", "n1", issued_at_ms=0)
    decision = gate.evaluate(
        _good_cmd(authorization_token=token, nonce="n1", issued_at_ms=0),
        fresh_ctx(),
        now_ms=10_000,  # 10s old
    )
    assert decision.verdict == DENY
    assert decision.reason_code == "AUTH_TOKEN_STALE"


def test_r7_token_replayed_deny(token_gate):
    gate, verifier = token_gate
    token = verifier.mint("bob", "n1")
    kwargs = dict(authorization_token=token, nonce="n1", issued_at_ms=0)
    ctx = fresh_ctx()
    # First call OK
    first = gate.evaluate(_good_cmd(**kwargs), ctx)
    assert first.verdict in (ALLOW, REDUCE)
    # Replay the same nonce
    second = gate.evaluate(_good_cmd(**kwargs), ctx)
    assert second.verdict == DENY
    assert second.reason_code == "AUTH_TOKEN_REPLAYED"


def test_r7_valid_token_allow(token_gate):
    gate, verifier = token_gate
    token = verifier.mint("bob", "n2")
    decision = gate.evaluate(
        _good_cmd(authorization_token=token, nonce="n2"),
        fresh_ctx(),
    )
    assert decision.verdict == ALLOW


# ---------------------------------------------------------------------------
# R8 — connection health + heartbeat
# ---------------------------------------------------------------------------


def test_r8_connection_unhealthy_deny(gate, zero_motion_calls):
    ctx = fresh_ctx(connection_healthy=False)
    decision = gate.evaluate(_good_cmd(), ctx)
    assert decision.verdict == DENY
    assert decision.reason_code == "CONNECTION_UNHEALTHY"
    assert zero_motion_calls


def test_r8_heartbeat_lost_deny_and_force_zero_motion(gate, zero_motion_calls):
    ctx = SafetyContext(last_heartbeat_ms=0)
    decision = gate.evaluate(_good_cmd(), ctx, now_ms=10_000)
    assert decision.verdict == DENY
    assert decision.reason_code == "HEARTBEAT_LOST"
    assert zero_motion_calls, "R11 must fire on HEARTBEAT_LOST"


def test_r8_fresh_heartbeat_passes(gate):
    ctx = SafetyContext(last_heartbeat_ms=9_999)
    decision = gate.evaluate(_good_cmd(), ctx, now_ms=10_000)
    assert decision.verdict == ALLOW


# ---------------------------------------------------------------------------
# R9 — e-stop
# ---------------------------------------------------------------------------


def test_r9_estop_engaged_deny(gate, zero_motion_calls):
    ctx = fresh_ctx(estop_engaged=True)
    decision = gate.evaluate(_good_cmd(), ctx)
    assert decision.verdict == DENY
    assert decision.reason_code == "ESTOP_ENGAGED"
    assert zero_motion_calls


def test_r9_estop_engaged_but_stop_is_allowed(gate, zero_motion_calls):
    """The whole point of stop is to be possible in degraded states."""
    ctx = fresh_ctx(estop_engaged=True)
    stop_cmd = _good_cmd(
        linear_velocity_mps=0.0,
        angular_velocity_radps=0.0,
        duration_s=0.001,
        capability="stop",
    )
    decision = gate.evaluate(stop_cmd, ctx)
    assert decision.verdict == ALLOW
    assert not zero_motion_calls, "Allow on stop, no zero-motion pulse"


# ---------------------------------------------------------------------------
# R10 — capability
# ---------------------------------------------------------------------------


def test_r10_unknown_capability_deny(gate, zero_motion_calls):
    with pytest.raises(ValueError):
        # The constructor rejects unknown capabilities — verifying the
        # gate never sees one. Use a hand-crafted dict to bypass.
        RoverCommand.from_dict(
            {
                "linear_velocity_mps": 0.0,
                "angular_velocity_radps": 0.0,
                "duration_s": 1.0,
                "capability": "fly",
            }
        )


def test_r10_stop_allowed_even_with_no_other_capability(gate, zero_motion_calls):
    stop_cmd = _good_cmd(
        linear_velocity_mps=0.0,
        angular_velocity_radps=0.0,
        duration_s=0.001,
        capability="stop",
    )
    decision = gate.evaluate(stop_cmd, fresh_ctx())
    assert decision.verdict == ALLOW


# ---------------------------------------------------------------------------
# R11 — zero-motion pulse on every deny
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build_ctx",
    [
        lambda: fresh_ctx(estop_engaged=True),
        lambda: fresh_ctx(connection_healthy=False),
    ],
)
def test_r11_zero_motion_pulse_fires_on_deny(
    gate, zero_motion_calls, build_ctx
):
    gate.evaluate(_good_cmd(), build_ctx())
    assert len(zero_motion_calls) == 1
    cmd, _ = zero_motion_calls[0]
    assert cmd.linear_velocity_mps == 0.0
    assert cmd.angular_velocity_radps == 0.0


def test_r11_no_zero_motion_on_allow(gate, zero_motion_calls):
    gate.evaluate(_good_cmd(), fresh_ctx())
    assert zero_motion_calls == []


def test_r11_no_zero_motion_on_reduce(gate, zero_motion_calls):
    gate.evaluate(_good_cmd(linear_velocity_mps=2.5), fresh_ctx())
    assert zero_motion_calls == []


# ---------------------------------------------------------------------------
# R12 — internal exception swallowing
# ---------------------------------------------------------------------------


def test_r12_gate_swallows_unexpected_exception(
    gate, zero_motion_calls, monkeypatch
):
    # Inject a deterministic failure inside the gate
    def boom(*a, **kw):
        raise RuntimeError("boom")

    # Patch the operators registry to raise. The gate must not propagate.
    monkeypatch.setattr(gate._ops, "is_authorized", boom)
    decision = gate.evaluate(_good_cmd(), fresh_ctx())
    assert decision.verdict == DENY
    assert decision.reason_code == "SAFETY_GATE_INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# Decision shape / behavior
# ---------------------------------------------------------------------------


def test_allow_returns_same_command_unchanged(gate, ctx):
    cmd = _good_cmd(linear_velocity_mps=0.3, angular_velocity_radps=0.1)
    decision = gate.evaluate(cmd, ctx)
    assert decision.verdict == ALLOW
    assert decision.commanded == cmd


def test_reduce_returns_new_command_original_unchanged(gate, ctx):
    cmd = _good_cmd(linear_velocity_mps=2.5, angular_velocity_radps=2.0)
    decision = gate.evaluate(cmd, ctx)
    assert decision.verdict == REDUCE
    assert cmd.linear_velocity_mps == 2.5, "original must not be mutated"
    assert cmd.angular_velocity_radps == 2.0, "original must not be mutated"
    assert decision.commanded.linear_velocity_mps == pytest.approx(1.0)
    assert decision.commanded.angular_velocity_radps == pytest.approx(0.5)


def test_decision_audit_id_is_32_char_hex(gate, ctx):
    d = gate.evaluate(_good_cmd(), ctx)
    assert len(d.audit_id) == 32


# ---------------------------------------------------------------------------
# Thread safety (smoke)
# ---------------------------------------------------------------------------


def test_concurrent_evaluations_are_safe(gate, ctx):
    results: List[SafetyDecision] = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(gate.evaluate(_good_cmd(), ctx))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8
    ids = {r.audit_id for r in results}
    assert len(ids) == 8  # no duplicates


# ---------------------------------------------------------------------------
# Decision dataclass validation
# ---------------------------------------------------------------------------


def test_decision_rejects_bad_verdict():
    with pytest.raises(ValueError, match="verdict"):
        SafetyDecision(
            verdict="bogus",
            commanded=zero_motion(),
            reason="",
            reason_code="",
            audit_id="0" * 32,
        )


def test_decision_rejects_short_audit_id():
    with pytest.raises(ValueError, match="audit_id"):
        SafetyDecision(
            verdict=ALLOW,
            commanded=zero_motion(),
            audit_id="abc",
        )


def test_decision_reduces_must_carry_non_zero_command():
    """REDUCE verdict must carry a command the adapter should run."""
    with pytest.raises(ValueError, match="REDUCE"):
        SafetyDecision(
            verdict=REDUCE,
            commanded=zero_motion(),
            reason_code="X",
            audit_id="0" * 32,
        )


def test_decision_deny_requires_reason_code():
    with pytest.raises(ValueError, match="DENY"):
        SafetyDecision(
            verdict=DENY,
            commanded=zero_motion(),
            audit_id="0" * 32,
        )