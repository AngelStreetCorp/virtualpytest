"""Flappy Bird showcase library (TASK-33 phase 3c): the plan script, the lookahead and the runner's
flow against a scripted page. The physics plan itself runs in the browser; it is exercised by
test_scripts/game/local/flappy_vpt_local.py. No browser, no device.

Run: pytest tests/shared/test_flappy.py -v
"""
import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))

from shared.src.lib.game.flappy.runner import FlappyRunner, lookahead_frames, plan_script  # noqa: E402
from shared.src.lib.game.flappy.ui import build_manifest  # noqa: E402


def test_plan_script_carries_the_runner_settings():
    js = plan_script(7, 5)
    assert "const margin = 7, lookahead = 5;" in js
    assert "__" not in js.replace("__vpt", "")  # every placeholder filled
    assert js.startswith("() => {")


def test_lookahead_covers_the_loop():
    assert lookahead_frames(0) == 3          # at least one frame, plus two
    assert lookahead_frames(33.3) == 4       # ~2 frames of loop
    assert lookahead_frames(55) == 5


def test_tree_has_entry_start_and_game_over():
    tree = build_manifest("http://example/")["trees"][0]
    ids = {n["node_id"] for n in tree["nodes"]}
    assert {"entry-node", "game", "start", "game_over"} <= ids
    start = next(e for e in tree["edges"] if e["target_node_id"] == "start")
    assert [a["command"] for a in start["action_sets"][0]["actions"]] == ["navigate_to_url", "press_key"]


class _IO:
    """A page that flies `pipes` pipes, one per 5 steps, then dies (state 2)."""

    def __init__(self, die_at):
        self.die_at, self.steps, self.scripts = die_at, 0, []

    def navigate(self, target):
        return {"success": True}

    def run_actions(self, actions):
        self.steps += 1
        self.scripts.append(actions[0]["params"]["script"])
        score = self.steps // 5
        state = 2 if score >= self.die_at else 1
        result = {"state": state, "score": min(score, self.die_at), "v": 1.0, "top": 300, "bottom": 330,
                  "pipe": {"top": 250, "bottom": 340}, "planned": 2, "jumps": self.steps // 3}
        return {"success": True, "results": [{"output_data": {"result": result}}]}

    def evidence(self, name):
        return ""


class _Ctx:
    team_id = "t"

    def __init__(self):
        self.step_results = []

    def record_step_immediately(self, step):
        self.step_results.append(step)


def test_runner_stops_at_the_pipe_budget():
    io, ctx = _IO(die_at=1000), _Ctx()
    data = FlappyRunner(io, ctx, max_pipes=25, max_duration=60, min_pipes=10).run()
    assert data["stop_reason"] == "pipe_limit" and data["success"] and data["pipes"] == 25
    assert sum(1 for s in ctx.step_results if s["message"].startswith("Pipes ")) == 2
    assert "lookahead = " in io.scripts[-1]


def test_runner_judges_a_death_by_the_pipe_floor():
    data = FlappyRunner(_IO(die_at=12), _Ctx(), max_pipes=100, max_duration=60, min_pipes=10).run()
    assert data["stop_reason"] == "died" and data["pipes"] == 12 and data["success"]
    data = FlappyRunner(_IO(die_at=4), _Ctx(), max_pipes=100, max_duration=60, min_pipes=10).run()
    assert data["stop_reason"] == "died" and not data["success"] and "4 pipes < 10" in data["error"]
    assert data["last_readings"]
