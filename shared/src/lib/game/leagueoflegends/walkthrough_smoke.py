"""Synthetic walkthrough loop smoke runner for the League of Legends agent.

This script is the **in-process** analogue of the operator's 12-step
reference walkthrough in TASK-121 §11.1.1. It feeds the runner a synthetic
``WalkthroughFrame`` per step and a typed ``Decision`` that the agent would
emit for that step (WAIT/ABSTAIN for operator-driven steps, a typed MOVE
once we reach the in-game top lane). It then prints the resulting state
trace.

The script does **not** launch any real League process. It does not touch
``pyautogui``, does not open the Riot Client, does not fill credentials, does
not click PLAY, does not pick a champion, does not buy items. Every action
attributed to the human operator (steps 1-11) is recorded as a label
envelope, not executed; the only ``Decision`` the runner routes through
``safe_decision`` is the in-game step-12 MOVE, which the runner records in
its audit ledger.

Usage (from the worktree root)::

    cd <repo-root>
    /usr/local/bin/python3 -m shared.src.lib.game.leagueoflegends.walkthrough_smoke

Exit code 0 on clean run-through; non-zero on any policy refusal, schema
rejection, or state-machine violation.
"""

from __future__ import annotations

import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, List, Tuple

from pydantic import TypeAdapter

from shared.src.lib.game.leagueoflegends.contracts_decision import (
    Action,
    Decision,
)
from shared.src.lib.game.leagueoflegends.contracts_episode import (
    LabelEnvelope,
    WalkthroughEpisode,
    WalkthroughFrame,
    WalkthroughStep,
)
from shared.src.lib.game.leagueoflegends.contracts_simulator import SimulatorTarget
from shared.src.lib.game.leagueoflegends.runner import (
    LeagueRunner,
    RunnerState,
    StopReason,
)

# Module-level TypeAdapter for the discriminated Action union. Pydantic
# v2's discriminated union (``Annotated[Union[...], Field(discriminator="type")]``)
# is not itself a Pydantic model, so a TypeAdapter is the canonical way to
# construct the right branch from a dict.
_ACTION_ADAPTER: TypeAdapter = TypeAdapter(Action)


# ---------------------------------------------------------------------------
# Static step table (TASK-121 §11.1.1).
# ---------------------------------------------------------------------------

# Each row: (focus_app_at_step, expected_outcome, next_intended_action, agent_decision_kind)
# `agent_decision_kind` is one of "wait", "abstain", "move_top".
# The smoke script maps this to the corresponding Decision. Steps 1-11 are
# operator-driven and the agent records a deliberate non-action (WAIT for
# the launch/queue/load phases, ABSTAIN for the operator's explicit picks
# like Garen / runes / shop). Step 12 is the in-game tick where the agent
# actually emits a typed top-lane action against the offline simulator.
_STEP_TABLE: List[Tuple[str, str, str, str]] = [
    (
        "Riot Client",
        "Riot Client window is visible with the product tile grid",
        "Operator: launch RiotClientServices.exe if not running",
        "wait",
    ),
    (
        "Riot Client",
        "League of Legends tile is highlighted; the LoL launcher becomes active",
        "Operator: click the League of Legends tile",
        "wait",
    ),
    (
        "League of Legends",
        "League client is up; Play view is the foreground",
        "Operator: click PLAY (top left)",
        "wait",
    ),
    (
        "League of Legends",
        "Training tab is the only enabled match option",
        "Operator: select Training -> Practice Tool",
        "wait",
    ),
    (
        "League of Legends",
        "Practice Tool lobby is open with the slot-empty bot config; role is unselected",
        "Operator: add one bot on each side, leave role empty",
        "wait",
    ),
    (
        "League of Legends",
        "Lobby is full (1 human + 2 bots); Start button is enabled",
        "Operator: click Start (begin champion select)",
        "wait",
    ),
    (
        "League of Legends",
        "Champion-select screen is open; pick timer is counting down",
        "Operator: pick a champion (Garen) and confirm",
        "abstain",
    ),
    (
        "League of Legends",
        "Garen is locked in; the pick timer is paused",
        "Operator: type Garen and confirm the pick",
        "abstain",
    ),
    (
        "League of Legends",
        "Rune page is locked; the recommended page from Riot is selected",
        "Operator: click Take Recommended (bottom right)",
        "abstain",
    ),
    (
        "League of Legends",
        "Loading screen shows both teams; ~60s to in-game",
        "Operator: wait for the load to complete",
        "wait",
    ),
    (
        "League of Legends",
        "In-game shop is open; recommended items appear in the suggest list",
        "Operator: buy recommended items and upgrade the recommended spell",
        "abstain",
    ),
    (
        "League of Legends",
        "In-game top lane; minimap shows blue-side top with a 1v0 lane state",
        "Agent: emit a typed Decision for the first top-lane tick",
        "move_top",
    ),
]


# ---------------------------------------------------------------------------
# Synthetic frame + decision builders.
# ---------------------------------------------------------------------------


def _make_frame(
    step: WalkthroughStep,
    focus_app: str,
    expected_outcome: str,
    next_intended_action: str,
    frame_id: int,
) -> WalkthroughFrame:
    """Build a synthetic ``WalkthroughFrame`` for one step of the loop."""
    return WalkthroughFrame(
        frame_id=frame_id,
        frame_hash=f"<smoke-frame-{step:02d}-{uuid.uuid4().hex[:8]}>",
        acquired_at_monotonic_ns=time.monotonic_ns(),
        source_dimensions=(1280, 720),
        focus_app=focus_app,
        app_windows_rect=(0, 0, 1280, 720),
        label=LabelEnvelope(
            current_step=step,
            next_intended_action=next_intended_action,
            expected_outcome=expected_outcome,
            operator_note="<smoke run, no real client>",
            unknown=False,
        ),
    )


def _make_decision(
    step: WalkthroughStep,
    kind: str,
    observation_id: str,
    observation_acquired_at_ns: int,
) -> Decision:
    """Build a typed ``Decision`` for one step of the loop.

    * ``"wait"`` steps emit ``WAIT`` (deliberate non-action during operator
      setup; the runner routes through ``safe_decision`` which records it
      as ``reason_code="ACCEPTED"``, ``allowed=False``).
    * ``"abstain"`` steps emit ``ABSTAIN`` (the operator made a choice;
      the agent records it but does not act).
    * ``"move_top"`` (only step 12) emits a typed ``MOVE`` to the top lane,
      which is the only step where the agent's autonomous decision would
      actually be proposed against the offline simulator target.
    """
    if kind == "wait":
        action_payload: dict[str, Any] = {"type": "WAIT"}
    elif kind == "abstain":
        action_payload = {
            "type": "ABSTAIN",
            "reason": f"Operator-driven step {step}; agent records the choice.",
        }
    elif kind == "move_top":
        # 0.42, 0.66 = roughly mid-top-lane in the normalized screen;
        # a future vision detector will replace this with a real
        # (x, y) from a per-frame minimap/HUD crop.
        action_payload = {"type": "MOVE", "target": {"x": 0.42, "y": 0.66}}
    else:
        raise ValueError(f"unknown decision kind {kind!r}")

    action = _ACTION_ADAPTER.validate_python(action_payload)

    return Decision(
        schema_version="league-decision/v1",
        observation_id=observation_id,
        action=action,
        confidence=0.91,
        reason=f"smoke-loop step {step} ({kind})",
        policy_mode="simulator",
    )


# ---------------------------------------------------------------------------
# The smoke loop.
# ---------------------------------------------------------------------------


def build_runner() -> LeagueRunner:
    """Construct a runner bound to a non-League, license-cleared simulator target.

    The custom-moba kind with a non-League ``exe_path`` and
    ``license_review_status="approved"`` is the canonical happy-path target.
    The runner's three-layer FR-13/FR-15 defense accepts it; the agent's
    autonomous play routes through this target only.
    """
    target = SimulatorTarget(
        schema_version="league-simulator/v1",
        target_kind="custom-moba",
        target_id="smoke-loop-custom-moba-001",
        display_name="Smoke Loop Custom MOBA (Phase 1 build)",
        license_review_url=None,
        license_review_status="approved",
        build_commit_sha="0" * 40,
        exe_path="/opt/simulators/league-moba/main.py",
        validation_metrics_url=None,
        notes="Phase 1 smoke loop; not a League binary, not a Riot binary.",
    )
    return LeagueRunner(
        target,
        lease_token="smoke-loop-lease",  # placeholder; not a real lease
        focus_app="league-of-legends-simulator",
    )


def run_loop(runner: LeagueRunner) -> WalkthroughEpisode:
    """Drive the runner through the 12-step walkthrough; return the resulting episode.

    Returns the synthesized ``WalkthroughEpisode`` so callers (the smoke
    CLI and the pytest loop test) can assert on the final state, the
    recorded decisions, and the per-step frame/decision pairing.
    """
    if runner.state != RunnerState.DISCOVER:
        raise RuntimeError(f"runner must be in DISCOVER, got {runner.state}")

    runner.start()
    if runner.state != RunnerState.CAPTURE_TEST:
        raise RuntimeError(
            f"runner.start() did not advance to CAPTURE_TEST; "
            f"state={runner.state} stop_reason={runner.stop_reason}"
        )

    operator = "smoke-loop"
    host_fingerprint = "smoke-loop-host-fingerprint"
    simulator_target_kind = runner.simulator_target.target_kind
    episode_id = f"walkthrough_{datetime.now(timezone.utc).strftime('%Y%m%d')}_99"
    episode = WalkthroughEpisode(
        schema_version="league-episode/v1",
        episode_id=episode_id,
        operator=operator,
        host_fingerprint=host_fingerprint,
        started_at_utc=datetime.now(timezone.utc),
        frames=[],
        simulator_target_kind=simulator_target_kind,  # type: ignore[arg-type]
    )

    for step_idx, (focus_app, expected_outcome, next_intended, decision_kind) in enumerate(
        _STEP_TABLE, start=1
    ):
        step: WalkthroughStep = step_idx  # type: ignore[assignment]
        frame = _make_frame(
            step=step,
            focus_app=focus_app,
            expected_outcome=expected_outcome,
            next_intended_action=next_intended,
            frame_id=step_idx - 1,
        )
        runner.observe_frame(frame)
        episode.frames.append(frame)

        observation_id = f"smoke-step-{step_idx:02d}-{uuid.uuid4().hex[:8]}"
        decision = _make_decision(
            step=step,
            kind=decision_kind,
            observation_id=observation_id,
            observation_acquired_at_ns=frame.acquired_at_monotonic_ns,
        )
        runner.propose(decision, observation_id, frame.acquired_at_monotonic_ns)

    return episode


def main(argv: List[str]) -> int:
    runner = build_runner()
    episode = run_loop(runner)

    print("=" * 72)
    print("League of Legends walkthrough loop (smoke run)")
    print("=" * 72)
    print(f"episode_id                = {episode.episode_id}")
    print(f"simulator_target_kind     = {episode.simulator_target_kind}")
    print(f"runner.state              = {runner.state.value}")
    print(f"runner.stop_reason        = {runner.stop_reason.value if runner.stop_reason else None}")
    print(f"frames_observed           = {runner.frames_observed}")
    print(f"decisions_recorded        = {len(runner.decisions)}")
    print()
    print("Per-step trace:")
    for idx, (decision, result) in enumerate(runner.decisions, start=1):
        action_kind = decision.action.type
        allowed = "ALLOW" if result.allowed else "  ---"
        reason = result.reason_code
        print(
            f"  step {idx:02d}  {allowed}  "
            f"action={action_kind:<13s}  reason={reason}"
        )
    print()
    print("Final assertions:")
    assert runner.frames_observed == 12, runner.frames_observed
    assert len(runner.decisions) == 12, len(runner.decisions)
    assert runner.state in (RunnerState.OBSERVE, RunnerState.ABSTAIN), runner.state
    # Step 12 is the only one that emits a typed MOVE; it must have been allowed.
    assert runner.decisions[-1][0].action.type == "MOVE", runner.decisions[-1]
    assert runner.decisions[-1][1].allowed is True, runner.decisions[-1][1]
    # All other steps are deliberate non-actions (WAIT or ABSTAIN); the policy
    # records them with reason_code=ACCEPTED, allowed=False.
    for i, (decision, result) in enumerate(runner.decisions[:-1], start=1):
        assert decision.action.type in ("WAIT", "ABSTAIN"), (i, decision)
        assert result.allowed is False, (i, result)
        assert result.reason_code == "ACCEPTED", (i, result)
    print("  - frames_observed == 12                  OK")
    print("  - decisions_recorded == 12               OK")
    print("  - final state in {OBSERVE, ABSTAIN}      OK")
    print("  - step 12 was a typed MOVE, allowed      OK")
    print("  - steps 1-11 were WAIT/ABSTAIN (ACCEPTED) OK")
    print()
    print("Smoke loop completed cleanly. No real client was touched.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
