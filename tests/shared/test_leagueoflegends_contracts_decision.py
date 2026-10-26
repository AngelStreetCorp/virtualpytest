"""Tests for the League of Legends decision schema (TASK-121 §8).

Covers :mod:`shared.src.lib.game.leagueoflegends.contracts_decision` —
the typed vocabulary for one per-tick decision (six action variants)
plus the discriminator and ``policy_mode`` hint.

The real League client is a human-played data source only (TASK-121
§6 FR-13). This module never imports ``pyautogui`` or any League-process
helper and we assert that with the AST walk at the bottom.
"""
from __future__ import annotations

import ast
import inspect
import math
import re
from typing import Any

import pytest
from pydantic import ValidationError

from shared.src.lib.game.leagueoflegends import contracts_decision as contracts_mod
from shared.src.lib.game.leagueoflegends.contracts_decision import (
    Action,
    Decision,
    Point,
    PolicyResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _point(x: float, y: float) -> dict:
    """Trivial Point payload builder."""
    return {"x": x, "y": y}


def _move(target: dict | None = None) -> dict:
    """A minimal valid ``MOVE`` action payload."""
    return {"type": "MOVE", "target": target or _point(0.5, 0.5)}


def _minimal_decision_payload(**overrides: Any) -> dict:
    """A valid minimal :class:`Decision` envelope (one MOVE action)."""
    payload = {
        "schema_version": "league-decision/v1",
        "observation_id": "obs-decision-001",
        "action": _move(),
        "confidence": 0.7,
        "reason": "test envelope",
        "policy_mode": "simulator",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Point tests.
# ---------------------------------------------------------------------------


def test_point_valid() -> None:
    """``(0.5, 0.5)`` is the canonical mid-screen point — must be accepted."""
    p = Point(x=0.5, y=0.5)
    assert p.x == pytest.approx(0.5)
    assert p.y == pytest.approx(0.5)


def test_point_rejects_out_of_range() -> None:
    """Out-of-range ``x`` / ``y`` is rejected (cursor / target safety)."""
    # Slightly negative x.
    with pytest.raises(ValidationError):
        Point(**_point(-0.01, 0.5))  # type: ignore[arg-type]
    # Slightly above the upper bound on y.
    with pytest.raises(ValidationError):
        Point(**_point(0.5, 1.01))  # type: ignore[arg-type]
    # Well outside the unit interval still rejected.
    with pytest.raises(ValidationError):
        Point(**_point(1.5, -0.5))  # type: ignore[arg-type]


def test_point_rejects_nan_and_inf() -> None:
    """``NaN`` and ``±inf`` are rejected — Pydantic ``Field`` does not block them."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            Point(**{"x": bad, "y": 0.5})  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            Point(**{"x": 0.5, "y": bad})  # type: ignore[arg-type]

    # Sanity check — ``math.isfinite`` is what the validator uses.
    assert not math.isfinite(float("nan"))
    assert not math.isfinite(float("inf"))
    assert not math.isfinite(float("-inf"))


# ---------------------------------------------------------------------------
# Action tests.
# ---------------------------------------------------------------------------


def test_action_move_valid() -> None:
    """A ``MOVE`` action with a valid point round-trips through the envelope."""
    d = Decision(**_minimal_decision_payload(action=_move()))
    assert d.action.type == "MOVE"
    assert d.action.target.x == pytest.approx(0.5)
    assert d.action.target.y == pytest.approx(0.5)


def test_action_cast_spell_with_target() -> None:
    """``CAST_SPELL`` with a target point is accepted (skillshot spell)."""
    payload = _minimal_decision_payload(
        action={
            "type": "CAST_SPELL",
            "spell": "Q",
            "target": _point(0.25, 0.75),
        }
    )
    d = Decision(**payload)
    assert d.action.type == "CAST_SPELL"
    assert d.action.spell == "Q"
    assert d.action.target is not None
    assert d.action.target.x == pytest.approx(0.25)


def test_action_cast_spell_without_target() -> None:
    """``CAST_SPELL`` without a target is accepted (self-targeted spell)."""
    payload = _minimal_decision_payload(
        action={"type": "CAST_SPELL", "spell": "W", "target": None}
    )
    d = Decision(**payload)
    assert d.action.type == "CAST_SPELL"
    assert d.action.spell == "W"
    assert d.action.target is None


def test_action_abstain_requires_reason() -> None:
    """An empty ``ABSTAIN.reason`` is rejected by ``min_length=1``."""
    # Empty string is rejected.
    with pytest.raises(ValidationError):
        Decision(
            **_minimal_decision_payload(
                action={"type": "ABSTAIN", "reason": ""}
            )
        )

    # A 1-char reason passes.
    d = Decision(
        **_minimal_decision_payload(
            action={"type": "ABSTAIN", "reason": "?"}
        )
    )
    assert d.action.type == "ABSTAIN"
    assert d.action.reason == "?"

    # A reason over 200 chars is rejected.
    with pytest.raises(ValidationError):
        Decision(
            **_minimal_decision_payload(
                action={"type": "ABSTAIN", "reason": "x" * 201}
            )
        )


# ---------------------------------------------------------------------------
# Decision envelope tests.
# ---------------------------------------------------------------------------


def test_decision_rejects_unknown_policy_mode() -> None:
    """``policy_mode="live"`` is rejected (it is not a member of the Literal)."""
    with pytest.raises(ValidationError):
        Decision(
            **_minimal_decision_payload(policy_mode="live")  # type: ignore[arg-type]
        )

    # The three allowed hints still round-trip.
    for mode in ("replay", "shadow", "simulator"):
        d = Decision(**_minimal_decision_payload(policy_mode=mode))  # type: ignore[arg-type]
        assert d.policy_mode == mode


def test_decision_strict_types() -> None:
    """``strict=True`` blocks string→float and other coercions."""
    # Confidence as a string is rejected (no implicit float coercion).
    with pytest.raises(ValidationError):
        Decision(
            **_minimal_decision_payload(confidence="0.5")  # type: ignore[arg-type]
        )

    # Confidence as a bool is rejected.
    with pytest.raises(ValidationError):
        Decision(
            **_minimal_decision_payload(confidence=True)  # type: ignore[arg-type]
        )

    # An int disguised as a string on observation_id is rejected.
    with pytest.raises(ValidationError):
        Decision(
            **_minimal_decision_payload(observation_id=12345)  # type: ignore[arg-type]
        )


def test_decision_rejects_out_of_range_confidence() -> None:
    """``confidence`` must be in ``[0.0, 1.0]`` inclusive."""
    # Just below the lower bound.
    with pytest.raises(ValidationError):
        Decision(**_minimal_decision_payload(confidence=-0.01))
    # Just above the upper bound.
    with pytest.raises(ValidationError):
        Decision(**_minimal_decision_payload(confidence=1.01))

    # Edge values are accepted.
    assert Decision(**_minimal_decision_payload(confidence=0.0)).confidence == 0.0
    assert Decision(**_minimal_decision_payload(confidence=1.0)).confidence == 1.0


def test_decision_extras_forbid() -> None:
    """``extra='forbid'`` blocks any unknown key on the envelope."""
    with pytest.raises(ValidationError) as excinfo:
        Decision(
            **_minimal_decision_payload(
                not_a_real_field="boom",  # type: ignore[arg-type]
            )
        )
    assert "not_a_real_field" in str(excinfo.value)


def test_decision_reason_length_bounds() -> None:
    """``reason`` is 1..300 chars; longer is rejected."""
    # 0 chars → rejected.
    with pytest.raises(ValidationError):
        Decision(**_minimal_decision_payload(reason=""))
    # 300 chars → accepted (inclusive).
    d = Decision(**_minimal_decision_payload(reason="x" * 300))
    assert d.reason == "x" * 300
    # 301 chars → rejected.
    with pytest.raises(ValidationError):
        Decision(**_minimal_decision_payload(reason="x" * 301))


# ---------------------------------------------------------------------------
# PolicyResult tests.
# ---------------------------------------------------------------------------


def test_policy_result_extra_forbid() -> None:
    """``PolicyResult`` rejects unknown keys — the policy surface is sealed."""
    # Minimal valid result.
    pr = PolicyResult(
        allowed=False,
        reason_code="STALE_OBSERVATION",
        human_reason="stale",
    )
    assert not pr.allowed
    assert pr.reason_code == "STALE_OBSERVATION"
    assert pr.effective_action is None

    # An unknown key is rejected.
    with pytest.raises(ValidationError) as excinfo:
        PolicyResult(
            allowed=False,
            reason_code="STALE_OBSERVATION",
            human_reason="stale",
            something_else="boom",  # type: ignore[arg-type]
        )
    assert "something_else" in str(excinfo.value)

    # An unknown reason_code is rejected (Literal closed bag).
    with pytest.raises(ValidationError):
        PolicyResult(
            allowed=True,
            reason_code="NOT_A_REAL_CODE",  # type: ignore[arg-type]
            human_reason="ok",
        )


def test_decision_action_extra_forbid() -> None:
    """Each ``Action`` branch also rejects unknown keys (``extra='forbid'``)."""
    # Discriminated-union: each variant has ``extra='forbid'`` too.
    with pytest.raises(ValidationError):
        Decision(
            **_minimal_decision_payload(
                action={"type": "MOVE", "target": _point(0.5, 0.5), "extra": "boom"}  # type: ignore[arg-type]
            )
        )
    with pytest.raises(ValidationError):
        Decision(
            **_minimal_decision_payload(
                action={"type": "CAST_SPELL", "spell": "Q", "target": None, "extra": "boom"}  # type: ignore[arg-type]
            )
        )


# ---------------------------------------------------------------------------
# Hard-policy guard: no pyautogui / League-process helpers anywhere in
# the contracts module. Mirrors the lobby/client/vision tests.
# ---------------------------------------------------------------------------


def test_contracts_decision_never_imports_pyautogui() -> None:
    """Static guard (TASK-121 §6 FR-13).

    The contracts module MUST NOT import ``pyautogui`` or any League-
    process helper. The AST walk + name scan finds imports and from-
    imports; the plain-text scan catches sneaky docstring mentions.
    """
    # Make sure the module is loaded so inspect.getsource can read it.
    assert hasattr(contracts_mod, "Decision")

    forbidden_top_level = {"pyautogui"}
    forbidden_substrings = (
        "LeagueClientUx",  # Riot/LCU API client library
        "RiotClient",  # Riot client process / launcher
        "RiotClientServices",  # the launcher executable
        "League of Legends",  # upstream botting libs often self-describe this way
    )

    src = inspect.getsource(contracts_mod)
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in forbidden_top_level:
                    pytest.fail(
                        f"{contracts_mod.__name__} has 'import {alias.name}' — "
                        f"forbidden by TASK-121 §6 FR-13."
                    )
                for bad in forbidden_substrings:
                    if bad in alias.name:
                        pytest.fail(
                            f"{contracts_mod.__name__} imports '{alias.name}' "
                            f"which references a League/Riot process."
                        )
        elif isinstance(node, ast.ImportFrom):
            mod_name = node.module or ""
            root = mod_name.split(".")[0]
            if root in forbidden_top_level:
                pytest.fail(
                    f"{contracts_mod.__name__} has 'from {mod_name} import …' — "
                    f"forbidden by TASK-121 §6 FR-13."
                )
            for bad in forbidden_substrings:
                if bad in mod_name:
                    pytest.fail(
                        f"{contracts_mod.__name__} imports from '{mod_name}' "
                        f"which references a League/Riot process."
                    )

    # Plain-text check on the source with comments stripped.
    no_comments = re.sub(r"#.*", "", src)
    assert "import pyautogui" not in no_comments
    assert "from pyautogui" not in no_comments

    # And the module must not expose pyautogui as a leaked attribute.
    assert "pyautogui" not in contracts_mod.__dict__
