"""Tests for the League of Legends vision-agent runner (TASK-121 §4.3, §10).

Covers :class:`shared.src.lib.game.leagueoflegends.runner.LeagueRunner`,
:class:`RunnerState`, :class:`StopReason`, and :class:`RunnerError`.

The runner is the orchestrator that ties the typed contracts into one
state machine + run loop. It is **deterministic** and **side-effect
free** — these tests do NOT drive a real client, do NOT import
``pyautogui``, and do NOT spawn subprocesses (the AST walk at the
bottom proves the absence of any of those).
"""

from __future__ import annotations

import ast
import inspect
import re
from typing import Optional, Tuple

import pytest

from shared.src.lib.game.leagueoflegends.contracts_decision import (
    Decision,
    Point,
    _AbstainAction,
    _MoveAction,
    _WaitAction,
)
from shared.src.lib.game.leagueoflegends.contracts_episode import (
    LabelEnvelope,
    WalkthroughFrame,
)
from shared.src.lib.game.leagueoflegends.contracts_simulator import SimulatorTarget
from shared.src.lib.game.leagueoflegends.runner import (
    LeagueRunner,
    RunnerError,
    RunnerState,
    StopReason,
)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


_TARGET_ID = "sim-1"
_TARGET_KIND = "custom-moba"


def _make_target(
    target_id: str = _TARGET_ID,
    target_kind: str = _TARGET_KIND,
    license_review_status: str = "self-built",
    build_commit_sha: Optional[str] = "abc1234",
    exe_path: Optional[str] = None,
) -> SimulatorTarget:
    """Build a valid, default-safe ``SimulatorTarget``.

    Defaults to ``custom-moba`` + ``self-built`` so the model validator
    is happy (``build_commit_sha`` is required for ``custom-moba``).
    """
    return SimulatorTarget(
        schema_version="league-simulator/v1",
        target_kind=target_kind,  # type: ignore[arg-type]
        target_id=target_id,
        display_name="test sim",
        license_review_url=None,
        license_review_status=license_review_status,  # type: ignore[arg-type]
        build_commit_sha=build_commit_sha,
        exe_path=exe_path,
        validation_metrics_url=None,
        notes="",
    )


def _make_frame(frame_id: int = 0) -> WalkthroughFrame:
    """Build a valid :class:`WalkthroughFrame`."""
    return WalkthroughFrame(
        frame_id=frame_id,
        frame_hash=f"hash-{frame_id:03d}",
        acquired_at_monotonic_ns=1_000_000_000 + frame_id,
        source_dimensions=(1920, 1080),
        focus_app="LoL-Sim",
        app_windows_rect=(0, 0, 1920, 1080),
        label=LabelEnvelope(
            current_step=1,
            next_intended_action="step",
            expected_outcome="step",
        ),
    )


def _move_dec(
    observation_id: str = "obs-1",
    confidence: float = 0.7,
) -> Decision:
    """Build a valid :class:`Decision` that proposes a MOVE to (0.5, 0.5)."""
    return Decision(
        schema_version="league-decision/v1",
        observation_id=observation_id,
        action=_MoveAction(type="MOVE", target=Point(x=0.5, y=0.5)),
        confidence=confidence,
        reason="test move",
        policy_mode="simulator",
    )


def _abstain_dec(observation_id: str = "obs-1") -> Decision:
    """Build a :class:`Decision` that proposes ABSTAIN."""
    return Decision(
        schema_version="league-decision/v1",
        observation_id=observation_id,
        action=_AbstainAction(type="ABSTAIN", reason="model uncertain"),
        confidence=0.9,
        reason="abstain test",
        policy_mode="simulator",
    )


def _wait_dec(observation_id: str = "obs-1") -> Decision:
    """Build a :class:`Decision` that proposes WAIT."""
    return Decision(
        schema_version="league-decision/v1",
        observation_id=observation_id,
        action=_WaitAction(type="WAIT"),
        confidence=0.9,
        reason="wait test",
        policy_mode="simulator",
    )


# ---------------------------------------------------------------------------
# Construction: state defaults + FR-15 hard refusal.
# ---------------------------------------------------------------------------


def test_runner_initial_state_is_discover() -> None:
    """A fresh ``LeagueRunner`` starts in ``DISCOVER`` (§4.3)."""
    runner = LeagueRunner(_make_target(), lease_token="lease-1", focus_app="app")
    assert runner.state == RunnerState.DISCOVER
    assert runner.stop_reason is None
    assert runner.decisions == ()
    assert runner.frames_observed == 0
    assert runner.simulator_target.target_id == _TARGET_ID
    assert runner.simulator_target.target_kind == _TARGET_KIND
    # ``RunnerState.DISCOVER == "discover"`` per the spec.
    assert RunnerState.DISCOVER.value == "discover"


def test_runner_hard_refuses_real_league_target_via_model_construct() -> None:
    """``model_construct(target_kind="real-league")`` bypasses the schema's Literal
    gate; the runner's own ``getattr`` check catches it (FR-15 defense in
    depth at the orchestrator).
    """
    # ``model_construct`` skips validators, so this construction
    # succeeds with ``target_kind="real-league"`` — a value the schema
    # would normally reject.
    target = SimulatorTarget.model_construct(
        schema_version="league-simulator/v1",
        target_kind="real-league",
        target_id="x",
        display_name="x",
        license_review_url=None,
        license_review_status="unknown",
        build_commit_sha=None,
        exe_path=None,
        validation_metrics_url=None,
        notes="",
    )
    with pytest.raises(RunnerError) as excinfo:
        LeagueRunner(target)
    assert "refused" in str(excinfo.value).lower()
    assert "real League process" in str(excinfo.value)


def test_runner_hard_refuses_exe_path_with_riot_substring() -> None:
    """An ``exe_path`` naming a real Riot binary is refused by the runner's
    defense layer.

    We use ``model_construct`` to bypass the schema's exe_path validator
    and let the runner's own substring check catch it. The FR-15 layered
    defense at the orchestrator: schema gate first, runner gate second.
    """
    target = SimulatorTarget.model_construct(
        schema_version="league-simulator/v1",
        target_kind="custom-moba",
        target_id="x",
        display_name="x",
        license_review_url=None,
        license_review_status="self-built",
        build_commit_sha="abc",
        exe_path="C:\\RiotClientServices.exe",
        validation_metrics_url=None,
        notes="",
    )
    with pytest.raises(RunnerError) as excinfo:
        LeagueRunner(target)
    assert "refused" in str(excinfo.value).lower()


def test_runner_hard_refuses_exe_path_with_leagueclientux() -> None:
    """An ``exe_path`` naming ``LeagueClientUx`` is refused by the runner's
    defense layer."""
    target = SimulatorTarget.model_construct(
        schema_version="league-simulator/v1",
        target_kind="custom-moba",
        target_id="x",
        display_name="x",
        license_review_url=None,
        license_review_status="self-built",
        build_commit_sha="abc",
        exe_path="C:\\LeagueClientUx.exe",
        validation_metrics_url=None,
        notes="",
    )
    with pytest.raises(RunnerError):
        LeagueRunner(target)


# ---------------------------------------------------------------------------
# Lifecycle: start.
# ---------------------------------------------------------------------------


def test_runner_start_without_lease_transitions_to_stop() -> None:
    """``start()`` without a lease token → STOP with MISSING_LEASE (FR-02)."""
    runner = LeagueRunner(_make_target(), lease_token=None, focus_app="app")
    runner.start()
    assert runner.state == RunnerState.STOP
    assert runner.stop_reason == StopReason.MISSING_LEASE


def test_runner_start_with_lease_transitions_to_capture_test() -> None:
    """``start()`` with a valid lease → CAPTURE_TEST (§4.3)."""
    runner = LeagueRunner(_make_target(), lease_token="lease-1", focus_app="app")
    runner.start()
    assert runner.state == RunnerState.CAPTURE_TEST
    assert runner.stop_reason is None


def test_runner_start_refuses_rejected_license() -> None:
    """``license_review_status == "rejected"`` → STOP with POLICY_MISMATCH (FR-15)."""
    # ``stand-in-game`` + ``rejected`` is allowed by the schema's model
    # validator (only ``community-sim`` + ``rejected`` is refused by
    # the schema); the runner catches it at ``start()``.
    target = _make_target(
        target_kind="stand-in-game",
        license_review_status="rejected",
        build_commit_sha=None,
    )
    runner = LeagueRunner(target, lease_token="lease-1", focus_app="app")
    runner.start()
    assert runner.state == RunnerState.STOP
    assert runner.stop_reason == StopReason.POLICY_MISMATCH


# ---------------------------------------------------------------------------
# Lifecycle: observe_frame.
# ---------------------------------------------------------------------------


def test_runner_observe_none_transitions_to_stop() -> None:
    """``observe_frame(None)`` → STOP with CAPTURE_FAILURE."""
    runner = LeagueRunner(_make_target(), lease_token="lease-1", focus_app="app")
    runner.start()
    runner.observe_frame(None)
    assert runner.state == RunnerState.STOP
    assert runner.stop_reason == StopReason.CAPTURE_FAILURE


def test_runner_observe_valid_frame_advances_capture_test_to_observe() -> None:
    """A valid frame in CAPTURE_TEST transitions to OBSERVE (§4.3)."""
    runner = LeagueRunner(_make_target(), lease_token="lease-1", focus_app="app")
    runner.start()
    assert runner.state == RunnerState.CAPTURE_TEST
    runner.observe_frame(_make_frame(0))
    assert runner.state == RunnerState.OBSERVE
    assert runner.frames_observed == 1


# ---------------------------------------------------------------------------
# Lifecycle: propose.
# ---------------------------------------------------------------------------


def test_runner_propose_safe_move_action_records_decision() -> None:
    """A permitted MOVE is recorded and state advances through the
    ``OBSERVE → PROPOSE → SIMULATE → VERIFY → OBSERVE`` chain.
    """
    runner = LeagueRunner(_make_target(), lease_token="lease-1", focus_app="app")
    runner.start()
    runner.observe_frame(_make_frame(0))

    decision = _move_dec()
    result = runner.propose(decision, "obs-1", 1_500_000_000)

    assert result.allowed is True
    assert result.reason_code == "ACCEPTED"
    assert len(runner.decisions) == 1
    assert runner.decisions[0][0] is decision
    assert runner.decisions[0][1] is result
    # Chain ends back at OBSERVE so the next observe_frame can resume.
    assert runner.state == RunnerState.OBSERVE


def test_runner_propose_replay_mode_always_wrong_mode() -> None:
    """In ``replay`` mode, :func:`safe_decision` returns ``WRONG_MODE``;
    runner records and transitions to ABSTAIN.

    The runner's authoritative mode defaults to ``"simulator"``; this
    test overrides the kwarg-only ``mode`` argument so the policy's
    mode gate fires. Production callers MUST NOT pass ``mode``.
    """
    runner = LeagueRunner(
        _make_target(),
        lease_token="lease-1",
        focus_app="app",
        mode="replay",
    )
    runner.start()
    runner.observe_frame(_make_frame(0))

    decision = _move_dec()
    result = runner.propose(decision, "obs-1", 1_500_000_000)

    assert result.allowed is False
    assert result.reason_code == "WRONG_MODE"
    # The rejected decision is still recorded (audit ledger).
    assert len(runner.decisions) == 1
    # The action is NOT executed — runner transitions to ABSTAIN.
    assert runner.state == RunnerState.ABSTAIN


def test_runner_propose_abstain_is_recorded() -> None:
    """``ABSTAIN`` is recorded (``allowed=False``, ``reason_code="ACCEPTED"``);
    state → ``ABSTAIN`` (§4.3 deliberate non-action branch)."""
    runner = LeagueRunner(_make_target(), lease_token="lease-1", focus_app="app")
    runner.start()
    runner.observe_frame(_make_frame(0))

    decision = _abstain_dec()
    result = runner.propose(decision, "obs-1", 1_500_000_000)

    assert result.allowed is False
    assert result.reason_code == "ACCEPTED"
    assert result.effective_action is not None
    assert result.effective_action.type == "ABSTAIN"
    assert runner.state == RunnerState.ABSTAIN
    assert len(runner.decisions) == 1


def test_runner_propose_wait_is_recorded() -> None:
    """``WAIT`` is recorded (``allowed=False``, ``reason_code="ACCEPTED"``);
    state → ``ABSTAIN``."""
    runner = LeagueRunner(_make_target(), lease_token="lease-1", focus_app="app")
    runner.start()
    runner.observe_frame(_make_frame(0))

    decision = _wait_dec()
    result = runner.propose(decision, "obs-1", 1_500_000_000)

    assert result.allowed is False
    assert result.reason_code == "ACCEPTED"
    assert result.effective_action is not None
    assert result.effective_action.type == "WAIT"
    assert runner.state == RunnerState.ABSTAIN
    assert len(runner.decisions) == 1


# ---------------------------------------------------------------------------
# Terminal-state guards.
# ---------------------------------------------------------------------------


def test_runner_propose_after_stop_raises() -> None:
    """Once STOP, :meth:`propose` raises :class:`RunnerError` (no terminal re-entry)."""
    runner = LeagueRunner(_make_target(), lease_token="lease-1", focus_app="app")
    runner.stop(StopReason.COMPLETED)
    with pytest.raises(RunnerError):
        runner.propose(_move_dec(), "obs-1", 1_500_000_000)


def test_runner_observe_after_stop_raises() -> None:
    """Once STOP, :meth:`observe_frame` raises :class:`RunnerError`."""
    runner = LeagueRunner(_make_target(), lease_token="lease-1", focus_app="app")
    runner.stop(StopReason.COMPLETED)
    with pytest.raises(RunnerError):
        runner.observe_frame(_make_frame(0))


# ---------------------------------------------------------------------------
# stop() method.
# ---------------------------------------------------------------------------


def test_runner_stop_method_records_reason() -> None:
    """``stop(reason)`` records the reason and transitions to STOP."""
    runner = LeagueRunner(_make_target(), lease_token="lease-1", focus_app="app")
    runner.stop(StopReason.COMPLETED)
    assert runner.state == RunnerState.STOP
    assert runner.stop_reason == StopReason.COMPLETED


# ---------------------------------------------------------------------------
# Read-only views.
# ---------------------------------------------------------------------------


def test_runner_decisions_property_is_readonly_tuple() -> None:
    """``decisions`` returns a tuple; ``decisions.append(...)`` raises AttributeError."""
    runner = LeagueRunner(_make_target(), lease_token="lease-1", focus_app="app")
    runner.start()
    runner.observe_frame(_make_frame(0))
    runner.propose(_move_dec(), "obs-1", 1_500_000_000)

    decisions = runner.decisions
    assert isinstance(decisions, tuple)
    assert len(decisions) == 1

    # tuple has no ``.append``; ``AttributeError`` is raised.
    with pytest.raises(AttributeError):
        decisions.append((_move_dec(), None))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Determinism.
# ---------------------------------------------------------------------------


def test_runner_deterministic_state_sequence() -> None:
    """Same call sequence → same final state and stop_reason (pure orchestrator)."""

    def run_one() -> Tuple[RunnerState, Optional[StopReason]]:
        runner = LeagueRunner(_make_target(), lease_token="lease-1", focus_app="app")
        runner.start()
        runner.observe_frame(_make_frame(0))
        runner.propose(_move_dec(), "obs-1", 1_500_000_000)
        runner.observe_frame(_make_frame(1))
        runner.propose(
            _abstain_dec(observation_id="obs-2"),
            "obs-2",
            2_500_000_000,
        )
        runner.stop(StopReason.COMPLETED)
        return runner.state, runner.stop_reason

    s1, r1 = run_one()
    s2, r2 = run_one()

    assert s1 == s2 == RunnerState.STOP
    assert r1 == r2 == StopReason.COMPLETED


# ---------------------------------------------------------------------------
# Hard-policy guard: pyautogui / League-process helpers.
# ---------------------------------------------------------------------------


def test_runner_never_imports_pyautogui() -> None:
    """The runner module MUST NOT import ``pyautogui`` or any
    League-process helper.

    Defense-in-depth: even though the brief bans pyautogui by spec, the
    test asserts the AST contains no such import. Mirrors the AST guard
    in :mod:`test_leagueoflegends_policies` so a future refactor that
    accidentally re-introduces a real-client dependency is caught here.
    """
    from shared.src.lib.game.leagueoflegends import runner as runner_mod

    assert hasattr(runner_mod, "LeagueRunner")

    forbidden_top_level = {"pyautogui"}
    forbidden_substrings = (
        "LeagueClientUx",
        "RiotClient",
        "RiotClientServices",
        "League of Legends",
    )

    src = inspect.getsource(runner_mod)
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in forbidden_top_level:
                    pytest.fail(
                        f"{runner_mod.__name__} has 'import {alias.name}' — "
                        f"forbidden by TASK-121 §6 FR-13."
                    )
                for bad in forbidden_substrings:
                    if bad in alias.name:
                        pytest.fail(
                            f"{runner_mod.__name__} imports '{alias.name}' "
                            f"which references a League/Riot process."
                        )
        elif isinstance(node, ast.ImportFrom):
            mod_name = node.module or ""
            root = mod_name.split(".")[0]
            if root in forbidden_top_level:
                pytest.fail(
                    f"{runner_mod.__name__} has 'from {mod_name} import …' — "
                    f"forbidden by TASK-121 §6 FR-13."
                )
            for bad in forbidden_substrings:
                if bad in mod_name:
                    pytest.fail(
                        f"{runner_mod.__name__} imports from '{mod_name}' "
                        f"which references a League/Riot process."
                    )

    # Plain-text check on the source with comments stripped.
    no_comments = re.sub(r"#.*", "", src)
    assert "import pyautogui" not in no_comments
    assert "from pyautogui" not in no_comments

    # The module must not expose pyautogui as a leaked attribute.
    assert "pyautogui" not in runner_mod.__dict__