"""LlmAgent = ScanAgent + a text-only waypoint planner. Gateway monkeypatched."""
import numpy as np

from shared.src.lib.drone.agents import LlmAgent, ScanAgent
from shared.src.lib.drone.perception import Detection
from shared.src.lib.drone.roommap import RoomMap
from shared.src.lib.drone.safety import SafetyLimits
from shared.src.lib.drone.sim.world import Pose, default_room

LIM = SafetyLimits(room_map=RoomMap.from_sim_room(default_room()))
FRAME = np.zeros((720, 960, 3), np.uint8)
POSE = Pose(100, 100, 80, 0)


class NoSight:
    name = "fake"

    def __init__(self, costly=False):
        self.costly = costly
        self.calls = 0
        self.last_note = "a wall"

    def detect(self, frame, target):
        self.calls += 1
        return None


def make(monkeypatch, answers, perception=None):
    from shared.src.lib.ai import gateway
    prompts = []

    def fake(usage, prompt, **kw):
        assert "image_b64" not in kw  # text only
        prompts.append((usage, prompt))
        a = answers.pop(0)
        return a if isinstance(a, dict) else {"success": True, "content": a,
                                              "usage": {"prompt_tokens": 400, "completion_tokens": 20},
                                              "model": "m1", "provider_used": "p1"}

    monkeypatch.setattr(gateway, "complete", fake)
    agent = LlmAgent(LIM, ScanAgent(perception or NoSight(), LIM), usage="vision")
    agent.start("sofa")
    return agent, prompts


def finish_scan(agent):
    """Feed frames until the first waypoint decision; returns that Decision."""
    for _ in range(40):
        d = agent.decide(FRAME, POSE)
        if "LLM" in d.note or "nearest" in d.note or d.note.startswith("to waypoint"):
            return d
    raise AssertionError("no waypoint decision")


def test_valid_answer_picks_that_waypoint_and_reports_reason_and_tokens(monkeypatch):
    agent, prompts = make(monkeypatch, ['{"waypoint_id": 3, "reason": "sofas stand against a wall"}'])
    agent.scan.visited.append((POSE.x, POSE.y))  # the start spot counts as searched when the choice is made
    cands = agent.scan._candidates(POSE)
    d = finish_scan(agent)
    want = cands[3][0]
    assert agent.scan.waypoint == want
    assert "LLM picks waypoint 3" in d.note and "sofas stand against a wall" in d.note
    assert (d.ai_calls, d.tokens_in, d.tokens_out) == (1, 400, 20)
    assert (agent.ai_calls, agent.tokens_in, agent.fallbacks) == (1, 400, 0)
    assert agent.models == {"p1/m1"}
    usage, prompt = prompts[0]
    assert usage == "vision" and "sofa" in prompt and "shelf" in prompt and "route=" in prompt
    assert "near:" in prompt and "x=100 y=100" in prompt


def test_invalid_id_falls_back_to_nearest(monkeypatch):
    agent, _ = make(monkeypatch, ['{"waypoint_id": 99, "reason": "x"}'])
    agent.scan.visited.append((POSE.x, POSE.y))
    nearest = agent.scan._candidates(POSE)[0][0]
    d = finish_scan(agent)
    assert agent.scan.waypoint == nearest and "failed" in d.note
    assert agent.fallbacks == 1 and agent.ai_calls == 1


def test_gateway_failure_falls_back_to_nearest(monkeypatch):
    agent, _ = make(monkeypatch, [{"success": False, "content": "", "error": "no usable AI profile", "usage": {}}])
    agent.scan.visited.append((POSE.x, POSE.y))
    nearest = agent.scan._candidates(POSE)[0][0]
    d = finish_scan(agent)
    assert agent.scan.waypoint == nearest and "no usable AI profile" in d.note and agent.fallbacks == 1


def test_garbage_answer_falls_back(monkeypatch):
    agent, _ = make(monkeypatch, ["I think the left one"])
    finish_scan(agent)
    assert agent.fallbacks == 1


def test_prompt_lists_what_the_last_scan_saw_and_visited_waypoints(monkeypatch):
    per = NoSight(costly=True)
    agent, prompts = make(monkeypatch, ['{"waypoint_id": 0, "reason": "near"}'], per)
    finish_scan(agent)
    assert "0: a wall" in prompts[0][1]  # heading: note from the vision model during the scan
    assert "Already searched" in prompts[0][1]


def test_claim_still_comes_from_the_scan_agent(monkeypatch):
    class Sees(NoSight):
        def detect(self, frame, target):
            return Detection(target, 0.9, (400, 300, 100, 100), "fake")

    agent, prompts = make(monkeypatch, [], Sees())
    assert agent.decide(FRAME, POSE).action == "claim" and not prompts


def test_paid_detector_only_looks_at_scan_frames():
    per = NoSight(costly=True)
    a = ScanAgent(per, LIM)
    a.start("sofa")
    for _ in range(a.spin_steps):  # the scan at the start: every frame is looked at
        a.decide(FRAME, POSE)
    assert per.calls == a.spin_steps
    a.waypoint, a.spins_left = (300.0, 100.0), 0
    a.nav.set_goal(POSE, a.waypoint)
    before = per.calls
    d = a.decide(FRAME, POSE)  # travelling: no call
    assert per.calls == before and d.action.startswith(("cw", "ccw", "forward"))


def test_hider_target_text(monkeypatch):
    agent, prompts = make(monkeypatch, ['{"waypoint_id": 0, "reason": "r"}'])
    agent.start("2")
    finish_scan(agent)
    assert "marker id 2" in prompts[0][1] and "behind tall furniture" in prompts[0][1]
