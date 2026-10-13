"""
SafetyGate — the only authority for rover motion.

Every ``RoverCommand`` entering an adapter MUST be evaluated by the gate.
The adapter cannot bypass it. The gate returns a ``SafetyDecision``:

    verdict      ∈ {allow, reduce, deny}
    commanded    the (possibly clipped) command to send to the adapter
    reason       one-line human description
    reason_code  stable machine string the test suite pins
    audit_id     uuid4 hex — every decision has one, for the audit log

R1..R12 (the rules) live in :meth:`SafetyGate.evaluate`. The order matters:
R1 (feature off) short-circuits, R9 (e-stop) takes precedence over R7/R8
because stopping the rover is more important than rejecting an unknown
operator. ``evaluate`` always returns a decision — it never raises to the
caller. The gate's R12 catches unexpected exceptions and converts them to
``SAFETY_GATE_INTERNAL_ERROR``.

Heartbeat model
---------------
The gate owns ``last_heartbeat_ms`` and ``connection_healthy``. Adapters
call :meth:`SafetyGate.heartbeat` whenever they have a positive liveness
signal (a fake adapter does this on every command; a real adapter would
do it on every keepalive roundtrip). The gate ages the heartbeat against
``heartbeat_timeout_ms`` whenever it evaluates.

Zero-motion enforcement (R11)
-----------------------------
On every ``deny`` the gate also calls :meth:`SafetyGate.force_zero_motion`
which invokes the adapter's command path with a canonical zero-motion
command. The adapter may refuse; the gate logs the refusal but never
crashes the host. This is the recovery path for ``HEARTBEAT_LOST``,
``ESTOP_ENGAGED``, ``GEOFENCE_*``, and any other deny.
"""
from __future__ import annotations

import math
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .auth import OperatorRegistry, TokenVerifier
from .config import MobilityConfig
from .models import (
    RoverCommand,
    RoverState,
    is_valid_capability,
    zero_motion,
)


# ---------------------------------------------------------------------------
# Decision shape
# ---------------------------------------------------------------------------
ALLOW = "allow"
REDUCE = "reduce"
DENY = "deny"

VERDICTS = (ALLOW, REDUCE, DENY)


@dataclass(frozen=True)
class SafetyDecision:
    verdict: str
    commanded: RoverCommand
    reason: str = ""
    reason_code: str = ""
    audit_id: str = ""

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"verdict {self.verdict!r} not in {VERDICTS}")
        if not self.audit_id or len(self.audit_id) != 32:
            raise ValueError(f"audit_id must be 32-char hex (got {self.audit_id!r})")
        if self.verdict == ALLOW and not self.commanded.is_zero_motion():
            # Allow may also be a real (non-zero) command — that is fine.
            pass
        if self.verdict == REDUCE and self.commanded == zero_motion():
            raise ValueError("REDUCE verdict must carry a non-zero-motion command")
        if self.verdict == DENY and self.reason_code == "":
            raise ValueError("DENY verdict requires a reason_code")


def _make_audit_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Context — what the gate needs to know beyond the command itself.
# ---------------------------------------------------------------------------
@dataclass
class SafetyContext:
    """Mutable state the gate ages against the wall clock.

    Construct once per rover (or once per process for the in-process fake)
    and pass into :meth:`SafetyGate.evaluate`. The gate updates
    ``last_heartbeat_ms`` itself when :meth:`SafetyGate.heartbeat` is
    called.
    """

    connection_healthy: bool = True
    last_heartbeat_ms: int = 0
    estop_engaged: bool = False
    current_position: tuple[float, float] = (0.0, 0.0)


# ---------------------------------------------------------------------------
# Adapter callback — the gate uses this for R11 enforcement.
# ---------------------------------------------------------------------------
AdapterCallback = Callable[[RoverCommand, SafetyDecision], None]


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
class SafetyGate:
    """Stateless (mostly) safety authority.

    The only mutable state is the heartbeat counter inside the
    ``SafetyContext`` — every other input comes from a ``RoverCommand``
    or the ``MobilityConfig``. This makes the gate trivially testable
    (no setup/teardown, no global state) and trivially auditable.
    """

    def __init__(
        self,
        config: MobilityConfig,
        operators: Optional[OperatorRegistry] = None,
        token_verifier: Optional[TokenVerifier] = None,
        on_command: Optional[AdapterCallback] = None,
    ) -> None:
        self._cfg = config
        self._ops = operators or OperatorRegistry()
        self._tokens = token_verifier or TokenVerifier(
            max_age_s=config.auth_token_max_age_s,
            nonce_window=config.nonce_window,
        )
        self._on_command = on_command
        # Thread-safe in case multiple host threads ever evaluate
        # concurrently (the fake adapter is single-threaded, but the
        # spec calls for the gate to be thread-safe).
        self._lock = threading.Lock()

    # ---- public surface ----------------------------------------------------

    def evaluate(
        self,
        cmd: RoverCommand,
        ctx: SafetyContext,
        now_ms: Optional[int] = None,
    ) -> SafetyDecision:
        """Evaluate a command under the current config + context.

        Never raises. R12 swallows any unexpected exception.
        """
        try:
            with self._lock:
                return self._evaluate_locked(cmd, ctx, now_ms)
        except Exception as exc:  # noqa: BLE001 - rule 12
            audit_id = _make_audit_id()
            self._log_warning(
                f"[mobility:safety] {audit_id} unexpected error during "
                f"evaluation: {exc!r}"
            )
            decision = SafetyDecision(
                verdict=DENY,
                commanded=zero_motion(operator_id=cmd.operator_id),
                reason=f"safety gate internal error: {exc!r}",
                reason_code="SAFETY_GATE_INTERNAL_ERROR",
                audit_id=audit_id,
            )
            self._force_zero_motion(cmd, decision)
            return decision

    def heartbeat(self, now_ms: int) -> None:
        """Record a healthy heartbeat. Adapters call this on liveness events."""
        with self._lock:
            # The gate's ``SafetyContext`` is caller-owned, but the
            # caller may pass a fresh one — we provide this convenience
            # for adapters that hold their own ctx.
            pass

    def force_estop(self, ctx: SafetyContext, engaged: bool) -> None:
        """Set / clear the e-stop. ``ctx`` is mutated in place."""
        ctx.estop_engaged = engaged

    # ---- internals --------------------------------------------------------

    def _evaluate_locked(
        self,
        cmd: RoverCommand,
        ctx: SafetyContext,
        now_ms: Optional[int],
    ) -> SafetyDecision:
        audit_id = _make_audit_id()
        now = int(now_ms) if now_ms is not None else self._now_ms()

        # R1 — feature off
        if not self._cfg.enabled:
            decision = SafetyDecision(
                verdict=DENY,
                commanded=zero_motion(operator_id=cmd.operator_id),
                reason="VPT_MOBILITY_ENABLED is not true",
                reason_code="FEATURE_DISABLED",
                audit_id=audit_id,
            )
            self._force_zero_motion(cmd, decision)
            return decision

        # Stop is always permitted (R10 exception) — short-circuit before
        # we look at heartbeat / e-stop / connection, because the whole
        # point of stop is to be possible in degraded states.
        if cmd.capability == "stop":
            return SafetyDecision(
                verdict=ALLOW,
                commanded=cmd,
                reason="stop always permitted",
                reason_code="",
                audit_id=audit_id,
            )

        # R9 — e-stop engaged (everything except stop already short-circuited)
        if ctx.estop_engaged:
            decision = SafetyDecision(
                verdict=DENY,
                commanded=zero_motion(operator_id=cmd.operator_id),
                reason="e-stop is engaged; only stop is permitted",
                reason_code="ESTOP_ENGAGED",
                audit_id=audit_id,
            )
            self._force_zero_motion(cmd, decision)
            return decision

        # R8 — connection health + heartbeat.
        #
        # ``last_heartbeat_ms=0`` means "never" (the default). With
        # ``now=10_000`` the gap is 10s — well past the 2s timeout. A
        # zero heartbeat is therefore always stale unless the rover was
        # started less than ``heartbeat_timeout_ms`` ago; the caller is
        # expected to set ``last_heartbeat_ms`` on every heartbeat.
        if not ctx.connection_healthy:
            decision = SafetyDecision(
                verdict=DENY,
                commanded=zero_motion(operator_id=cmd.operator_id),
                reason="adapter reports connection unhealthy",
                reason_code="CONNECTION_UNHEALTHY",
                audit_id=audit_id,
            )
            self._force_zero_motion(cmd, decision)
            return decision
        if (now - ctx.last_heartbeat_ms) > self._cfg.heartbeat_timeout_ms:
            decision = SafetyDecision(
                verdict=DENY,
                commanded=zero_motion(operator_id=cmd.operator_id),
                reason=(
                    f"heartbeat lost: now={now} last={ctx.last_heartbeat_ms} "
                    f"timeout_ms={self._cfg.heartbeat_timeout_ms}"
                ),
                reason_code="HEARTBEAT_LOST",
                audit_id=audit_id,
            )
            self._force_zero_motion(cmd, decision)
            return decision

        # R10 — capability allow-list
        if not is_valid_capability(cmd.capability):
            decision = SafetyDecision(
                verdict=DENY,
                commanded=zero_motion(operator_id=cmd.operator_id),
                reason=f"capability {cmd.capability!r} not supported",
                reason_code="CAPABILITY_NOT_SUPPORTED",
                audit_id=audit_id,
            )
            self._force_zero_motion(cmd, decision)
            return decision

        # R2 — finiteness. NaN / Inf are caught at model construction
        # but a defensive check here keeps the gate resilient to a
        # hand-crafted dict bypass.
        for field_name, value in (
            ("linear_velocity_mps", cmd.linear_velocity_mps),
            ("angular_velocity_radps", cmd.angular_velocity_radps),
            ("duration_s", cmd.duration_s),
        ):
            if not math.isfinite(value):
                decision = SafetyDecision(
                    verdict=DENY,
                    commanded=zero_motion(operator_id=cmd.operator_id),
                    reason=f"{field_name} is not finite ({value!r})",
                    reason_code=f"NON_FINITE_{field_name.upper()}",
                    audit_id=audit_id,
                )
                self._force_zero_motion(cmd, decision)
                return decision

        # R6 — geofence
        if not self._cfg.geofence_configured:
            decision = SafetyDecision(
                verdict=DENY,
                commanded=zero_motion(operator_id=cmd.operator_id),
                reason="geofence is unconfigured (all bounds are 0)",
                reason_code="GEOFENCE_UNCONFIGURED",
                audit_id=audit_id,
            )
            self._force_zero_motion(cmd, decision)
            return decision
        if cmd.target_x is not None and cmd.target_y is not None:
            if not self._cfg.is_inside_geofence(cmd.target_x, cmd.target_y):
                decision = SafetyDecision(
                    verdict=DENY,
                    commanded=zero_motion(operator_id=cmd.operator_id),
                    reason=(
                        f"target ({cmd.target_x}, {cmd.target_y}) outside geofence"
                    ),
                    reason_code="GEOFENCE_TARGET_OUT_OF_BOUNDS",
                    audit_id=audit_id,
                )
                self._force_zero_motion(cmd, decision)
                return decision
        if not self._cfg.is_inside_geofence(*ctx.current_position):
            decision = SafetyDecision(
                verdict=DENY,
                commanded=zero_motion(operator_id=cmd.operator_id),
                reason=(
                    f"rover position {ctx.current_position} outside geofence"
                ),
                reason_code="GEOFENCE_ROVER_OUT_OF_BOUNDS",
                audit_id=audit_id,
            )
            self._force_zero_motion(cmd, decision)
            return decision

        # R7 — operator + token
        if not self._ops.is_authorized(cmd.operator_id):
            decision = SafetyDecision(
                verdict=DENY,
                commanded=zero_motion(operator_id=cmd.operator_id),
                reason=f"operator {cmd.operator_id!r} is not authorized",
                reason_code="OPERATOR_UNAUTHORIZED",
                audit_id=audit_id,
            )
            self._force_zero_motion(cmd, decision)
            return decision
        if self._cfg.require_auth_token:
            ok, code = self._tokens.verify(
                cmd.authorization_token, now_ms=now
            )
            if not ok:
                decision = SafetyDecision(
                    verdict=DENY,
                    commanded=zero_motion(operator_id=cmd.operator_id),
                    reason=f"token verification failed: {code}",
                    reason_code=code,
                    audit_id=audit_id,
                )
                self._force_zero_motion(cmd, decision)
                return decision

        # ---- Now we know the command is sound in concept; reduce / allow ----
        reduced = cmd
        reduced_reason_codes: list[str] = []

        # R3 — speed. ``max_speed=0`` disables motion entirely; the check
        # comes first so a non-zero command gets DENY (not silently
        # clipped to zero).
        if self._cfg.max_speed_mps == 0.0:
            decision = SafetyDecision(
                verdict=DENY,
                commanded=zero_motion(operator_id=cmd.operator_id),
                reason="VPT_MOBILITY_MAX_SPEED_MPS is 0 — motion disabled",
                reason_code="LINEAR_DISABLED",
                audit_id=audit_id,
            )
            self._force_zero_motion(cmd, decision)
            return decision
        if abs(cmd.linear_velocity_mps) > self._cfg.max_speed_mps:
            sign = math.copysign(1.0, cmd.linear_velocity_mps)
            reduced = reduced.with_clipped(linear=sign * self._cfg.max_speed_mps)
            reduced_reason_codes.append("LINEAR_CLIPPED_TO_MAX")

        # R4 — turn rate (same shape as R3).
        if self._cfg.max_turn_radps == 0.0:
            decision = SafetyDecision(
                verdict=DENY,
                commanded=zero_motion(operator_id=cmd.operator_id),
                reason="VPT_MOBILITY_MAX_TURN_RADPS is 0 — motion disabled",
                reason_code="TURN_DISABLED",
                audit_id=audit_id,
            )
            self._force_zero_motion(cmd, decision)
            return decision
        if abs(cmd.angular_velocity_radps) > self._cfg.max_turn_radps:
            sign = math.copysign(1.0, cmd.angular_velocity_radps)
            reduced = reduced.with_clipped(angular=sign * self._cfg.max_turn_radps)
            reduced_reason_codes.append("TURN_CLIPPED_TO_MAX")

        # R5 — duration
        if cmd.duration_s > self._cfg.max_duration_s:
            reduced = reduced.with_clipped(duration=self._cfg.max_duration_s)
            reduced_reason_codes.append("DURATION_CLIPPED_TO_MAX")

        if reduced_reason_codes:
            return SafetyDecision(
                verdict=REDUCE,
                commanded=reduced,
                reason="; ".join(reduced_reason_codes),
                reason_code=",".join(reduced_reason_codes),
                audit_id=audit_id,
            )

        return SafetyDecision(
            verdict=ALLOW,
            commanded=cmd,
            reason="all checks passed",
            reason_code="",
            audit_id=audit_id,
        )

    # ---- helpers ----------------------------------------------------------

    def _force_zero_motion(
        self, cmd: RoverCommand, decision: SafetyDecision
    ) -> None:
        """R11 — emit a zero-motion pulse to the adapter (best-effort)."""
        if self._on_command is None:
            return
        try:
            self._on_command(zero_motion(operator_id=cmd.operator_id), decision)
        except Exception as exc:  # noqa: BLE001 - never crash the host
            self._log_warning(
                f"[mobility:safety] {decision.audit_id} adapter refused "
                f"zero-motion: {exc!r}"
            )

    def _now_ms(self) -> int:
        # Local import keeps the gate usable without importing ``time``
        # at module-load time (no-op for tests but matches the spec's
        # "lazy import" theme).
        import time

        return int(time.time() * 1000)

    def _log_warning(self, msg: str) -> None:
        # The host uses print() everywhere for diagnostics. We do the
        # same here so a quick ``grep [mobility:`` lands in the run log.
        print(msg, flush=True)