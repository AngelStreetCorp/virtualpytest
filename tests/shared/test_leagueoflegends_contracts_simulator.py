"""Tests for the League of Legends simulator target schema + registry (TASK-121).

Covers :mod:`shared.src.lib.game.leagueoflegends.contracts_simulator`
(typed schema for an offline simulator target) and
:mod:`shared.src.lib.game.leagueoflegends.simulator_registry` (the
in-process registry that refuses misconfigured targets at register time).

No real League client interaction; no ``pyautogui``.
"""
from __future__ import annotations

import ast
import inspect
from typing import Any

import pytest
from pydantic import ValidationError

from shared.src.lib.game.leagueoflegends.contracts_simulator import (
    FORBIDDEN_EXE_SUBSTRINGS,
    LicenseReviewStatus,
    SimulatorTarget,
    SimulatorTargetKind,
)
from shared.src.lib.game.leagueoflegends.simulator_registry import (
    SimulatorRegistry,
    SimulatorRegistryError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_payload(**overrides: Any) -> dict:
    """Build a valid minimal ``SimulatorTarget`` payload.

    The payload uses ``target_kind="stand-in-game"`` by default because
    it has the fewest extra constraints (no license review, no commit
    sha) — tests that exercise the other kinds override ``target_kind``
    and the relevant fields below.
    """
    payload: dict[str, Any] = {
        "schema_version": "league-simulator/v1",
        "target_kind": "stand-in-game",
        "target_id": "sim-test-001",
        "display_name": "Stand-in for the operator's offline lane",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Schema tests — happy paths.
# ---------------------------------------------------------------------------


def test_simulator_target_valid_community_sim() -> None:
    """A full ``community-sim`` payload with a reviewed upstream is accepted."""
    target = SimulatorTarget(
        **_minimal_payload(
            target_kind="community-sim",
            target_id="comm-sim-abc",
            display_name="Community LoL Replay Harness",
            license_review_url="https://example.invalid/reviews/123",
            license_review_status="approved",
            exe_path="C:\\sims\\comm\\harness.exe",
            validation_metrics_url="https://example.invalid/metrics/comm-sim",
            notes="Approved on 2026-10-15 for offline replay only.",
        )
    )

    assert target.schema_version == "league-simulator/v1"
    assert target.target_kind == "community-sim"
    assert target.target_id == "comm-sim-abc"
    assert target.display_name == "Community LoL Replay Harness"
    assert target.license_review_status == "approved"
    assert target.license_review_url is not None
    assert target.exe_path is not None
    assert target.build_commit_sha is None  # we don't own a community sim
    assert target.notes.startswith("Approved")


def test_simulator_target_valid_custom_moba_with_sha() -> None:
    """A ``custom-moba`` payload with a pinned build sha is accepted."""
    target = SimulatorTarget(
        **_minimal_payload(
            target_kind="custom-moba",
            target_id="custom-moba-001",
            display_name="Custom minimal MOBA (alpha)",
            license_review_status="self-built",
            build_commit_sha="abc1234",
            exe_path="/opt/sims/moba/build/server.exe",
            notes="Built 2026-10-10 from the custom-moba branch.",
        )
    )

    assert target.target_kind == "custom-moba"
    assert target.license_review_status == "self-built"
    assert target.build_commit_sha == "abc1234"
    # And the schema_version round-trips.
    assert target.schema_version == "league-simulator/v1"


def test_simulator_target_valid_stand_in_game() -> None:
    """A ``stand-in-game`` payload (fewest constraints) is accepted."""
    target = SimulatorTarget(**_minimal_payload())

    assert target.target_kind == "stand-in-game"
    # All optional fields default to None / "" / unknown.
    assert target.license_review_url is None
    assert target.license_review_status == "unknown"
    assert target.build_commit_sha is None
    assert target.exe_path is None
    assert target.validation_metrics_url is None
    assert target.notes == ""


# ---------------------------------------------------------------------------
# Schema tests — refusal paths (target_kind Literal).
# ---------------------------------------------------------------------------


def test_simulator_target_rejects_real_league_kind() -> None:
    """``target_kind="real-league"`` is refused by the Literal (FR-15 hard gate).

    The Literal deliberately excludes ``"real-league"`` — the FR-15 contract
    is that any code path that tries to register a real-league target gets
    a ``ValidationError`` *at construction time*, before the runner ever
    sees it.
    """
    with pytest.raises(ValidationError) as excinfo:
        SimulatorTarget(**_minimal_payload(target_kind="real-league"))  # type: ignore[arg-type]

    # The Literal error names the offending value, so a future refactor
    # that silently widened the kind set would fail this assertion too.
    assert "real-league" in str(excinfo.value)


def test_simulator_target_rejects_unknown_kind() -> None:
    """A kind outside the three allowed is refused by the Literal."""
    with pytest.raises(ValidationError):
        SimulatorTarget(**_minimal_payload(target_kind="not-a-kind"))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Schema tests — refusal paths (model validators).
# ---------------------------------------------------------------------------


def test_simulator_target_rejects_community_sim_with_rejected_license() -> None:
    """``community-sim`` + ``license_review_status="rejected"`` is refused.

    Even though the Literal admits ``"rejected"`` as a status value, the
    model validator refuses to construct a target where the license
    review explicitly rejected the upstream — registering one would
    violate FR-15.
    """
    with pytest.raises(ValidationError) as excinfo:
        SimulatorTarget(
            **_minimal_payload(
                target_kind="community-sim",
                license_review_status="rejected",
                license_review_url="https://example.invalid/reviews/999",
            )
        )

    assert "rejected by license review" in str(excinfo.value)


def test_simulator_target_rejects_custom_moba_without_sha() -> None:
    """``custom-moba`` + ``build_commit_sha=None`` is refused.

    We own a custom-moba simulator and must know what we built — a missing
    sha means the pin wasn't recorded and the runner must not let it
    loose on the agent.
    """
    with pytest.raises(ValidationError) as excinfo:
        SimulatorTarget(
            **_minimal_payload(
                target_kind="custom-moba",
                build_commit_sha=None,
                license_review_status="self-built",
            )
        )

    assert "custom-moba requires build_commit_sha" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Schema tests — refusal paths (exe_path field validator).
# ---------------------------------------------------------------------------


def test_simulator_target_rejects_exe_path_riotclientservices() -> None:
    """``exe_path`` naming ``RiotClientServices`` is refused."""
    with pytest.raises(ValidationError) as excinfo:
        SimulatorTarget(
            **_minimal_payload(
                target_kind="stand-in-game",
                exe_path="C:\\Riot Games\\Riot Client\\RiotClientServices.exe",
            )
        )

    assert "real League process" in str(excinfo.value)


def test_simulator_target_rejects_exe_path_leagueclientux() -> None:
    """``exe_path`` naming ``LeagueClientUx`` is refused."""
    with pytest.raises(ValidationError) as excinfo:
        SimulatorTarget(
            **_minimal_payload(
                target_kind="stand-in-game",
                exe_path="C:\\Riot Games\\League of Legends\\LeagueClientUx.exe",
            )
        )

    assert "real League process" in str(excinfo.value)


def test_simulator_target_rejects_exe_path_league_of_legends() -> None:
    """``exe_path`` containing ``League of Legends`` (any case) is refused.

    The substring check is case-insensitive (Windows paths are too in
    practice), so a lowercase ``league of legends`` must also be caught.
    """
    with pytest.raises(ValidationError) as excinfo:
        SimulatorTarget(
            **_minimal_payload(
                target_kind="stand-in-game",
                exe_path="D:\\Program Files\\league of legends\\Game\\League.exe",
            )
        )

    assert "real League process" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Schema tests — extra / minor acceptance.
# ---------------------------------------------------------------------------


def test_simulator_target_extra_forbid() -> None:
    """An unknown key raises ``ValidationError`` (extra='forbid')."""
    with pytest.raises(ValidationError) as excinfo:
        SimulatorTarget(
            **_minimal_payload(
                not_a_field="boom",  # type: ignore[arg-type]
            )
        )
    # The error names the offending key so a future silent-extending
    # refactor would fail this assertion too.
    assert "not_a_field" in str(excinfo.value)


def test_simulator_target_license_review_status_pending_allowed() -> None:
    """``license_review_status="pending"`` is accepted (review in progress).

    A pending review is not a refusal: the upstream is still being
    evaluated and the runner should not block on it. Only ``"rejected"``
    is refused by the model validator (and only for ``community-sim``).

    Belt-and-braces: we also pin the membership of the two Literals so a
    future refactor that silently widened either set would fail this test
    (e.g. sneaking ``"real-league"`` back into :data:`SimulatorTargetKind`).
    """
    target = SimulatorTarget(
        **_minimal_payload(
            target_kind="community-sim",
            license_review_status="pending",
            license_review_url="https://example.invalid/reviews/321",
        )
    )
    assert target.license_review_status == "pending"
    # Pin the kind Literal — ``real-league`` must stay out.
    assert SimulatorTargetKind.__args__ == (  # type: ignore[attr-defined]
        "community-sim",
        "custom-moba",
        "stand-in-game",
    )
    # And the review-status Literal — ``pending`` must stay in.
    assert LicenseReviewStatus.__args__ == (  # type: ignore[attr-defined]
        "approved",
        "pending",
        "rejected",
        "self-built",
        "unknown",
    )


# ---------------------------------------------------------------------------
# Registry tests.
# ---------------------------------------------------------------------------


def test_simulator_registry_register_and_get() -> None:
    """Register a stand-in-game target and look it up."""
    registry = SimulatorRegistry()

    target = SimulatorTarget(**_minimal_payload(target_id="stand-in-1"))
    registry.register(target)

    assert len(registry) == 1
    fetched = registry.get("stand-in-1")
    assert fetched is not None
    assert fetched.target_id == "stand-in-1"
    assert fetched.target_kind == "stand-in-game"


def test_simulator_registry_register_refuses_riot_path() -> None:
    """``SimulatorRegistryError`` raised for a banned ``exe_path``.

    Even though the schema already refuses to construct such a target,
    the registry re-applies the check at register time (defense in
    depth) so a future bypass via ``model_construct`` is still caught.
    """
    from pydantic import BaseModel

    from shared.src.lib.game.leagueoflegends.contracts_simulator import (
        SimulatorTarget as ST,
    )

    registry = SimulatorRegistry()

    # Build a SimulatorTarget that *skips* the field validator by going
    # through ``model_construct`` — this is the bypass scenario the
    # registry must still catch.
    bypassed = ST.model_construct(  # type: ignore[call-overload]
        schema_version="league-simulator/v1",
        target_kind="stand-in-game",
        target_id="bypass-1",
        display_name="Bypass via model_construct",
        license_review_url=None,
        license_review_status="unknown",
        build_commit_sha=None,
        exe_path="C:\\Riot Games\\Riot Client\\RiotClientServices.exe",
        validation_metrics_url=None,
        notes="",
    )
    # The bypassed instance exists (model_construct skips validators).
    assert bypassed.exe_path is not None

    with pytest.raises(SimulatorRegistryError) as excinfo:
        registry.register(bypassed)  # type: ignore[arg-type]

    assert "real League process" in str(excinfo.value)
    # And nothing was registered (the bypass was refused).
    assert len(registry) == 0


def test_simulator_registry_register_idempotent_on_id() -> None:
    """Re-registering the same ``target_id`` replaces (the new entry wins)."""
    registry = SimulatorRegistry()

    first = SimulatorTarget(**_minimal_payload(target_id="sim-x", display_name="first"))
    second = SimulatorTarget(
        **_minimal_payload(target_id="sim-x", display_name="second")
    )

    registry.register(first)
    registry.register(second)

    # Only one entry (replace, not append).
    assert len(registry) == 1
    fetched = registry.get("sim-x")
    assert fetched is not None
    assert fetched.display_name == "second"


def test_simulator_registry_list_approved() -> None:
    """``list_approved`` only returns targets with status ``approved`` / ``self-built``."""
    registry = SimulatorRegistry()

    registry.register(
        SimulatorTarget(
            **_minimal_payload(
                target_id="approved-1",
                target_kind="community-sim",
                license_review_status="approved",
                license_review_url="https://example.invalid/reviews/1",
            )
        )
    )
    registry.register(
        SimulatorTarget(
            **_minimal_payload(
                target_id="self-built-1",
                target_kind="custom-moba",
                license_review_status="self-built",
                build_commit_sha="deadbeef",
            )
        )
    )
    registry.register(
        SimulatorTarget(
            **_minimal_payload(
                target_id="pending-1",
                target_kind="community-sim",
                license_review_status="pending",
                license_review_url="https://example.invalid/reviews/2",
            )
        )
    )
    registry.register(
        SimulatorTarget(
            **_minimal_payload(
                target_id="unknown-1",
                target_kind="stand-in-game",
            )
        )
    )

    approved = registry.list_approved()
    approved_ids = sorted(t.target_id for t in approved)
    assert approved_ids == ["approved-1", "self-built-1"]


def test_simulator_registry_refuses_real_league_class_contract() -> None:
    """FR-15 contract assertion: ``refuses_real_league()`` is ``True``.

    This is the single source of truth the spec calls out: any code path
    that asks "does this registry refuse real-league?" must read this
    attribute. A future refactor that adds a leak vector MUST keep this
    assertion honest — if it ever returns ``False``, the FR-15 contract
    is broken.
    """
    # Class-level: callable on the class itself (classmethod).
    assert SimulatorRegistry.refuses_real_league() is True
    # And on an instance (the contract is class-wide).
    assert SimulatorRegistry().refuses_real_league() is True


def test_simulator_registry_forbidden_substrings_exported() -> None:
    """``FORBIDDEN_EXE_SUBSTRINGS`` is importable and contains the four substrings."""
    # Import from the registry module (the canonical public location for
    # the runner to read the forbidden list).
    from shared.src.lib.game.leagueoflegends.simulator_registry import (  # noqa: F401,WPS433
        FORBIDDEN_EXE_SUBSTRINGS as REG_FORBIDDEN,
    )

    assert REG_FORBIDDEN is FORBIDDEN_EXE_SUBSTRINGS
    # It must be a tuple (immutable — the runner / tests should not
    # mutate this list).
    assert isinstance(FORBIDDEN_EXE_SUBSTRINGS, tuple)
    # All four substrings from the spec are present.
    expected = (
        "riotclientservices",
        "leagueclientux",
        "league of legends",
        "riot games\\riot client",
    )
    for needle in expected:
        assert needle in FORBIDDEN_EXE_SUBSTRINGS, (
            f"FORBIDDEN_EXE_SUBSTRINGS missing {needle!r}"
        )


# ---------------------------------------------------------------------------
# Static guard: pyautogui / League-process leak check.
# ---------------------------------------------------------------------------


def test_simulator_module_never_imports_pyautogui() -> None:
    """AST-walk the two module sources; fail on any forbidden import.

    Mirrors the lobby / client / decision test pattern: the source file
    MUST NOT import ``pyautogui`` or any League-process helper. This is
    the single point that pins the no-desktop-automation guarantee for
    §6 FR-13 / FR-15 in the simulator-target layer (the registry is the
    one that picks the executable path; if *it* imported pyautogui the
    whole layer would be unsafe).

    We deliberately avoid ``"pyautogui" not in sys.modules`` — the broader
    test suite (desktop controllers, etc.) is free to import it for
    unrelated reasons; that pollution is not this layer's concern.
    """
    import shared.src.lib.game.leagueoflegends.contracts_simulator as contracts_mod  # noqa: F401
    import shared.src.lib.game.leagueoflegends.simulator_registry as registry_mod  # noqa: F401

    forbidden_top_level = {"pyautogui"}
    # These strings must never appear in an import statement of either
    # module — they're the spec'd real-League-process identifiers.
    forbidden_substrings = (
        "LeagueClientUx",
        "RiotClient",
        "RiotClientServices",
        "League of Legends",
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
                            f"{mod.__name__} has 'import {alias.name}' — "
                            "forbidden by TASK-121 §6 FR-13."
                        )
                    for bad in forbidden_substrings:
                        if bad in alias.name:
                            pytest.fail(
                                f"{mod.__name__} imports '{alias.name}' "
                                "which references a League/Riot process."
                            )
            elif isinstance(node, ast.ImportFrom):
                mod_name = node.module or ""
                root = mod_name.split(".")[0]
                if root in forbidden_top_level:
                    pytest.fail(
                        f"{mod.__name__} has 'from {mod_name} import …' — "
                        "forbidden by TASK-121 §6 FR-13."
                    )
                for bad in forbidden_substrings:
                    if bad in mod_name:
                        pytest.fail(
                            f"{mod.__name__} imports from '{mod_name}' "
                            "which references a League/Riot process."
                        )
        # Belt-and-braces: a plain-text scan on the uncommented source
        # catches any future bad import that slips past the AST walk.
        import re as _re

        uncommented = _re.sub(r"#.*", "", src)
        assert "import pyautogui" not in uncommented
        assert "from pyautogui" not in uncommented

    _check_no_forbidden(contracts_mod)
    _check_no_forbidden(registry_mod)

    # Defensive: the modules must not expose ``pyautogui`` as an attribute
    # (e.g. via a star import).
    assert "pyautogui" not in contracts_mod.__dict__
    assert "pyautogui" not in registry_mod.__dict__
