"""Tests for the League of Legends client-window schema (TASK-121).

Covers :mod:`shared.src.lib.game.leagueoflegends.contracts_client` (typed
schema) and :mod:`shared.src.lib.game.leagueoflegends.vision_client`
(detector stub). No real League client interaction; no ``pyautogui``.
"""
from __future__ import annotations

import sys
import time
import uuid
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from shared.src.lib.game.leagueoflegends.contracts_client import (
    ClientObservation,
)
from shared.src.lib.game.leagueoflegends.vision_client import ClientVision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_payload(**overrides: Any) -> dict:
    """Build a valid minimal payload (provenance only, classifier defaults)."""
    payload = {
        "schema_version": "league-client/v1",
        "observation_id": "obs-test-001",
        "captured_at_monotonic_ns": time.monotonic_ns(),
        "frame_hash": "deadbeef",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Schema tests (contracts_client.py)
# ---------------------------------------------------------------------------


def test_client_observation_valid_minimal() -> None:
    """An empty classifier payload with all "unknown"/None defaults is accepted."""
    obs = ClientObservation(**_minimal_payload())

    # Provenance round-trips.
    assert obs.schema_version == "league-client/v1"
    assert obs.observation_id == "obs-test-001"
    assert obs.captured_at_monotonic_ns >= 0
    assert obs.frame_hash == "deadbeef"

    # Classifier defaults reflect the "no information" reading.
    assert obs.active_window == "unknown"
    assert obs.logged_in == "unknown"
    assert obs.lol_ready is None
    assert obs.practice_tool_open is None
    assert obs.play_view_open is None
    assert obs.product_tiles_visible == []
    assert obs.window_title is None
    assert obs.confidence == 0.0
    assert obs.unknown_fields == []


def test_client_observation_riot_client_state() -> None:
    """The §11.1.1 step 2 reading: logged-in Riot Client with LoL + Valorant tiles visible."""
    obs = ClientObservation(
        **_minimal_payload(
            observation_id="obs-walkthrough-step-2",
            active_window="riot_client",
            logged_in="yes",
            product_tiles_visible=["league_of_legends", "valorant"],
            window_title="Riot Client",
            confidence=0.91,
            unknown_fields=[],
        )
    )

    assert obs.active_window == "riot_client"
    assert obs.logged_in == "yes"
    assert obs.product_tiles_visible == ["league_of_legends", "valorant"]
    assert obs.window_title == "Riot Client"
    assert obs.confidence == pytest.approx(0.91)
    assert obs.unknown_fields == []


def test_client_observation_lol_in_game_state() -> None:
    """The §11.1.1 post-step-6 reading: practice tool in game, lobby has launched."""
    obs = ClientObservation(
        **_minimal_payload(
            observation_id="obs-walkthrough-step-6-in-game",
            active_window="lol_in_game",
            logged_in="yes",
            lol_ready=True,
            practice_tool_open=True,
            play_view_open=False,
            confidence=0.88,
        )
    )

    assert obs.active_window == "lol_in_game"
    assert obs.logged_in == "yes"
    assert obs.lol_ready is True
    assert obs.practice_tool_open is True
    # play_view_open defaults to None unless set; here we set False to confirm
    # the bool slot accepts a real False (not just None).
    assert obs.play_view_open is False
    assert obs.confidence == pytest.approx(0.88)


def test_client_observation_rejects_unknown_active_window() -> None:
    """``active_window`` is a closed Literal — anything outside the enum is rejected."""
    with pytest.raises(ValidationError):
        ClientObservation(**_minimal_payload(active_window="discord"))


def test_client_observation_rejects_extra_field() -> None:
    """``extra='forbid'`` blocks unknown keys (TASK-121 §8 schema policy)."""
    with pytest.raises(ValidationError) as excinfo:
        ClientObservation(
            **_minimal_payload(
                not_a_field="boom",  # type: ignore[arg-type]
            )
        )
    # The error message names the offending key, so a future refactor that
    # silently swallows extras would fail this assertion too.
    assert "not_a_field" in str(excinfo.value)


def test_client_observation_rejects_logged_in_value() -> None:
    """``logged_in`` is restricted to ``yes``/``no``/``unknown``."""
    with pytest.raises(ValidationError):
        ClientObservation(**_minimal_payload(logged_in="maybe"))


def test_client_observation_rejects_confidence_out_of_range() -> None:
    """Confidence is bounded to [0.0, 1.0] inclusive."""
    # Below the lower bound.
    with pytest.raises(ValidationError):
        ClientObservation(**_minimal_payload(confidence=-0.01))

    # Above the upper bound.
    with pytest.raises(ValidationError):
        ClientObservation(**_minimal_payload(confidence=1.01))


# ---------------------------------------------------------------------------
# Detector stub tests (vision_client.py)
# ---------------------------------------------------------------------------


def test_client_vision_observe_none_returns_unknown() -> None:
    """``observe(None)`` returns a fully-unknown observation (no information)."""
    vision = ClientVision()
    obs = vision.observe(None)

    # Provenance is populated.
    assert obs.schema_version == "league-client/v1"
    assert obs.observation_id  # non-empty
    assert obs.captured_at_monotonic_ns >= 0
    assert obs.frame_hash  # non-empty placeholder

    # All classifier fields at their "unknown" / None / False / [] defaults.
    assert obs.active_window == "unknown"
    assert obs.logged_in == "unknown"
    assert obs.lol_ready is None
    assert obs.practice_tool_open is None
    assert obs.play_view_open is None
    assert obs.product_tiles_visible == []
    assert obs.window_title is None
    assert obs.confidence == 0.0

    # Every detector-derived field is listed as unknown.
    expected_unknown = {
        "active_window",
        "logged_in",
        "lol_ready",
        "practice_tool_open",
        "play_view_open",
        "product_tiles_visible",
        "window_title",
        "confidence",
    }
    assert set(obs.unknown_fields) == expected_unknown


def test_client_vision_observe_array_populates_metadata() -> None:
    """``observe(np.ndarray)`` populates ``observation_id`` and ``captured_at_monotonic_ns``."""
    vision = ClientVision()

    # Synthetic 100x100x3 uint8 frame (RGB / BGR — the stub doesn't care).
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    before_ns = time.monotonic_ns()
    obs = vision.observe(frame, window_title="Riot Client")
    after_ns = time.monotonic_ns()

    # observation_id is a fresh UUID4.
    parsed = uuid.UUID(obs.observation_id)
    assert parsed.version == 4

    # captured_at_monotonic_ns is monotonic and bracketed by our measurement.
    assert obs.captured_at_monotonic_ns >= before_ns
    assert obs.captured_at_monotonic_ns <= after_ns

    # The same invariants as the None case (stub is shape-agnostic).
    assert obs.active_window == "unknown"
    assert obs.lol_ready is None
    assert obs.confidence == 0.0
    assert "active_window" in obs.unknown_fields

    # window_title is captured verbatim.
    assert obs.window_title == "Riot Client"

    # And the dtype / ndim guards reject anything that is not a 3-D uint8
    # ndarray — the caller is responsible for sanitizing the capture pipe.
    with pytest.raises(TypeError):
        vision.observe("not-a-frame")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        vision.observe(np.zeros((10, 10), dtype=np.uint8))  # 2-D
    with pytest.raises(ValueError):
        vision.observe(np.zeros((10, 10, 3), dtype=np.float32))  # wrong dtype


def test_client_vision_never_imports_pyautogui() -> None:
    """Static guard (TASK-121 §6 FR-13).

    The client-window module MUST NOT import ``pyautogui``. We check this
    by snapshotting ``sys.modules`` before and after importing our modules
    and asserting no new ``pyautogui`` entry was added by our import graph.
    """
    # Snapshot the modules that are present *before* we touch our code.
    before = set(sys.modules)

    # Import our two modules. If either transitively imports pyautogui,
    # it will land in sys.modules here.
    import shared.src.lib.game.leagueoflegends.contracts_client as contracts_mod  # noqa: F401
    import shared.src.lib.game.leagueoflegends.vision_client as vision_mod  # noqa: F401

    after = set(sys.modules)
    new_modules = after - before

    # If pyautogui showed up as a new module, fail with a useful message.
    if "pyautogui" in new_modules:
        pytest.fail(
            f"Importing {contracts_mod.__name__} / {vision_mod.__name__} pulled in "
            f"pyautogui (forbidden by TASK-121 §6 FR-13). New modules: {sorted(new_modules)}"
        )

    # Defensive belt-and-braces: the modules themselves must not have a
    # 'pyautogui' attribute (would only happen if a wildcard import or
    # `import *` pulled it in).
    assert "pyautogui" not in contracts_mod.__dict__
    assert "pyautogui" not in vision_mod.__dict__