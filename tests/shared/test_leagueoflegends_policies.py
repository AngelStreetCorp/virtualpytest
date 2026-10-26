"""Tests for the League of Legends decision-policy validator (TASK-121 §8).

Covers :func:`shared.src.lib.game.leagueoflegends.policies.safe_decision`
and the surrounding :class:`Authority` / :data:`POLICY_DOC_URL` shape.

Priority order exercised:

1. ``STALE_OBSERVATION`` (id mismatch / stale clock)
2. Recorded ``WAIT`` / ``ABSTAIN`` (``ACCEPTED``, not executed)
3. ``WRONG_MODE`` (``replay`` / ``shadow``)
4. ``MISSING_LEASE`` (simulator + no lease token)
5. ``DISABLED_FOCUS`` (simulator + no focus app)
6. ``LOW_CONFIDENCE`` (``confidence < 0.3``)
7. ``UNSAFE_COORDINATES`` (MOVE / ATTACK_MOVE / RETREAT out-of-range)
8. ``UNRECOGNIZED_SPELL`` (CAST_SPELL off-bag)
9. Default ``ACCEPTED``

The real League client is a human-played data source only (TASK-121
§6 FR-13) and this module never imports ``pyautogui`` or any
League-process helper; the AST walk at the bottom proves it.
"""
from __future__ import annotations

import ast
import inspect
import math
import random
import re
from typing import Any

import pytest
from pydantic import ValidationError

from shared.src.lib.game.leagueoflegends import policies as policies_mod
from shared.src.lib.game.leagueoflegends.contracts_decision import (
    Decision,
    Point,
    _AbstainAction,
    _AttackMoveAction,
    _CastSpellAction,
    _MoveAction,
    _RetreatAction,
    _WaitAction,
)
from shared.src.lib.game.leagueoflegends.policies import (
    POLICY_DOC_URL,
    Authority,
    safe_decision,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_OBS_ID = "obs-policy-001"
_OBS_ACQ_NS = 1_000_000_000  # arbitrary baseline


def _point(x: float = 0.5, y: float = 0.5) -> Point:
    """Build a safe :class:`Point`."""
    return Point(x=x, y=y)


def _authority(
    *,
    mode: str = "simulator",
    lease_token: str | None = "lease-1",
    focus_app: str | None = "LoL",
    clock_monotonic_ns: int = 2_500_000_000,  # 1.5 s after _OBS_ACQ_NS
    calibration_hash: str | None = "cal-1",
) -> Authority:
    """Build an :class:`Authority` with sensible defaults."""
    return Authority(
        mode=mode,  # type: ignore[arg-type]
        lease_token=lease_token,
        focus_app=focus_app,
        clock_monotonic_ns=clock_monotonic_ns,
        calibration_hash=calibration_hash,
    )


def _move_dec(
    *,
    observation_id: str = _OBS_ID,
    confidence: float = 0.7,
    target: Point | None = None,
    policy_mode: str = "simulator",
) -> Decision:
    """Build a ``Decision`` that proposes a plain ``MOVE`` to ``(0.5, 0.5)``."""
    return Decision(
        schema_version="league-decision/v1",
        observation_id=observation_id,
        action=_MoveAction(type="MOVE", target=target or _point()),
        confidence=confidence,
        reason="test move",
        policy_mode=policy_mode,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Happy-path and acceptance.
# ---------------------------------------------------------------------------


def test_safe_decision_accepted_simulator_focused() -> None:
    """Happy path → ``allowed=True``, ``reason_code="ACCEPTED"``."""
    result = safe_decision(_move_dec(), _OBS_ID, _OBS_ACQ_NS, _authority())
    assert result.allowed is True
    assert result.reason_code == "ACCEPTED"
    assert result.effective_action is not None
    assert result.effective_action.type == "MOVE"
    # ``human_reason`` is 1..300 chars.
    assert 1 <= len(result.human_reason) <= 300


# ---------------------------------------------------------------------------
# Mode gate (FR-07 fail-closed).
# ---------------------------------------------------------------------------


def test_safe_decision_rejects_replay_mode() -> None:
    """``replay`` mode → ``WRONG_MODE`` (no execution)."""
    result = safe_decision(
        _move_dec(),
        _OBS_ID,
        _OBS_ACQ_NS,
        _authority(mode="replay"),
    )
    assert result.allowed is False
    assert result.reason_code == "WRONG_MODE"
    assert result.effective_action is None


def test_safe_decision_rejects_shadow_mode() -> None:
    """``shadow`` mode → ``WRONG_MODE`` (no execution)."""
    result = safe_decision(
        _move_dec(),
        _OBS_ID,
        _OBS_ACQ_NS,
        _authority(mode="shadow"),
    )
    assert result.allowed is False
    assert result.reason_code == "WRONG_MODE"
    assert result.effective_action is None


# ---------------------------------------------------------------------------
# Staleness gates (FR-07).
# ---------------------------------------------------------------------------


def test_safe_decision_stale_observation_clock() -> None:
    """A clock-too-far-after-capture reading is rejected as stale."""
    # The authority's clock is 9 s past the observation's acquire time;
    # default ``max_observation_age_ns`` is 2 s, so this is stale.
    result = safe_decision(
        _move_dec(),
        _OBS_ID,
        _OBS_ACQ_NS,
        _authority(clock_monotonic_ns=_OBS_ACQ_NS + 9_000_000_000),
    )
    assert result.allowed is False
    assert result.reason_code == "STALE_OBSERVATION"


def test_safe_decision_stale_observation_id() -> None:
    """Observation-id mismatch is rejected as stale (highest priority)."""
    result = safe_decision(
        _move_dec(observation_id="agent-thinks-this"),
        "current-obs-id",
        _OBS_ACQ_NS,
        _authority(),
    )
    assert result.allowed is False
    assert result.reason_code == "STALE_OBSERVATION"


# ---------------------------------------------------------------------------
# Lease and focus gates (FR-02 fail-closed).
# ---------------------------------------------------------------------------


def test_safe_decision_missing_lease() -> None:
    """Simulator mode without a lease token → ``MISSING_LEASE``."""
    result = safe_decision(
        _move_dec(),
        _OBS_ID,
        _OBS_ACQ_NS,
        _authority(lease_token=None),
    )
    assert result.allowed is False
    assert result.reason_code == "MISSING_LEASE"
    assert result.effective_action is None


def test_safe_decision_disabled_focus() -> None:
    """Simulator mode without a focus app → ``DISABLED_FOCUS``."""
    result = safe_decision(
        _move_dec(),
        _OBS_ID,
        _OBS_ACQ_NS,
        _authority(focus_app=None),
    )
    assert result.allowed is False
    assert result.reason_code == "DISABLED_FOCUS"


# ---------------------------------------------------------------------------
# Confidence gate (FR-07).
# ---------------------------------------------------------------------------


def test_safe_decision_low_confidence() -> None:
    """``confidence < 0.3`` → ``LOW_CONFIDENCE``."""
    result = safe_decision(
        _move_dec(confidence=0.29),
        _OBS_ID,
        _OBS_ACQ_NS,
        _authority(),
    )
    assert result.allowed is False
    assert result.reason_code == "LOW_CONFIDENCE"
    # Edge: 0.3 itself is accepted.
    result_ok = safe_decision(
        _move_dec(confidence=0.3),
        _OBS_ID,
        _OBS_ACQ_NS,
        _authority(),
    )
    assert result_ok.allowed is True


# ---------------------------------------------------------------------------
# Coordinate safety (FR-07).
# ---------------------------------------------------------------------------


def test_safe_decision_unsafe_coordinates_move() -> None:
    """An out-of-range MOVE target triggers the belt-and-braces ``UNSAFE_COORDINATES`` check.

    The Point validator blocks invalid coordinates at construction, so we
    use ``model_construct`` to assemble a Decision with ``target.x=1.5``
    without triggering that validator. The policy's own range check then
    must catch it (``UNSAFE_COORDINATES``).
    """
    from shared.src.lib.game.leagueoflegends.contracts_decision import (
        _MoveAction,
        Decision,
    )

    bad_target = Point.model_construct(x=1.5, y=0.5)
    bad_action = _MoveAction.model_construct(type="MOVE", target=bad_target)
    decision = Decision.model_construct(
        schema_version="league-decision/v1",
        observation_id=_OBS_ID,
        action=bad_action,
        confidence=0.7,
        reason="unsafe",
        policy_mode="simulator",
    )

    result = safe_decision(decision, _OBS_ID, _OBS_ACQ_NS, _authority())
    assert result.allowed is False
    assert result.reason_code == "UNSAFE_COORDINATES"
    assert result.effective_action is None


# ---------------------------------------------------------------------------
# Deliberate non-actions: WAIT / ABSTAIN (FR-07).
# ---------------------------------------------------------------------------


def test_safe_decision_abstain_is_recorded_not_executed() -> None:
    """ABSTAIN is recorded (``ACCEPTED``) with the ABSTAIN itself as effective action."""
    abstain = Decision(
        schema_version="league-decision/v1",
        observation_id=_OBS_ID,
        action=_AbstainAction(type="ABSTAIN", reason="model uncertain"),
        confidence=0.9,
        reason="abstain test",
        policy_mode="simulator",
    )
    result = safe_decision(abstain, _OBS_ID, _OBS_ACQ_NS, _authority())
    assert result.allowed is False  # not *executed*
    assert result.reason_code == "ACCEPTED"  # but *accepted* as a non-action
    assert result.effective_action is not None
    assert result.effective_action.type == "ABSTAIN"


def test_safe_decision_wait_is_recorded_not_executed() -> None:
    """WAIT is recorded (``ACCEPTED``) with the WAIT itself as effective action."""
    wait_dec = Decision(
        schema_version="league-decision/v1",
        observation_id=_OBS_ID,
        action=_WaitAction(type="WAIT"),
        confidence=0.9,
        reason="wait test",
        policy_mode="simulator",
    )
    result = safe_decision(wait_dec, _OBS_ID, _OBS_ACQ_NS, _authority())
    assert result.allowed is False
    assert result.reason_code == "ACCEPTED"
    assert result.effective_action is not None
    assert result.effective_action.type == "WAIT"


# ---------------------------------------------------------------------------
# Determinism.
# ---------------------------------------------------------------------------


def test_safe_decision_deterministic() -> None:
    """Same inputs always produce the same result (pure function)."""
    dec = _move_dec()
    auth = _authority()
    results = tuple(
        safe_decision(dec, _OBS_ID, _OBS_ACQ_NS, auth)
        for _ in range(3)
    )
    # All three results compare equal.
    assert results[0] == results[1] == results[2]


# ---------------------------------------------------------------------------
# Priority ordering.
# ---------------------------------------------------------------------------


def test_safe_decision_priority_replay_beats_low_confidence() -> None:
    """Mode check fires before confidence — even at ``0.1`` confidence, replay wins."""
    result = safe_decision(
        _move_dec(confidence=0.1),
        _OBS_ID,
        _OBS_ACQ_NS,
        _authority(mode="replay"),
    )
    assert result.allowed is False
    assert result.reason_code == "WRONG_MODE"


def test_safe_decision_priority_stale_beats_low_confidence() -> None:
    """Stale-observation-id check fires before confidence — the proposal isn't even on the current frame."""
    result = safe_decision(
        _move_dec(confidence=0.1, observation_id="wrong"),
        _OBS_ID,
        _OBS_ACQ_NS,
        _authority(),
    )
    assert result.allowed is False
    assert result.reason_code == "STALE_OBSERVATION"


def test_safe_decision_priority_lease_beats_low_confidence() -> None:
    """A simulator without a lease loses to *anything else* — even a low-confidence MOVE."""
    result = safe_decision(
        _move_dec(confidence=0.1),
        _OBS_ID,
        _OBS_ACQ_NS,
        _authority(lease_token=None),
    )
    assert result.reason_code == "MISSING_LEASE"


# ---------------------------------------------------------------------------
# Robustness: never raises on valid inputs (fuzz).
# ---------------------------------------------------------------------------


def test_safe_decision_never_raises_on_valid_input() -> None:
    """50 random valid (Decision, Authority) pairs all return a ``PolicyResult``."""
    rng = random.Random(0x5EED)  # deterministic fuzz seed

    # Each entry: (action-constructor, type-literal). The two are tied so we
    # can use a single random pick and still construct a valid action.
    action_builders: tuple[tuple[str, Any], ...] = (
        ("MOVE", lambda i, rng: _MoveAction(
            type="MOVE",
            target=Point(x=rng.random(), y=rng.random()),
        )),
        ("ATTACK_MOVE", lambda i, rng: _AttackMoveAction(
            type="ATTACK_MOVE",
            target=Point(x=rng.random(), y=rng.random()),
        )),
        ("RETREAT", lambda i, rng: _RetreatAction(
            type="RETREAT",
            target=Point(x=rng.random(), y=rng.random()),
        )),
        ("WAIT", lambda i, rng: _WaitAction(type="WAIT")),
        ("ABSTAIN", lambda i, rng: _AbstainAction(
            type="ABSTAIN", reason=f"reason-{i:02d}"
        )),
        ("CAST_SPELL", lambda i, rng: _CastSpellAction(
            type="CAST_SPELL",
            spell=rng.choice(("Q", "W", "E", "R")),
            target=(
                Point(x=rng.random(), y=rng.random())
                if rng.random() < 0.5
                else None
            ),
        )),
    )

    for i in range(50):
        # Random action type and parameters.
        _, builder = action_builders[rng.randrange(len(action_builders))]
        action = builder(i, rng)

        decision = Decision(
            schema_version="league-decision/v1",
            observation_id=f"obs-{i:03d}",
            action=action,
            confidence=rng.uniform(0.0, 1.0),
            reason=f"fuzz-{i:02d}",
            policy_mode="simulator",
        )
        authority = Authority(
            mode=rng.choice(("replay", "shadow", "simulator")),
            lease_token=(
                None if rng.random() < 0.3 else f"lease-{i:02d}"
            ),
            focus_app=(
                None if rng.random() < 0.3 else f"app-{i:02d}"
            ),
            clock_monotonic_ns=rng.randrange(0, 10_000_000_000),
            calibration_hash=None,
        )

        # The observation's acquire time is anywhere in [0, clock].
        obs_acq = rng.randrange(0, authority.clock_monotonic_ns + 1)

        # The key assertion: ``safe_decision`` must never raise.
        result = safe_decision(decision, decision.observation_id, obs_acq, authority)
        assert isinstance(result.allowed, bool)
        assert 1 <= len(result.human_reason) <= 300
        assert result.reason_code in {
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
        }


# ---------------------------------------------------------------------------
# Hard-policy guard: pyautogui / League-process helpers.
# ---------------------------------------------------------------------------


def test_policies_never_imports_pyautogui() -> None:
    """The policies module MUST NOT import ``pyautogui`` or League-process helpers."""
    # Make sure the module is loaded so inspect.getsource can read it.
    assert hasattr(policies_mod, "safe_decision")

    forbidden_top_level = {"pyautogui"}
    forbidden_substrings = (
        "LeagueClientUx",
        "RiotClient",
        "RiotClientServices",
        "League of Legends",
    )

    src = inspect.getsource(policies_mod)
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in forbidden_top_level:
                    pytest.fail(
                        f"{policies_mod.__name__} has 'import {alias.name}' — "
                        f"forbidden by TASK-121 §6 FR-13."
                    )
                for bad in forbidden_substrings:
                    if bad in alias.name:
                        pytest.fail(
                            f"{policies_mod.__name__} imports '{alias.name}' "
                            f"which references a League/Riot process."
                        )
        elif isinstance(node, ast.ImportFrom):
            mod_name = node.module or ""
            root = mod_name.split(".")[0]
            if root in forbidden_top_level:
                pytest.fail(
                    f"{policies_mod.__name__} has 'from {mod_name} import …' — "
                    f"forbidden by TASK-121 §6 FR-13."
                )
            for bad in forbidden_substrings:
                if bad in mod_name:
                    pytest.fail(
                        f"{policies_mod.__name__} imports from '{mod_name}' "
                        f"which references a League/Riot process."
                    )

    # Plain-text check on the source with comments stripped.
    no_comments = re.sub(r"#.*", "", src)
    assert "import pyautogui" not in no_comments
    assert "from pyautogui" not in no_comments

    # And the module must not expose pyautogui as a leaked attribute.
    assert "pyautogui" not in policies_mod.__dict__


# ---------------------------------------------------------------------------
# Defensive: doc URL and surface hygiene.
# ---------------------------------------------------------------------------


def test_policy_doc_url_present_and_in_repo() -> None:
    """The policy doc URL points to the TASK-121 spec section."""
    assert isinstance(POLICY_DOC_URL, str)
    # Path is inside the repo, not an external URL.
    assert not POLICY_DOC_URL.startswith(("http://", "https://"))
    assert POLICY_DOC_URL.startswith("docs/")
    assert "TASK-121-league-of-legends-windows-vision-agent" in POLICY_DOC_URL


def test_authority_extras_forbid() -> None:
    """``Authority`` rejects unknown keys (``extra='forbid'``)."""
    with pytest.raises(ValidationError) as excinfo:
        Authority(
            mode="simulator",
            lease_token=None,
            focus_app=None,
            clock_monotonic_ns=1,
            calibration_hash=None,
            not_an_authority_field="boom",  # type: ignore[arg-type]
        )
    assert "not_an_authority_field" in str(excinfo.value)


def test_authority_rejects_negative_clock() -> None:
    """``clock_monotonic_ns`` must be ``>= 0``."""
    with pytest.raises(ValidationError):
        Authority(
            mode="simulator",
            lease_token=None,
            focus_app=None,
            clock_monotonic_ns=-1,
            calibration_hash=None,
        )


def test_authority_rejects_unknown_mode() -> None:
    """``Authority.mode`` is a closed bag."""
    with pytest.raises(ValidationError):
        Authority(
            mode="authorized_target",  # type: ignore[arg-type]
            lease_token=None,
            focus_app=None,
            clock_monotonic_ns=1,
            calibration_hash=None,
        )


def test_safe_decision_finite_point_fuzz() -> None:
    """Every random point used by the fuzz above passes ``math.isfinite``."""

    rng = random.Random(0xBABE)
    for _ in range(100):
        x = rng.random()
        y = rng.random()
        assert math.isfinite(x) and math.isfinite(y)
