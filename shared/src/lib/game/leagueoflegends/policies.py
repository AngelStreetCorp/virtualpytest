"""Decision-policy validator for the League of Legends vision agent (TASK-121 §8).

The single entry point is :func:`safe_decision`. Given a typed
:class:`~contracts_decision.Decision` proposal together with the
authoritative observation reference, lease token and clock, it returns a
:class:`~contracts_decision.PolicyResult` that is either:

* a *permitted* simulator action (``allowed=True``, ``reason_code="ACCEPTED"``);
* a *rejected* proposal (``allowed=False``, named reason); or
* a recorded non-action ``WAIT`` / ``ABSTAIN`` (still
  ``reason_code="ACCEPTED"`` because the agent deliberately chose to
  not act — see the rationale in §priority below).

Hard policy (TASK-121 §6 FR-06, FR-07, FR-13, §8, §13):

* The real League client is a human-played data source only.
* The schema/policy MUST never import ``pyautogui`` or any League-process
  helper.
* ``mode`` is **read from the trusted runner's :class:`Authority`**; the
  ``policy_mode`` field on ``Decision`` is an LLM-supplied hint that this
  module ignores for the mode check (TASK-121 §8 guarding principle).
* :func:`safe_decision` is **deterministic** — same inputs always yield
  the same result — and **side-effect free** — no I/O, no logging
  side-channels, no clock reads inside the function body (the clock is
  provided as a parameter).
* :func:`safe_decision` must **never raise** for input that has already
  passed Pydantic validation. Every branch ends in a constructed
  :class:`PolicyResult`.

Priority order
--------------

The rejection precedence is fixed by the spec so the orchestrator gets
*one* canonical reason per tick regardless of how many checks would
otherwise have failed. In priority order (lowest number = checked first):

1. **STALE_OBSERVATION** (observation_id mismatch or stale clock) —
   beats everything else; an agent that is asking us to act on the wrong
   frame is fundamentally broken, the rest doesn't matter.
2. **ACCEPTED-with-non-action** for ``ABSTAIN`` and ``WAIT`` —
   recorded before the mode check because the agent deliberately chose
   to not act; recording it in ``replay`` is just as valid as recording
   it in ``simulator``.
3. **WRONG_MODE** for ``replay`` / ``shadow`` — the agent may only
   execute against an offline simulator; this gate is *before*
   ``MISSING_LEASE`` / ``DISABLED_FOCUS`` because in ``replay`` mode
   the lease and focus are not relevant.
4. **MISSING_LEASE** when simulator mode has no lease token.
5. **DISABLED_FOCUS** when simulator mode has no focus app.
6. **LOW_CONFIDENCE** for ``confidence < 0.3``.
7. **UNSAFE_COORDINATES** for ``MOVE``/``ATTACK_MOVE``/``RETREAT`` with
   out-of-range target (NaN/inf is already blocked at the Point validator;
   this is defense in depth for a future refactor that may loosen the
   validator).
8. **UNRECOGNIZED_SPELL** for ``CAST_SPELL`` with an off-bag spell
   (defense in depth; ``Literal["Q","W","E","R"]`` already enforces).

If none of the rejection branches fire we reach the **default ACCEPTED**
branch and the proposal is permitted, with ``effective_action`` set to
the very action the agent proposed.

``ABSTAIN`` / ``WAIT`` semantics
--------------------------------

Both ``ABSTAIN`` and ``WAIT`` set ``allowed=False`` and set
``effective_action`` to *the very action the agent emitted* (not
``None``). They are deliberate non-actions: the agent is telling us
"don't act on this tick". The orchestrator still records them in the
run ledger so an analyst can see what the agent would have proposed
had it not chosen to abstain. ``reason_code="ACCEPTED"`` because the
proposal was *accepted*, just not *executed*.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.src.lib.game.leagueoflegends.contracts_decision import (
    Action,
    Decision,
    PolicyResult,
)


# Documentation pointer (TASK-121 §8). Surfaced in run reports so an
# analyst can trace a rejection back to the spec section that defines
# the priority order. The path matches the in-repo doc layout; if it
# ever moves the tests in :mod:`tests.shared.test_leagueoflegends_policies`
# should be updated.
POLICY_DOC_URL: str = (
    "docs/tasks/TASK-121-league-of-legends-windows-vision-agent.md"
    "#8-typed-contract"
)


# ---------------------------------------------------------------------------
# Authority (trusted runner configuration).
# ---------------------------------------------------------------------------


class Authority(BaseModel):
    """The trusted runner context for one tick of policy validation.

    The ``mode`` field here is the **authoritative** mode; the agent's
    :attr:`Decision.policy_mode` is intentionally ignored by
    :func:`safe_decision` because it is an LLM-supplied hint
    (TASK-121 §8).

    ``lease_token`` is the VPT lease identifier; ``None`` means the
    operator does not hold the device (§FR-02 fail-closed).

    ``focus_app`` is the foreground-window title (or a stable alias);
    ``None`` means no simulator focus has been acquired (§FR-02
    fail-closed when the simulator would otherwise be the target).

    ``clock_monotonic_ns`` is the policy caller's snapshot of
    ``time.monotonic_ns()``; we never read the clock ourselves so
    :func:`safe_decision` stays deterministic and side-effect free.

    ``calibration_hash`` is the source calibration identifier;
    it is **recorded on every accepted result** (carried by the caller
    into the report) but does not gate acceptance in this revision
    — future revisions may add a calibration-mismatch rejection.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["replay", "shadow", "simulator"]
    lease_token: Optional[str] = None
    focus_app: Optional[str] = None
    clock_monotonic_ns: int = Field(ge=0)
    calibration_hash: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------


def _reject(
    reason_code: PolicyResult.model_fields["reason_code"].annotation,
    human_reason: str,
) -> PolicyResult:
    """Build a uniform rejection :class:`PolicyResult`.

    Centralizes the rejection shape so every branch that produces a
    rejection sets the same three fields (and so a future refactor
    that adds another uniform field — e.g. ``policy_doc_url`` — can
    do it in one place).

    ``human_reason`` is guaranteed to be 1..300 chars by the spec; the
    callers below all use 1..200 chars to leave headroom.
    """
    return PolicyResult(
        allowed=False,
        reason_code=reason_code,
        human_reason=human_reason,
        effective_action=None,
    )


def _record_non_action(action: Action) -> PolicyResult:
    """Record a deliberate ``WAIT`` / ``ABSTAIN``.

    Both come through here so they get the same shape and the same
    ``reason_code``. ``effective_action`` carries the agent's own
    proposal so the runner can log "agent abstained because X" without
    a separate field.
    """
    return PolicyResult(
        allowed=False,
        reason_code="ACCEPTED",
        human_reason=(
            "Agent deliberately chose WAIT/ABSTAIN; recorded as a "
            "non-action without executor invocation."
        ),
        effective_action=action,
    )


# ---------------------------------------------------------------------------
# The validator.
# ---------------------------------------------------------------------------


def safe_decision(
    decision: Decision,
    observation_id: str,
    observation_acquired_at_ns: int,
    authority: Authority,
    *,
    max_observation_age_ns: int = 2_000_000_000,
) -> PolicyResult:
    """Decide whether ``decision`` is permitted under ``authority``.

    Parameters
    ----------
    decision:
        A Pydantic-validated :class:`Decision` (the agent's proposal).
    observation_id:
        The identifier of the observation the agent is supposed to act
        on. Must match ``decision.observation_id``.
    observation_acquired_at_ns:
        The monotonic-clock timestamp at which that observation was
        captured. Used with ``authority.clock_monotonic_ns`` to decide
        whether the observation is fresh enough (``<= max_observation_age_ns``).
    authority:
        The trusted runner context (mode, lease, focus, clock).
    max_observation_age_ns:
        The maximum allowed age of the observation, in nanoseconds.
        Default 2 seconds (2_000_000_000 ns) — long enough to cover a
        slow vision-LLM tick but short enough that the agent never
        acts on a frame older than one tactical cycle.

    Returns
    -------
    A :class:`PolicyResult`. The function never raises for inputs that
    already pass Pydantic validation.

    Notes
    -----
    Strictly deterministic and side-effect free. No clock reads, no
    logging, no I/O — the caller controls the clock and the report
    plumbing. The behaviour for any (Decision, observation_id, ns,
    Authority) tuple is a pure function of those four values plus
    ``max_observation_age_ns``.
    """
    # --- 1. Staleness gates (highest priority) --------------------------
    if decision.observation_id != observation_id:
        return _reject(
            "STALE_OBSERVATION",
            (
                f"Decision's observation_id {decision.observation_id!r} does "
                f"not match the current observation {observation_id!r}; "
                f"refusing to act on a stale frame."
            ),
        )

    age_ns = authority.clock_monotonic_ns - observation_acquired_at_ns
    # ``age_ns`` may be negative if a clock reset happened between the
    # capture and the policy call — treat negative as STALE rather than as
    # a crash; this is the only safe interpretation when two monotonic
    # clocks can't be compared.
    if age_ns < 0 or age_ns > max_observation_age_ns:
        return _reject(
            "STALE_OBSERVATION",
            (
                f"Observation is stale: age={age_ns} ns "
                f"(max={max_observation_age_ns} ns); refusing to act on a "
                f"frame older than the tactical-cycle TTL."
            ),
        )

    # --- 2. Recorded non-actions (ABSTAIN / WAIT) -----------------------
    if decision.action.type == "ABSTAIN":
        return _record_non_action(decision.action)
    if decision.action.type == "WAIT":
        return _record_non_action(decision.action)

    # --- 3. Mode gate ---------------------------------------------------
    if authority.mode in ("replay", "shadow"):
        return _reject(
            "WRONG_MODE",
            (
                f"Authority mode is {authority.mode!r}: no execution; the "
                f"recommendation is recorded only."
            ),
        )

    # ``authority.mode == "simulator"`` from here on.
    # --- 4. Lease gate --------------------------------------------------
    if authority.lease_token is None:
        return _reject(
            "MISSING_LEASE",
            (
                "Simulator mode requires a VPT lease_token but none was "
                "supplied; refusing to act without an operator lease."
            ),
        )

    # --- 5. Focus gate --------------------------------------------------
    if authority.focus_app is None:
        return _reject(
            "DISABLED_FOCUS",
            (
                "Simulator mode requires a focus_app but none was supplied; "
                "refusing to act without an acquired focus window."
            ),
        )

    # --- 6. Confidence gate --------------------------------------------
    if decision.confidence < 0.3:
        return _reject(
            "LOW_CONFIDENCE",
            (
                f"Decision confidence {decision.confidence:.2f} is below the "
                f"0.3 cutoff; refusing to act on an uncertain proposal."
            ),
        )

    # --- 7. Coordinate safety (MOVE / ATTACK_MOVE / RETREAT) ------------
    if decision.action.type in {"MOVE", "ATTACK_MOVE", "RETREAT"}:
        target = decision.action.target  # type: ignore[attr-defined]
        # Point already enforces [0.0, 1.0] and rejects NaN / ±inf; this is
        # the belt-and-braces check called out by the spec in case a
        # future refactor relaxes the Point validator.
        if not (0.0 <= target.x <= 1.0 and 0.0 <= target.y <= 1.0):
            return _reject(
                "UNSAFE_COORDINATES",
                (
                    f"Action {decision.action.type!r} target {target!r} "
                    f"falls outside the safe [0.0, 1.0] window; refusing to "
                    f"act on an out-of-bounds cursor."
                ),
            )

    # --- 8. Spell slot (CAST_SPELL) ------------------------------------
    if decision.action.type == "CAST_SPELL":
        if decision.action.spell not in {"Q", "W", "E", "R"}:
            return _reject(
                "UNRECOGNIZED_SPELL",
                (
                    f"CAST_SPELL uses slot {decision.action.spell!r} which "
                    f"is not in the Q/W/E/R bag; refusing to act on an "
                    f"unknown ability."
                ),
            )

    # --- Default: ACCEPTED ---------------------------------------------
    return PolicyResult(
        allowed=True,
        reason_code="ACCEPTED",
        human_reason=(
            f"Proposal permitted under mode={authority.mode!r}, "
            f"lease={'set' if authority.lease_token else 'unset'}, "
            f"focus={'set' if authority.focus_app else 'unset'}, "
            f"confidence={decision.confidence:.2f}."
        ),
        effective_action=decision.action,
    )


__all__ = [
    "POLICY_DOC_URL",
    "Authority",
    "safe_decision",
]
