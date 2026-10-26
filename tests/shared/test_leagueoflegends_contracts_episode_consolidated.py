"""Tests locking the consolidation of ``SimulatorTargetKind`` into a single canonical home.

Background: TASK-121 wave 2 defined the literal in BOTH
``shared.src.lib.game.leagueoflegends.contracts_episode`` and
``shared.src.lib.game.leagueoflegends.contracts_simulator``. This wave collapses
the duplicate: ``contracts_simulator`` stays the canonical home and
``contracts_episode`` re-exports it. The literal members stay identical — the
goal is a no-op consolidation that downstream callers cannot feel.

This file pins:

* **Object identity** of ``SimulatorTargetKind`` across the two modules
  (``A is B``, not just ``A == B``),
* the consolidation is a no-op for :class:`WalkthroughEpisode` validation —
  ``real-league`` is still rejected, the three allowed kinds still work,
* ``contracts_episode`` is still importable and ``WalkthroughEpisode`` is
  still constructible with all three valid ``simulator_target_kind`` values,
* the consolidation test file itself doesn't sneak in ``pyautogui`` or any
  League/Riot process helper (TASK-121 §6 FR-13, §13).

No real League client interaction; no ``pyautogui``; no League process names.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from shared.src.lib.game.leagueoflegends.contracts_episode import WalkthroughEpisode
from shared.src.lib.game.leagueoflegends.contracts_simulator import (
    SimulatorTargetKind as CanonicalSimulatorTargetKind,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_episode(**overrides):
    """Build a valid minimal :class:`WalkthroughEpisode` payload."""
    payload = {
        "schema_version": "league-episode/v1",
        "episode_id": "walkthrough_20261017_01",
        "operator": "op-anon-001",
        "host_fingerprint": "vpt-win-host-A",
        "started_at_utc": datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc),
        "frames": [],
        "simulator_target_kind": "community-sim",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Object-identity consolidation lock
# ---------------------------------------------------------------------------


def test_simulator_target_kind_is_the_same_object_in_both_modules() -> None:
    """``SimulatorTargetKind`` is one literal, exported by both modules (object identity).

    After the consolidation the two ``from … import SimulatorTargetKind`` lines
    must resolve to the **same** object — not to two equal-but-distinct
    Literals. Identity matters because Pydantic validates Literal values via
    the underlying generic-alias object; two equal Literals could diverge on
    a future model bump and silently break the FR-15 ``real-league`` gate.
    """
    from shared.src.lib.game.leagueoflegends.contracts_episode import (
        SimulatorTargetKind as EpisodeSymbol,
    )
    from shared.src.lib.game.leagueoflegends.contracts_simulator import (
        SimulatorTargetKind as SimulatorSymbol,
    )

    # Object identity, not equality — this is the whole point of the
    # consolidation (single source of truth).
    assert EpisodeSymbol is SimulatorSymbol
    # And, belt-and-braces, the canonical symbol we imported at module
    # top is still the same object after re-importing it from the episode
    # module.
    assert EpisodeSymbol is CanonicalSimulatorTargetKind


# ---------------------------------------------------------------------------
# Per-value validation pins
# ---------------------------------------------------------------------------


def test_walkthrough_episode_simulator_target_kind_rejects_real_league() -> None:
    """After consolidation the canonical Literal still rejects ``real-league``.

    The episode module no longer owns the literal — it imports it from
    ``contracts_simulator`` — but the Literal is the same one, so
    ``WalkthroughEpisode(..., simulator_target_kind="real-league", ...)``
    is still rejected by Pydantic (FR-15 defense in depth).
    """
    with pytest.raises(ValidationError):
        WalkthroughEpisode(
            **_minimal_episode(simulator_target_kind="real-league")
        )


def test_walkthrough_episode_simulator_target_kind_community_sim_accepted() -> None:
    """``simulator_target_kind="community-sim"`` is accepted (§11.1.3 first family)."""
    ep = WalkthroughEpisode(**_minimal_episode(simulator_target_kind="community-sim"))
    assert ep.simulator_target_kind == "community-sim"


def test_walkthrough_episode_simulator_target_kind_custom_moba_accepted() -> None:
    """``simulator_target_kind="custom-moba"`` is accepted (§11.1.3 second family)."""
    ep = WalkthroughEpisode(**_minimal_episode(simulator_target_kind="custom-moba"))
    assert ep.simulator_target_kind == "custom-moba"


def test_walkthrough_episode_simulator_target_kind_stand_in_game_accepted() -> None:
    """``simulator_target_kind="stand-in-game"`` is accepted (§11.1.3 third family)."""
    ep = WalkthroughEpisode(**_minimal_episode(simulator_target_kind="stand-in-game"))
    assert ep.simulator_target_kind == "stand-in-game"


# ---------------------------------------------------------------------------
# Module-level no-op guarantee
# ---------------------------------------------------------------------------


def test_consolidation_does_not_break_existing_episode_module() -> None:
    """The episode module imports cleanly and ``WalkthroughEpisode`` still constructs.

    After the consolidation, ``import contracts_episode`` must not break and
    every legal ``simulator_target_kind`` value must still construct a valid
    ``WalkthroughEpisode``. This is the no-op guarantee for downstream code
    (labelers, recorders, runners) that imports the episode module.
    """
    # Import-time smoke test — a circular import or a missing symbol would
    # raise here.
    import shared.src.lib.game.leagueoflegends.contracts_episode as ep_mod

    assert ep_mod.WalkthroughEpisode is WalkthroughEpisode
    assert ep_mod.SimulatorTargetKind is CanonicalSimulatorTargetKind

    # All three allowed kinds construct a valid episode.
    for kind in ("community-sim", "custom-moba", "stand-in-game"):
        ep = WalkthroughEpisode(**_minimal_episode(simulator_target_kind=kind))
        assert ep.simulator_target_kind == kind


# ---------------------------------------------------------------------------
# Self-hygiene: the consolidation test must itself not import pyautogui or
# name a League/Riot process (TASK-121 §6 FR-13, §13).
# ---------------------------------------------------------------------------


def test_consolidation_never_imports_pyautogui() -> None:
    """This test file's own source must not import ``pyautogui`` or name a League process.

    Same defensive AST walk as ``test_leagueoflegends_contracts_episode`` —
    applied to the test file itself so the consolidation cannot sneak in a
    forbidden import. The check is structural: it walks every ``import`` /
    ``from … import …`` statement and fails on a forbidden top-level or a
    forbidden substring inside any imported module name.
    """
    # ``pyautogui`` is the one concrete desktop-automation library the
    # brief calls out. The League-process substrings are the ones named
    # in §13 operational safeguards (the windows the agent must never
    # drive) and §6 FR-13 (the real-client helpers).
    forbidden_top_level = {"pyautogui"}
    forbidden_substrings = (
        "RiotClientServices",  # Riot launcher executable
        "LeagueClientUx",     # LCU API client library / executable
        "RiotClient",         # Riot client process / launcher
    )

    # AST-walk the test file's own source — the consolidation test must
    # not itself smuggle in a forbidden import.
    with open(__file__, encoding="utf-8") as f:
        test_src = f.read()
    tree = ast.parse(test_src)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in forbidden_top_level:
                    pytest.fail(
                        f"this consolidation test has 'import {alias.name}' "
                        f"— forbidden by TASK-121 §6 FR-13."
                    )
                for bad in forbidden_substrings:
                    if bad in alias.name:
                        pytest.fail(
                            f"this consolidation test imports '{alias.name}' "
                            f"which references a League/Riot process."
                        )
        elif isinstance(node, ast.ImportFrom):
            mod_name = node.module or ""
            root = mod_name.split(".")[0]
            if root in forbidden_top_level:
                pytest.fail(
                    f"this consolidation test has 'from {mod_name} import …' "
                    f"— forbidden by TASK-121 §6 FR-13."
                )
            for bad in forbidden_substrings:
                if bad in mod_name:
                    pytest.fail(
                        f"this consolidation test imports from '{mod_name}' "
                        f"which references a League/Riot process."
                    )
