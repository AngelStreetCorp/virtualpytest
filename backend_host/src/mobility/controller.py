"""
MobilityController — the contract every adapter must satisfy.

The Protocol below is the language the SafetyGate and the API speak to
the rover. PR 1 ships :class:`FakeMobilityController` (deterministic,
in-process, no simulator). PR 2 will ship a Gazebo / ROS 2 adapter; PR 4
a physical-rover mock adapter. Both MUST satisfy this Protocol — that is
how the contract tests pin cross-adapter behaviour.

``BaseMobilityController`` is a minimal concrete base that:
- owns the in-process ``SafetyContext``,
- tracks the last commanded velocity so a subsequent ``telemetry()`` can
  report it,
- provides default implementations for ``stop()`` and ``connect()``,
- forwards every command through ``self._gate.evaluate`` before
  executing it (the adapter cannot bypass the gate).

Adapters implement ``_execute_command`` (the actual hardware / sim call)
and ``telemetry`` (read state) and ``camera`` / ``measure`` (read
sensors). Anything else (connect/disconnect, fault injection for tests)
is optional.

Stop semantics
--------------
``stop()`` is unconditional. It does NOT require the gate to evaluate
the command — the gate allows ``stop`` even when e-stop is engaged,
the connection is unhealthy, or the heartbeat is lost. Stop is the
recovery path; it must always succeed.

Connection / heartbeat
----------------------
The base tracks ``last_heartbeat_ms``. Adapters MUST call
:meth_hook(``heartbeat``) on every positive liveness event. The
:class:`SafetyGate` will deny any non-stop command if the gap exceeds
``heartbeat_timeout_ms``.
"""
from __future__ import annotations

import threading
import time
from typing import Iterable, List, Optional, Protocol, runtime_checkable

from .config import MobilityConfig
from .models import (
    MobilityObservation,
    RoverCommand,
    RoverState,
    is_valid_capability,
    zero_motion,
)
from .safety import (
    ALLOW,
    REDUCE,
    SafetyContext,
    SafetyDecision,
    SafetyGate,
)


@runtime_checkable
class MobilityController(Protocol):
    """The contract every adapter satisfies."""

    adapter_id: str

    def connect(self) -> bool: ...
    def disconnect(self) -> bool: ...
    def execute_command(self, cmd: RoverCommand) -> SafetyDecision: ...
    def telemetry(self) -> RoverState: ...
    def camera(self) -> Optional[str]: ...
    def measure(self) -> float: ...
    def stop(self) -> SafetyDecision: ...
    def heartbeat(self) -> None: ...


class BaseMobilityController:
    """Minimal shared logic — adapters override ``_execute_command`` and
    any sensor calls they actually implement.
    """

    adapter_id: str = "base"

    def __init__(
        self,
        config: MobilityConfig,
        gate: SafetyGate,
        initial_position: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        self._config = config
        self._gate = gate
        self._ctx = SafetyContext(
            connection_healthy=True,
            last_heartbeat_ms=int(time.time() * 1000),
            estop_engaged=False,
            current_position=initial_position,
        )
        self._lock = threading.RLock()
        self._audit_log: List[SafetyDecision] = []
        self._observations: List[MobilityObservation] = []
        self._last_decision: Optional[SafetyDecision] = None
        self._last_command: Optional[RoverCommand] = None

    # ---- public API -------------------------------------------------------

    def connect(self) -> bool:
        self._ctx.connection_healthy = True
        self._ctx.last_heartbeat_ms = int(time.time() * 1000)
        return True

    def disconnect(self) -> bool:
        self._ctx.connection_healthy = False
        return True

    def execute_command(self, cmd: RoverCommand) -> SafetyDecision:
        """Evaluate ``cmd`` through the gate; on allow/reduce, dispatch to
        the adapter's ``_execute_command``. Always returns the gate's
        decision (the adapter's own errors are surfaced through it).
        """
        with self._lock:
            decision = self._gate.evaluate(cmd, self._ctx)
            self._audit_log.append(decision)
            self._last_decision = decision

            if decision.verdict in (ALLOW, REDUCE):
                try:
                    self._execute_command(decision.commanded)
                    self._last_command = decision.commanded
                except Exception as exc:  # noqa: BLE001
                    # Adapter failure: surface as a deny so the caller
                    # can react. Audit id is preserved for traceability.
                    deny = SafetyDecision(
                        verdict="deny",
                        commanded=zero_motion(operator_id=cmd.operator_id),
                        reason=f"adapter exception: {exc!r}",
                        reason_code="ADAPTER_EXCEPTION",
                        audit_id=decision.audit_id,
                    )
                    self._audit_log.append(deny)
                    self._last_decision = deny
                    return deny
            return decision

    def stop(self) -> SafetyDecision:
        """Bring the rover to zero-motion immediately, bypassing R7..R10.

        The gate short-circuits on ``capability == "stop"`` so this works
        even when e-stop is engaged, the connection is unhealthy, or the
        heartbeat is lost.
        """
        with self._lock:
            cmd = RoverCommand(
                linear_velocity_mps=0.0,
                angular_velocity_radps=0.0,
                duration_s=0.001,
                capability="stop",
                operator_id=self._last_command.operator_id
                if self._last_command
                else "",
                reason="user-initiated stop",
            )
            decision = self._gate.evaluate(cmd, self._ctx)
            self._audit_log.append(decision)
            if decision.verdict in (ALLOW, REDUCE):
                try:
                    self._execute_command(decision.commanded)
                    self._last_command = decision.commanded
                except Exception as exc:  # noqa: BLE001
                    deny = SafetyDecision(
                        verdict="deny",
                        commanded=zero_motion(operator_id=cmd.operator_id),
                        reason=f"adapter exception on stop: {exc!r}",
                        reason_code="ADAPTER_EXCEPTION",
                        audit_id=decision.audit_id,
                    )
                    self._audit_log.append(deny)
                    return deny
            return decision

    def heartbeat(self) -> None:
        """Refresh the liveness timestamp."""
        self._ctx.last_heartbeat_ms = int(time.time() * 1000)

    def telemetry(self) -> RoverState:
        """Read the current rover state. Default implementation returns
        the last commanded velocity at the last known position; adapters
        override for richer telemetry.
        """
        with self._lock:
            last = self._last_command
            pos = self._ctx.current_position
        return RoverState(
            position_x=pos[0],
            position_y=pos[1],
            heading_rad=0.0,
            linear_velocity_mps=last.linear_velocity_mps if last else 0.0,
            angular_velocity_radps=last.angular_velocity_radps if last else 0.0,
            battery_pct=100.0,
            sensor_health={"lidar": "ok"},
            timestamp_ms=int(time.time() * 1000),
        )

    def camera(self) -> Optional[str]:
        """Return a path to a captured frame, or ``None``.

        Default implementation returns ``None`` — only the fake adapter
        provides a placeholder PNG.
        """
        return None

    def measure(self) -> float:
        """Return a sensor reading. Default returns 0.0."""
        return 0.0

    # ---- introspection ----------------------------------------------------

    @property
    def audit_log(self) -> tuple[SafetyDecision, ...]:
        """Read-only view of every decision the gate has produced."""
        with self._lock:
            return tuple(self._audit_log)

    @property
    def observations(self) -> tuple[MobilityObservation, ...]:
        with self._lock:
            return tuple(self._observations)

    @property
    def context(self) -> SafetyContext:
        return self._ctx

    # ---- adapter hook (override) -----------------------------------------

    def _execute_command(self, cmd: RoverCommand) -> None:
        """Default no-op. Adapters override with the hardware / sim call."""
        return None

    # ---- observation helper ----------------------------------------------

    def _record_observation(
        self,
        timestamp_ms: int,
        position: tuple[float, float],
        heading: float,
        event: str = "",
        sensor_health: Optional[dict] = None,
    ) -> None:
        """Append an observation to the run trace.

        Adapters call this whenever they want the run's trace to
        capture a moment (curb detected, obstacle reroute, etc.). The
        fake uses it densely; physical adapters can use it sparingly.
        """
        last = self._last_command
        obs = MobilityObservation(
            timestamp_ms=timestamp_ms,
            position_x=position[0],
            position_y=position[1],
            heading_rad=heading,
            linear_velocity_mps=last.linear_velocity_mps if last else 0.0,
            angular_velocity_radps=last.angular_velocity_radps if last else 0.0,
            sensor_health=dict(sensor_health or {}),
            event=event,
        )
        with self._lock:
            self._observations.append(obs)
            self._ctx.current_position = position

    # ---- capability check (adapters may extend) ---------------------------

    def supports_capability(self, capability: str) -> bool:
        """Default: every adapter in PR 1 supports every capability."""
        return is_valid_capability(capability)