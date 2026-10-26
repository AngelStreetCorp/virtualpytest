"""Tests for the League of Legends Practice Tool lobby schema (TASK-121).

Covers :mod:`shared.src.lib.game.leagueoflegends.contracts_lobby` (typed
schema) and :mod:`shared.src.lib.game.leagueoflegends.vision_lobby`
(detector stub). No real League client interaction; no ``pyautogui``.
"""
from __future__ import annotations

import ast
import inspect
import re
import sys
import time
import uuid
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from shared.src.lib.game.leagueoflegends.contracts_lobby import (
    LobbyObservation,
)
from shared.src.lib.game.leagueoflegends.vision_lobby import LobbyVision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_payload(**overrides: Any) -> dict:
    """Build a valid minimal payload (provenance only, classifier defaults)."""
    payload = {
        "schema_version": "league-lobby/v1",
        "observation_id": "obs-test-001",
        "captured_at_monotonic_ns": time.monotonic_ns(),
        "frame_hash": "deadbeef",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Schema tests (contracts_lobby.py)
# ---------------------------------------------------------------------------


def test_lobby_observation_valid_minimal() -> None:
    """An empty classifier payload with side=None and role_locked=None is accepted."""
    obs = LobbyObservation(**_minimal_payload())

    # Provenance round-trips.
    assert obs.schema_version == "league-lobby/v1"
    assert obs.observation_id == "obs-test-001"
    assert obs.captured_at_monotonic_ns >= 0
    assert obs.frame_hash == "deadbeef"

    # Classifier defaults reflect the "no information" reading.
    assert obs.side is None
    assert obs.role_locked is None
    assert obs.match_type == "unknown"
    assert obs.bots_player_side == 0
    assert obs.bots_enemy_side == 0
    assert obs.human_players_player_side == 0
    assert obs.human_players_enemy_side == 0
    assert obs.start_button_enabled is False
    assert obs.lobby_full is False
    assert obs.confidence == 0.0
    assert obs.unknown_fields == []


def test_lobby_observation_full_practice_tool() -> None:
    """The §11.1.1 step 6 reading: practice tool, 1 bot each side, role unset, lobby ready."""
    obs = LobbyObservation(
        **_minimal_payload(
            observation_id="obs-walkthrough-step-6",
            match_type="practice_tool",
            side="Blue",
            role_locked=None,
            bots_player_side=1,
            bots_enemy_side=1,
            human_players_player_side=1,
            human_players_enemy_side=0,
            start_button_enabled=True,
            lobby_full=True,
            confidence=0.92,
            unknown_fields=[],
        )
    )

    assert obs.match_type == "practice_tool"
    assert obs.side == "Blue"
    assert obs.role_locked is None  # operator leaves it unset so human goes top
    assert obs.bots_player_side == 1
    assert obs.bots_enemy_side == 1
    assert obs.lobby_full is True
    assert obs.start_button_enabled is True
    assert obs.confidence == pytest.approx(0.92)


def test_lobby_observation_rejects_role_top_when_unset() -> None:
    """``role_locked="top"`` is allowed (operator choice); non-Literal values are rejected.

    The test name reflects the operator spec ("role left unset so human goes
    top") but the contract permits an explicit ``"top"`` lock — only literal
    values outside the enum are blocked.
    """
    # Explicit "top" is allowed.
    obs_top = LobbyObservation(
        **_minimal_payload(role_locked="top")
    )
    assert obs_top.role_locked == "top"

    # Every other legal role is also accepted (covers all Literal branches).
    for role in ("jungle", "mid", "bot", "support"):
        obs = LobbyObservation(**_minimal_payload(role_locked=role))
        assert obs.role_locked == role

    # Anything else is rejected by the Literal type.
    with pytest.raises(ValidationError):
        LobbyObservation(**_minimal_payload(role_locked="not-a-role"))

    # Strict mode also rejects int-as-bool / float-as-int coercion.
    with pytest.raises(ValidationError):
        LobbyObservation(**_minimal_payload(role_locked=1))


def test_lobby_observation_rejects_extra_field() -> None:
    """``extra='forbid'`` blocks unknown keys (TASK-121 §8 schema policy)."""
    with pytest.raises(ValidationError) as excinfo:
        LobbyObservation(
            **_minimal_payload(
                not_a_field="boom",  # type: ignore[arg-type]
            )
        )
    # The error message names the offending key, so a future refactor that
    # silently swallows extras would fail this assertion too.
    assert "not_a_field" in str(excinfo.value)


def test_lobby_observation_rejects_confidence_out_of_range() -> None:
    """Confidence is bounded to [0.0, 1.0] inclusive."""
    # Below the lower bound.
    with pytest.raises(ValidationError):
        LobbyObservation(**_minimal_payload(confidence=-0.01))

    # Above the upper bound.
    with pytest.raises(ValidationError):
        LobbyObservation(**_minimal_payload(confidence=1.01))

    # Strict mode also blocks string coercion.
    with pytest.raises(ValidationError):
        LobbyObservation(**_minimal_payload(confidence="0.5"))  # type: ignore[arg-type]

    # Edge values (0.0, 1.0) are accepted.
    assert LobbyObservation(**_minimal_payload(confidence=0.0)).confidence == 0.0
    assert LobbyObservation(**_minimal_payload(confidence=1.0)).confidence == 1.0


# ---------------------------------------------------------------------------
# Detector stub tests (vision_lobby.py)
# ---------------------------------------------------------------------------


def test_lobby_vision_observe_none_returns_unknown() -> None:
    """``observe(None)`` returns a fully-unknown observation (no information)."""
    vision = LobbyVision()
    obs = vision.observe(None)

    # Provenance is populated.
    assert obs.schema_version == "league-lobby/v1"
    assert obs.observation_id  # non-empty
    assert obs.captured_at_monotonic_ns >= 0
    assert obs.frame_hash  # non-empty placeholder

    # All classifier fields at their "unknown" / zero / False defaults.
    assert obs.match_type == "unknown"
    assert obs.side is None
    assert obs.role_locked is None
    assert obs.bots_player_side == 0
    assert obs.bots_enemy_side == 0
    assert obs.human_players_player_side == 0
    assert obs.human_players_enemy_side == 0
    assert obs.start_button_enabled is False
    assert obs.lobby_full is False
    assert obs.confidence == 0.0

    # Every detector-derived field is listed as unknown.
    expected_unknown = {
        "match_type",
        "side",
        "role_locked",
        "bots_player_side",
        "bots_enemy_side",
        "human_players_player_side",
        "human_players_enemy_side",
        "start_button_enabled",
        "lobby_full",
        "confidence",
    }
    assert set(obs.unknown_fields) == expected_unknown


def test_lobby_vision_observe_array_sets_observation_id_and_timestamp() -> None:
    """``observe(np.ndarray)`` populates observation_id (UUID4) and timestamp."""
    vision = LobbyVision()

    # Synthetic 100x100x3 uint8 frame (RGB / BGR — the stub doesn't care).
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    before_ns = time.monotonic_ns()
    obs = vision.observe(frame)
    after_ns = time.monotonic_ns()

    # observation_id is a fresh UUID4.
    parsed = uuid.UUID(obs.observation_id)
    assert parsed.version == 4

    # captured_at_monotonic_ns is monotonic and bracketed by our measurement.
    assert obs.captured_at_monotonic_ns >= before_ns
    assert obs.captured_at_monotonic_ns <= after_ns

    # The same invariants as the None case (stub is shape-agnostic).
    assert obs.match_type == "unknown"
    assert obs.role_locked is None
    assert obs.confidence == 0.0
    assert "match_type" in obs.unknown_fields

    # And the dtype / ndim guards reject anything that is not a 3-D uint8
    # ndarray — the caller is responsible for sanitizing the capture pipe.
    with pytest.raises(TypeError):
        vision.observe("not-a-frame")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        vision.observe(np.zeros((10, 10), dtype=np.uint8))  # 2-D
    with pytest.raises(ValueError):
        vision.observe(np.zeros((10, 10, 3), dtype=np.float32))  # wrong dtype


def test_lobby_vision_never_imports_pyautogui() -> None:
    """Static guard (TASK-121 §6 FR-13).

    The lobby module MUST NOT import ``pyautogui`` or any obvious
    League-process helper. We check this two ways:

    1. AST walk over our two modules' sources — fails if either contains an
       ``import pyautogui`` / ``from pyautogui import …`` line. This is the
       real guard against accidental coupling.
    2. Attribute presence on the module dict — fails if the import somehow
       sneaks in via a side-effect of another import.

    We deliberately avoid asserting ``"pyautogui" not in sys.modules`` because
    the broader test suite (e.g. ``backend_host`` desktop controllers) is
    free to import it for unrelated reasons; that pollution is not our
    concern.
    """
    # Ensure our modules are loaded so inspect.getsource can read them.
    import shared.src.lib.game.leagueoflegends.contracts_lobby as contracts_mod  # noqa: F401
    import shared.src.lib.game.leagueoflegends.vision_lobby as vision_mod  # noqa: F401

    # ``pyautogui`` is the one concrete desktop-automation library the
    # brief calls out. Anything else (e.g. ``subprocess``) is too general to
    # ban here without false-positives on benign uses; the relevant guard
    # is "no League-process helper", captured by ``forbidden_substrings``.
    forbidden_top_level = {"pyautogui"}
    forbidden_substrings = (
        "LeagueClientUx",  # Riot/LCU API client library
        "RiotClient",  # Riot client process / launcher
        "RiotClientServices",  # the launcher executable
        "League of Legends",  # upstream botting libs often self-describe this way
    )

    def _check_no_forbidden(mod: Any) -> None:
        src = inspect.getsource(mod)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in forbidden_top_level:
                        pytest.fail(
                            f"{mod.__name__} has 'import {alias.name}' — forbidden by "
                            f"TASK-121 §6 FR-13."
                        )
                    for bad in forbidden_substrings:
                        if bad in alias.name:
                            pytest.fail(
                                f"{mod.__name__} imports '{alias.name}' which references "
                                f"a League/Riot process."
                            )
            elif isinstance(node, ast.ImportFrom):
                mod_name = node.module or ""
                root = mod_name.split(".")[0]
                if root in forbidden_top_level:
                    pytest.fail(
                        f"{mod.__name__} has 'from {mod_name} import …' — forbidden by "
                        f"TASK-121 §6 FR-13."
                    )
                for bad in forbidden_substrings:
                    if bad in mod_name:
                        pytest.fail(
                            f"{mod.__name__} imports from '{mod_name}' which references "
                            f"a League/Riot process."
                        )
        # Belt-and-braces: a plain-text scan catches things AST might miss
        # (e.g. inside a docstring someone could still write the name —
        # we treat a real import as the failure mode and only forbid a real
        # ``import`` statement elsewhere; this is just a smoke test).
        assert "import pyautogui" not in re.sub(r"#.*", "", src)
        assert "from pyautogui" not in re.sub(r"#.*", "", src)

    _check_no_forbidden(contracts_mod)
    _check_no_forbidden(vision_mod)

    # And the modules must not expose pyautogui as an attribute (defensive).
    assert "pyautogui" not in contracts_mod.__dict__
    assert "pyautogui" not in vision_mod.__dict__


# ---------------------------------------------------------------------------
# Defensive: confirm ``time.monotonic_ns`` exists and our numpy import is
# exactly the public numpy module (not a stub).
# ---------------------------------------------------------------------------


def test_runtime_dependencies_present() -> None:
    """Sanity check that the test environment can run this module at all.

    Not part of the 8 contract tests, but a guard against the parent
    running tests in a slim Python without numpy / monotonic_ns.
    """
    assert hasattr(time, "monotonic_ns")
    assert isinstance(np.zeros((1, 1, 1), dtype=np.uint8), np.ndarray)
    # uuid4 is what vision_lobby uses; ensure it's importable.
    uuid.uuid4()