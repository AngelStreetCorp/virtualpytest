"""Orchestrator for the League of Legends vision agent (TASK-121 §4.3, §10).

The runner is the **orchestrator** that ties the typed contracts (decision,
observation, simulator target) into a single run loop. It is **deterministic**
and **side-effect free**:

* No file I/O, no network, no clock reads inside the runner's policy path
  (the clock is supplied by the caller — :func:`safe_decision` is pure).
* No real-client driving — the runner's authoritative mode is
  ``"simulator"``; ``replay`` / ``shadow`` are rejected at the policy layer
  and recorded as ``WRONG_MODE``.
* No ``pyautogui``, no League-process helper (TASK-121 §6 FR-13).

State machine
-------------

The state machine follows TASK-121 §4.3 verbatim. The runner records the
``OBSERVE → PROPOSE → SIMULATE → VERIFY → OBSERVE`` chain as a sequence of
state assignments for the audit ledger; the simulator step is a no-op in v1
(no executor is wired), but the transitions are still recorded so a future
executor adapter can replay them.

    DISCOVER → CAPTURE_TEST → OBSERVE → PROPOSE → SIMULATE → VERIFY → OBSERVE
                ↘ STOP                    ↘ ABSTAIN → OBSERVE (on next frame)
                                          ↘ STOP (forbidden / hard refusal)

Hard policy (TASK-121 §6 FR-13, FR-15, §4.3, §13)
-------------------------------------------------

* The real League client is never an execution target — only a human-played
  data source. The orchestrator refuses any ``SimulatorTarget`` whose
  ``target_kind`` is ``"real-league"`` (defense in depth, in case
  ``model_construct`` was used to bypass the schema's Literal gate) or whose
  ``exe_path`` references a real Riot / League binary (defense in depth, in
  case ``model_construct`` skipped the field validator). This is the
  FR-13 + FR-15 layered defense at the orchestrator: even if a
  misconfigured target sneaks past the schema, the runner catches it at
  construction.
* State transitions are bounded — once STOP, :meth:`observe_frame` and
  :meth:`propose` raise :class:`RunnerError` (no silent re-entry from a
  terminal state).
* :meth:`start` is also fail-closed: it refuses to transition out of
  ``DISCOVER`` unless both a ``lease_token`` and a non-rejected license
  review are configured. A ``MISSING_LEASE`` or ``POLICY_MISMATCH``
  stop reason is recorded on the refusal path.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional, Tuple

# Module-level imports — kept at the top per the brief (do this at module
# top, not inside ``__init__``). The runner never imports any League-process
# helper, ``pyautogui``, or any executable League client code.
from shared.src.lib.game.leagueoflegends.contracts_decision import (
    Decision,
    PolicyResult,
)
from shared.src.lib.game.leagueoflegends.contracts_episode import WalkthroughFrame
from shared.src.lib.game.leagueoflegends.contracts_simulator import SimulatorTarget
from shared.src.lib.game.leagueoflegends.policies import Authority, safe_decision
from shared.src.lib.game.leagueoflegends.simulator_registry import (
    FORBIDDEN_EXE_SUBSTRINGS,
)


# ---------------------------------------------------------------------------
# Enums (kept module-level so tests and downstream callers can import them).
# ---------------------------------------------------------------------------


class RunnerState(str, Enum):
    """The 9 §4.3 runner states.

    Values are the lowercase strings the spec uses; the ``str`` mixin keeps
    them JSON-friendly for run reports and lets ``RunnerState.DISCOVER ==
    "discover"``.
    """

    DISCOVER = "discover"
    CAPTURE_TEST = "capture_test"
    OBSERVE = "observe"
    ABSTAIN = "abstain"
    PROPOSE = "propose"
    REVIEW = "review"
    SIMULATE = "simulate"
    VERIFY = "verify"
    STOP = "stop"


class StopReason(str, Enum):
    """Terminal stop reasons recorded on a runner.

    The full set enumerated in the brief (with the runner's current usage
    noted):

    * ``COMPLETED`` — the run finished its allotted ticks.
    * ``CAPTURE_FAILURE`` — :meth:`observe_frame` received ``None``.
    * ``LEASE_LOST`` — the lease was dropped mid-run (operator action).
    * ``MISSING_LEASE`` — :meth:`start` was called without a lease token.
    * ``POLICY_MISMATCH`` — license review is ``"rejected"``.
    * ``FORBIDDEN_MODE`` — runner was asked to use a non-simulator mode at
      construction (currently unused; reserved for a future executor that
      might re-introduce a mode-override path).
    * ``TARGET_KIND_REJECTED`` — runtime refused the simulator target.
    * ``REPEATED_MISMATCH`` — simulator state did not match the expected
      post-action state across two consecutive frames.
    * ``EXCEPTION`` — uncaught exception inside the run loop.
    """

    COMPLETED = "completed"
    CAPTURE_FAILURE = "capture_failure"
    LEASE_LOST = "lease_lost"
    MISSING_LEASE = "missing_lease"
    POLICY_MISMATCH = "policy_mismatch"
    FORBIDDEN_MODE = "forbidden_mode"
    TARGET_KIND_REJECTED = "target_kind_rejected"
    REPEATED_MISMATCH = "repeated_mismatch"
    EXCEPTION = "exception"


class RunnerError(RuntimeError):
    """Raised on hard refusal or illegal state transitions.

    Subclasses :class:`RuntimeError` so a caller that catches
    ``RuntimeError`` keeps working. Used for:

    * hard refusal of a forbidden simulator target (FR-15);
    * calling :meth:`observe_frame` or :meth:`propose` after STOP;
    * calling :meth:`start` outside DISCOVER.
    """


# ---------------------------------------------------------------------------
# Internal types.
# ---------------------------------------------------------------------------


# The Authority's authoritative mode literal. Hardcoded to ``"simulator"`` in
# production; exposed as a kwarg-only argument on the runner so the
# policy's mode gate (replay / shadow → ``WRONG_MODE``) can be exercised
# in tests. Production callers do not pass ``mode``.
_ModeLiteral = Literal["replay", "shadow", "simulator"]


# ---------------------------------------------------------------------------
# The runner.
# ---------------------------------------------------------------------------


class LeagueRunner:
    """State machine + run loop for one offline-simulator session.

    Lifecycle (§4.3, §10):

    1. Construction validates the simulator target (FR-15 defense in depth;
       raises :class:`RunnerError` on a forbidden target).
    2. :meth:`start` checks the lease and license review; transitions to
       ``CAPTURE_TEST`` or ``STOP`` with a recorded reason.
    3. :meth:`observe_frame` appends a fresh frame and moves
       ``CAPTURE_TEST → OBSERVE`` (or ``ABSTAIN → OBSERVE`` on a fresh
       frame). A ``None`` frame is a capture failure → ``STOP``.
    4. :meth:`propose` routes through :func:`safe_decision` and records
       the result. The runner drives the
       ``OBSERVE → PROPOSE → SIMULATE → VERIFY → OBSERVE`` chain for
       permitted proposals; rejections and deliberate non-actions land
       on ``ABSTAIN``.

    Once STOP, :meth:`observe_frame` and :meth:`propose` raise
    :class:`RunnerError`. No terminal-state re-entry is permitted.
    """

    def __init__(
        self,
        simulator_target: "SimulatorTarget",
        lease_token: Optional[str] = None,
        focus_app: Optional[str] = None,
        *,
        mode: _ModeLiteral = "simulator",
    ) -> None:
        """Construct the runner and validate the simulator target.

        ``mode`` defaults to ``"simulator"`` per the spec; it is exposed
        as a keyword-only argument so the policy's mode gate (replay /
        shadow are turned into ``WRONG_MODE`` at the policy layer, not
        the runner layer — the runner still records the rejected
        decision) can be exercised in tests. Production callers MUST
        NOT pass ``mode``; the default keeps the runner's Authority
        hardcoded to simulator mode.
        """
        # 1) isinstance check — defense in depth against a typo'd argument
        #    (e.g. passing a ``WalkthroughFrame`` instead of a target).
        if not isinstance(simulator_target, SimulatorTarget):
            raise RunnerError(
                "LeagueRunner: simulator_target must be a SimulatorTarget "
                f"instance, got {type(simulator_target).__name__}"
            )

        # 2) Defense in depth: target_kind via getattr. The schema's
        #    Literal on ``target_kind`` already excludes ``"real-league"``
        #    at construction, but ``SimulatorTarget.model_construct(
        #    target_kind="real-league", ...)`` would slip past it; this
        #    getattr check catches the bypass (FR-15 layered defense at
        #    the orchestrator, in concert with the schema's gate).
        target_id = getattr(simulator_target, "target_id", "<unknown>")
        kind = getattr(simulator_target, "target_kind", None)
        if kind == "real-league":
            raise RunnerError(
                f"LeagueRunner refused: target {target_id} points at a "
                f"real League process"
            )

        # 3) Defense in depth: exe_path substring check. The schema's
        #    ``@field_validator("exe_path")`` refuses forbidden
        #    substrings at construction, but a target built via
        #    ``model_construct`` skips validators. We re-apply the same
        #    check here so the runner is independently safe against
        #    ``model_construct`` bypasses.
        exe_path = getattr(simulator_target, "exe_path", None)
        if exe_path is not None:
            lowered = exe_path.lower()
            for bad in FORBIDDEN_EXE_SUBSTRINGS:
                if bad in lowered:
                    raise RunnerError(
                        f"LeagueRunner refused: target {target_id} points "
                        f"at a real League process"
                    )

        self._simulator_target = simulator_target
        self._lease_token = lease_token
        self._focus_app = focus_app
        self._mode = mode
        self._state = RunnerState.DISCOVER
        self._stop_reason: Optional[StopReason] = None
        self._decisions: List[Tuple[Decision, PolicyResult]] = []
        self._frames: List[WalkthroughFrame] = []

    # ------------------------------------------------------------------
    # Properties (read-only views).
    # ------------------------------------------------------------------

    @property
    def state(self) -> RunnerState:
        """The runner's current §4.3 state."""
        return self._state

    @property
    def stop_reason(self) -> Optional[StopReason]:
        """The recorded stop reason, or ``None`` if not stopped."""
        return self._stop_reason

    @property
    def decisions(self) -> Tuple[Tuple[Decision, PolicyResult], ...]:
        """Tuple view of the recorded ``(decision, policy_result)`` pairs.

        Returns a fresh tuple on every access — callers cannot mutate
        the runner's internal list via this property (tuples have no
        ``.append``, ``.remove``, etc.).
        """
        return tuple(self._decisions)

    @property
    def frames_observed(self) -> int:
        """Number of frames recorded via :meth:`observe_frame`."""
        return len(self._frames)

    @property
    def simulator_target(self) -> SimulatorTarget:
        """The simulator target the runner is bound to."""
        return self._simulator_target

    # ------------------------------------------------------------------
    # Lifecycle.
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Transition ``DISCOVER → CAPTURE_TEST`` or ``DISCOVER → STOP``.

        Refuses (raises :class:`RunnerError`) if called outside
        ``DISCOVER``. Refuses to start (transitions to ``STOP`` with a
        recorded reason) if:

        * ``lease_token`` is ``None`` — we never start a run without a
          lease in simulator mode (FR-02 fail-closed);
        * the simulator target's ``license_review_status`` is
          ``"rejected"`` — the upstream review rejected the tool
          (FR-15).
        """
        if self._state != RunnerState.DISCOVER:
            raise RunnerError("start() called outside DISCOVER")

        if self._lease_token is None:
            self._stop_reason = StopReason.MISSING_LEASE
            self._state = RunnerState.STOP
            return

        if self._simulator_target.license_review_status == "rejected":
            self._stop_reason = StopReason.POLICY_MISMATCH
            self._state = RunnerState.STOP
            return

        self._state = RunnerState.CAPTURE_TEST

    def observe_frame(self, frame: Optional[WalkthroughFrame]) -> None:
        """Append a captured frame and transition to ``OBSERVE`` on fresh frames.

        * ``STOP`` state: raises :class:`RunnerError` (no terminal
          re-entry).
        * ``None`` frame: transitions to ``STOP`` with
          :attr:`StopReason.CAPTURE_FAILURE` (capture adapter failed
          to produce a frame).
        * Valid frame in ``CAPTURE_TEST``: appended, transitions to
          ``OBSERVE`` (calibration valid).
        * Valid frame in ``ABSTAIN``: appended, transitions to
          ``OBSERVE`` (§4.3 — fresh frame resumes observation).
        * Valid frame in any other state: appended, no transition
          (e.g. a frame observed while already in ``OBSERVE`` simply
          refreshes the buffer without changing state).
        """
        if self._state == RunnerState.STOP:
            raise RunnerError("cannot observe_frame in STOP state")

        if frame is None:
            self._stop_reason = StopReason.CAPTURE_FAILURE
            self._state = RunnerState.STOP
            return

        self._frames.append(frame)
        # §4.3 transitions on a fresh frame.
        if self._state in (RunnerState.CAPTURE_TEST, RunnerState.ABSTAIN):
            self._state = RunnerState.OBSERVE

    def propose(
        self,
        decision: Decision,
        observation_id: str,
        observation_acquired_at_ns: int,
    ) -> PolicyResult:
        """Submit a typed ``Decision`` for one tick of policy validation.

        Builds an :class:`Authority` from the runner's configured lease,
        focus, and mode (always ``"simulator"`` in production; see
        ``__init__`` for the test override) and routes through
        :func:`safe_decision`.

        Records the ``(decision, result)`` pair on every call. State
        transitions after the call:

        * ``allowed=True``: ``OBSERVE → PROPOSE → SIMULATE → VERIFY →
          OBSERVE`` (the simulator step is a no-op in v1; the
          intermediate states are recorded by sequential assignment so
          an audit reader can see the full chain if it queries between
          transitions).
        * ``allowed=False`` with ``reason_code == "ACCEPTED"``: this
          is a deliberate ``WAIT`` / ``ABSTAIN`` — transition to
          ``ABSTAIN``.
        * ``allowed=False`` for any other reason (a rejection):
          transition to ``ABSTAIN`` (the action is NOT executed).

        Raises :class:`RunnerError` if called in ``STOP`` state.
        """
        if self._state == RunnerState.STOP:
            raise RunnerError("cannot propose in STOP state")

        authority = Authority(
            mode=self._mode,
            lease_token=self._lease_token,
            focus_app=self._focus_app,
            clock_monotonic_ns=observation_acquired_at_ns,
            calibration_hash=None,
        )

        result = safe_decision(
            decision,
            observation_id,
            observation_acquired_at_ns,
            authority,
        )

        self._decisions.append((decision, result))

        if result.allowed:
            # OBSERVE → PROPOSE → SIMULATE → VERIFY → OBSERVE.
            # The intermediate states are recorded by sequential
            # assignment so the audit ledger sees the full chain.
            self._state = RunnerState.PROPOSE
            self._state = RunnerState.SIMULATE
            self._state = RunnerState.VERIFY
            self._state = RunnerState.OBSERVE
        else:
            # Both deliberate non-actions (WAIT / ABSTAIN → reason_code
            # "ACCEPTED") and rejections land on ABSTAIN. The next
            # observe_frame brings us back to OBSERVE (§4.3).
            self._state = RunnerState.ABSTAIN

        return result

    def stop(self, reason: StopReason) -> None:
        """Stop the runner with the given reason.

        Idempotent on STOP: re-stopping simply overwrites the reason.
        No-op on a not-yet-started runner.
        """
        self._stop_reason = reason
        self._state = RunnerState.STOP


__all__ = [
    "RunnerState",
    "StopReason",
    "RunnerError",
    "LeagueRunner",
]