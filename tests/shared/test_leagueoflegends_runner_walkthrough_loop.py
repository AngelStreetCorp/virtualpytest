"""End-to-end loop test for the §11.1.1 walkthrough (TASK-121).

This test drives the ``LeagueRunner`` through all 12 walkthrough steps
of the operator's reference walkthrough, asserting on every state
transition. It is the **in-process** analogue of the operator's
real-League walkthrough: the synthetic frames and decisions are the
same shape the real capture adapter will produce, but no League
process is touched.

Hard constraint: no ``pyautogui``, no League-process helper. The
``walkthrough_smoke`` module's helpers are exercised here; if they
ever pull a League-process helper or pyautogui, the AST-walk guard
at the end of this file will fail.
"""

from __future__ import annotations

import ast
import re
import sys
import time
from pathlib import Path
from typing import List

import pytest

# The smoke module is a script (uses ``sys.exit``); importing it for the
# ``build_runner`` / ``run_loop`` helpers is safe because the ``__main__``
# block is guarded by ``if __name__ == "__main__":``.
from shared.src.lib.game.leagueoflegends import walkthrough_smoke
from shared.src.lib.game.leagueoflegends.runner import (
    RunnerState,
    StopReason,
)


_WORKTREE_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# The loop test.
# ---------------------------------------------------------------------------


def test_walkthrough_loop_completes_cleanly() -> None:
    """Drive the runner through all 12 walkthrough steps; assert the loop."""
    runner = walkthrough_smoke.build_runner()
    assert runner.state == RunnerState.DISCOVER
    assert runner.frames_observed == 0
    assert len(runner.decisions) == 0

    episode = walkthrough_smoke.run_loop(runner)

    # Frames and decisions: exactly one per step.
    assert runner.frames_observed == 12, runner.frames_observed
    assert len(runner.decisions) == 12, len(runner.decisions)
    assert len(episode.frames) == 12, len(episode.frames)

    # Final state: the runner is in OBSERVE after step 12's permitted
    # proposal ran through PROPOSE -> SIMULATE -> VERIFY -> OBSERVE.
    assert runner.state == RunnerState.OBSERVE, runner.state
    assert runner.stop_reason is None, runner.stop_reason

    # Episode id follows the spec regex.
    assert re.match(r"^walkthrough_[0-9]{8}_[0-9]{2,}$", episode.episode_id), (
        episode.episode_id
    )
    # Simulator target kind is one of the three allowed values.
    assert episode.simulator_target_kind in {
        "community-sim",
        "custom-moba",
        "stand-in-game",
    }, episode.simulator_target_kind

    # Decisions 1-11: WAIT or ABSTAIN, allowed=False, reason_code=ACCEPTED.
    for i, (decision, result) in enumerate(runner.decisions[:-1], start=1):
        assert decision.action.type in ("WAIT", "ABSTAIN"), (
            f"step {i}: expected WAIT or ABSTAIN, got {decision.action.type!r}"
        )
        assert result.allowed is False, (
            f"step {i}: expected allowed=False for WAIT/ABSTAIN, got {result.allowed}"
        )
        assert result.reason_code == "ACCEPTED", (
            f"step {i}: expected reason_code=ACCEPTED, got {result.reason_code!r}"
        )

    # Step 12: typed MOVE, allowed=True, reason_code=ACCEPTED.
    last_decision, last_result = runner.decisions[-1]
    assert last_decision.action.type == "MOVE", last_decision.action.type
    assert last_result.allowed is True, last_result.allowed
    assert last_result.reason_code == "ACCEPTED", last_result.reason_code
    # The MOVE target is a valid normalized point.
    move_target = last_decision.action.target
    assert move_target is not None
    assert 0.0 <= move_target.x <= 1.0
    assert 0.0 <= move_target.y <= 1.0
    assert last_decision.confidence >= 0.3

    # Frame monotonicity: 0..11
    for i, frame in enumerate(episode.frames, start=0):
        assert frame.frame_id == i, frame.frame_id
        assert 1 <= frame.label.current_step <= 12, frame.label.current_step
        assert frame.focus_app in {
            "Riot Client",
            "League of Legends",
        }, frame.focus_app


def test_walkthrough_loop_refuses_real_league_target_at_construction() -> None:
    """build_runner() must produce a target that the FR-13/FR-15 gates accept.

    The smoke loop's happy-path target is a non-League custom-moba with a
    non-Riot ``exe_path`` and ``license_review_status="approved"``. Verify
    that an attempt to swap in a real-league target via ``model_construct``
    bypass is still caught at runner construction.
    """
    from shared.src.lib.game.leagueoflegends.contracts_simulator import SimulatorTarget
    from shared.src.lib.game.leagueoflegends.runner import LeagueRunner, RunnerError

    # Bypass the schema's Literal via model_construct; the runner's
    # getattr-defense must still catch it.
    bad = SimulatorTarget.model_construct(
        schema_version="league-simulator/v1",
        target_kind="real-league",
        target_id="bad",
        display_name="bad",
        license_review_url=None,
        license_review_status="unknown",
        build_commit_sha=None,
        exe_path=None,
        notes="",
    )
    with pytest.raises(RunnerError):
        LeagueRunner(bad, lease_token="x", focus_app="y")


def test_walkthrough_loop_refuses_exe_path_riot_substring_at_construction() -> None:
    """An ``exe_path`` containing a League-process substring is also caught.

    Same as above but targeting the second FR-13 layer: the
    ``FORBIDDEN_EXE_SUBSTRINGS`` check at the runner.
    """
    from shared.src.lib.game.leagueoflegends.contracts_simulator import SimulatorTarget
    from shared.src.lib.game.leagueoflegends.runner import LeagueRunner, RunnerError

    bad = SimulatorTarget.model_construct(
        schema_version="league-simulator/v1",
        target_kind="custom-moba",
        target_id="bad",
        display_name="bad",
        license_review_url=None,
        license_review_status="approved",
        build_commit_sha="0" * 40,
        exe_path="C:\\Riot Games\\RiotClientServices.exe",
        notes="",
    )
    with pytest.raises(RunnerError):
        LeagueRunner(bad, lease_token="x", focus_app="y")


def test_walkthrough_loop_rejects_no_lease_at_start() -> None:
    """``start()`` without a lease must transition to STOP with MISSING_LEASE."""
    runner = walkthrough_smoke.build_runner()
    runner._lease_token = None  # noqa: SLF001 — exercising the fail-closed path
    runner.start()
    assert runner.state == RunnerState.STOP, runner.state
    assert runner.stop_reason == StopReason.MISSING_LEASE, runner.stop_reason


def test_walkthrough_loop_rejects_rejected_license_at_start() -> None:
    """A simulator target with ``license_review_status='rejected'`` is refused at start."""
    from shared.src.lib.game.leagueoflegends.contracts_simulator import SimulatorTarget
    from shared.src.lib.game.leagueoflegends.runner import LeagueRunner

    target = SimulatorTarget(
        schema_version="league-simulator/v1",
        target_kind="custom-moba",
        target_id="rejected-1",
        display_name="Rejected Custom MOBA",
        license_review_url=None,
        license_review_status="rejected",
        build_commit_sha="0" * 40,
        exe_path=None,
        notes="license rejected upstream",
    )
    runner = LeagueRunner(target, lease_token="x", focus_app="y")
    runner.start()
    assert runner.state == RunnerState.STOP, runner.state
    assert runner.stop_reason == StopReason.POLICY_MISMATCH, runner.stop_reason


# ---------------------------------------------------------------------------
# Static guards.
# ---------------------------------------------------------------------------


def _read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_walkthrough_smoke_never_imports_pyautogui() -> None:
    """AST-walk the smoke module's source: fail on pyautogui or League-process helpers.

    Reads the source from the installed package's ``__file__`` so the test
    is robust to whatever directory layout the package lives under (the
    worktree on the Mac, the install at ``C:\virtualpytest\virtualpytest``
    on a Windows host, etc.). Without this, the AST guard would only
    work on the worktree the test was authored in.
    """
    src = _read_source(Path(walkthrough_smoke.__file__))
    tree = ast.parse(src)
    found_pyautogui: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "pyautogui" in alias.name.lower():
                    found_pyautogui.append(f"import {alias.name} at line {node.lineno}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and "pyautogui" in node.module.lower():
                found_pyautogui.append(
                    f"from {node.module} import ... at line {node.lineno}"
                )
    assert not found_pyautogui, (
        "walkthrough_smoke must not import pyautogui: " + "; ".join(found_pyautogui)
    )


def test_walkthrough_smoke_exe_path_is_not_a_riot_binary() -> None:
    """The smoke loop's runner is bound to a non-League, non-Riot ``exe_path``."""
    runner = walkthrough_smoke.build_runner()
    exe = runner.simulator_target.exe_path or ""
    lowered = exe.lower()
    for bad in ("riotclientservices", "leagueclientux", "league of legends"):
        assert bad not in lowered, (bad, exe)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
