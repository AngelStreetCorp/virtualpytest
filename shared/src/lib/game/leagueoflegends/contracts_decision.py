"""Typed contract for one League of Legends per-tick decision (TASK-121 §8).

This module pins the **action vocabulary** the agent emits each tick. A
``Decision`` is a *proposal* — the policy layer (:mod:`policies`) decides
whether the proposal becomes a permitted simulator action or a recorded
``WAIT`` / ``ABSTAIN``.

The discriminated union of action types (six variants) reflects what the
agent is allowed to propose at all — there is no general "free click", no
mouse-coordinate dump, no League-process helper. Per FR-06 the agent
returns **exactly one** typed abstract decision per tick; per FR-07 the
typed coordinates are normalized to ``[0.0, 1.0]`` and the policy rejects
non-finite values, stale observation IDs and unsafe targets upstream of
any execution.

Hard policy (TASK-121 §6 FR-06, FR-07, FR-13, §8, §13):

* The real League client is a human-played data source only.
* The schema MUST never import ``pyautogui`` or any League-process helper.
* ``extra='forbid'`` so the schema cannot be silently extended by an LLM.
* ``strict=True`` so type coercion (string→float, bool→int, …) is impossible.
* Coordinates are normalized floats in ``[0.0, 1.0]``; ``NaN`` and
  ``±inf`` are rejected at the validator layer.
* ``policy_mode`` is a *hint* the agent may attach to its proposal —
  it is **set by trusted runner configuration, NOT the LLM** (TASK-121
  §8, guarding principle). The policy validator in :mod:`policies`
  treats it as informational and overrides it with the runner's
  authoritative mode at validation time.

Schema: ``league-decision/v1`` (matches §8 illustrative TypeScript).
"""
from __future__ import annotations

import math
from typing import Annotated, List, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Stable enums / literals.
# ---------------------------------------------------------------------------

# The six abstract action variants. Each is a discriminated-union branch.
# ``WAIT`` and ``ABSTAIN`` are deliberately *non-executable* — the policy
# layer routes them through the ``ACCEPTED`` reason code but never invokes
# an executor.
ActionType = Literal["MOVE", "ATTACK_MOVE", "CAST_SPELL", "RETREAT", "WAIT", "ABSTAIN"]

# The four ability slots. ``Literal["Q","W","E","R"]`` enforces the bag at
# type-check time; ``policies.py`` re-checks for defense in depth.
SpellSlot = Literal["Q", "W", "E", "R"]

# Policy mode hint. The trusted runner overrides this before execution; the
# agent is allowed to attach a hint but the authority is the runner config.
PolicyModeHint = Literal["replay", "shadow", "simulator"]

# Reason codes the policy emits. ``ACCEPTED`` doubles as both the
# success code and the code for ``WAIT``/``ABSTAIN`` (which are recorded
# as deliberate non-actions, never executed).
ReasonCode = Literal[
    "ACCEPTED",
    "STALE_OBSERVATION",
    "UNSAFE_COORDINATES",
    "UNRECOGNIZED_SPELL",
    "DISABLED_FOCUS",
    "IMPOSSIBLE_TIMING",
    "UI_OVERLAY",
    "LOW_CONFIDENCE",
    "MISSING_LEASE",
    "WRONG_MODE",
]


# ---------------------------------------------------------------------------
# Geometry.
# ---------------------------------------------------------------------------


class Point(BaseModel):
    """A normalized point in ``[0.0, 1.0] x [0.0, 1.0]``.

    Coordinates are relative to the captured bitmap (the screen rectangle
    or the simulator window). The validator layer rejects:

    * any value outside ``[0.0, 1.0]`` (out-of-bounds cursor / target);
    * ``NaN``, ``+inf``, ``-inf`` (Pydantic ``Field`` accepts those on
      a plain float; the field validator below is the belt-and-braces
      guard called out in the spec).

    ``(0.0, 0.0)`` is top-left in the agent's screen-space; the executor
    multiplies by the source ``(W, H)`` to derive the literal pixel
    coordinate when the action is finally executed.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)

    @field_validator("x", "y")
    @classmethod
    def _finite_check(cls, v: float) -> float:
        # Pydantic ``Field(ge=…, le=…)`` only constrains range, it does NOT
        # reject ``NaN`` (NaN comparisons are always False, so NaN passes
        # ``ge`` and ``le``). It also doesn't reject ``inf`` because
        # ``inf <= 1.0`` is False — but ``-inf <= 1.0`` *is* true, so a
        # negative-infinity sneaks past ``le``. The explicit ``math.isfinite``
        # check is the single source of truth for "no NaN, no ±inf".
        if math.isnan(v):
            raise ValueError("coordinate must be a finite number (NaN rejected)")
        if math.isinf(v):
            raise ValueError("coordinate must be a finite number (±inf rejected)")
        return v


# A point that may be ``None`` (e.g. ``CAST_SPELL`` does not always need a
# target — a self-targeted heal or a point-blank ultimate lands on the
# champion itself). Kept as a plain ``Union`` annotation; Pydantic resolves
# it under ``strict=True``.
OptionalPoint = Union[Point, None]


# ---------------------------------------------------------------------------
# Action variants (the discriminated union).
# ---------------------------------------------------------------------------


class _MoveAction(BaseModel):
    """Plain move click (no attack)."""

    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["MOVE"]
    target: Point


class _AttackMoveAction(BaseModel):
    """Move + attack on the way (right-click attack-move in LoL terms)."""

    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["ATTACK_MOVE"]
    target: Point


class _CastSpellAction(BaseModel):
    """Cast one of Q/W/E/R at an optional normalized point.

    ``target`` is optional because a self-targeted spell (e.g. a self-heal
    that snaps to the caster) has no point target.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["CAST_SPELL"]
    spell: SpellSlot
    target: OptionalPoint = None


class _RetreatAction(BaseModel):
    """Step away from threat toward a safe point."""

    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["RETREAT"]
    target: Point


class _WaitAction(BaseModel):
    """Deliberate non-action: hold position, reobserve next tick.

    Recorded as ``ACCEPTED`` by the policy layer (never executed). The
    orchestrator may still request a fresh observation.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["WAIT"]


class _AbstainAction(BaseModel):
    """Refusal to act on this tick — operator/supervisor needs to intervene.

    ``reason`` is a 1..200-char free-text label an analyst can grep.
    Like ``WAIT``, the policy layer records it (``ACCEPTED``) without
    executing anything.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["ABSTAIN"]
    reason: str = Field(min_length=1, max_length=200)


# Discriminated-union of the six variants. Pydantic picks the right branch
# by reading the ``type`` field. Adding a new variant requires bumping the
# schema version — see :class:`Decision` below.
Action = Annotated[
    Union[
        _MoveAction,
        _AttackMoveAction,
        _CastSpellAction,
        _RetreatAction,
        _WaitAction,
        _AbstainAction,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# The decision envelope.
# ---------------------------------------------------------------------------


class Decision(BaseModel):
    """One proposal the agent emits per tick (TASK-121 FR-06).

    Schema: ``league-decision/v1``.

    ``schema_version`` is a single literal; future shapes MUST bump the
    version (e.g. ``league-decision/v2``) rather than silently extending
    fields — this is enforced by ``extra='forbid'`` and by giving every
    new variant its own ``Action`` branch.

    ``observation_id`` ties the decision to a captured frame so the policy
    layer can reject stale proposals against newer frames (TASK-121 §10).

    ``confidence`` is the agent's self-reported certainty for *this* tick;
    the policy treats ``confidence < 0.3`` as ``LOW_CONFIDENCE`` and
    refuses to execute.

    ``reason`` is a 1..300-char operator-readable explanation an analyst
    can grep in the run report.

    ``policy_mode`` is a *request hint* — the agent may attach a preferred
    mode, but the trusted runner overrides it. The policy validator in
    :mod:`policies` reads the runner's ``Authority.mode`` and ignores
    whatever the agent wrote here. This is deliberate (TASK-121 §8
    guarding principle): a future LLM must not be able to make itself
    execute against the real client by writing ``"policy_mode": "live"``
    (which is rejected here because it isn't a member of the Literal).
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["league-decision/v1"]
    observation_id: str = Field(min_length=1)
    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=300)
    policy_mode: PolicyModeHint


# ---------------------------------------------------------------------------
# Policy output shape.
# ---------------------------------------------------------------------------


class PolicyResult(BaseModel):
    """The authoritative answer from :func:`safe_decision`.

    ``allowed`` is the only signal the runner reads to decide whether to
    invoke an executor. ``reason_code`` is the machine-readable reason
    a proposal was rejected (or ``"ACCEPTED"`` if it was permitted /
    if the agent deliberately emitted ``WAIT`` / ``ABSTAIN``).

    ``effective_action`` is the action the runner should *actually*
    consider:

    * on a permitted proposal: ``decision.action`` (the same proposal);
    * on a rejected proposal: ``None``;
    * on ``WAIT`` or ``ABSTAIN``: the action itself (recorded as a
      deliberate non-action, never executed).

    ``human_reason`` is the analyst-side explanation, 1..300 chars.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    allowed: bool
    reason_code: ReasonCode
    human_reason: str = Field(min_length=1, max_length=300)
    effective_action: Action | None = None


__all__ = [
    "ActionType",
    "SpellSlot",
    "PolicyModeHint",
    "ReasonCode",
    "Point",
    "Action",
    "Decision",
    "PolicyResult",
]
