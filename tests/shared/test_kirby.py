"""Super Kirby Clash library (TASK-51): vision, tactics, and the loop on synthetic frames only.

The vision functions draw their thresholds from real fight frames; here we paint synthetic blobs
of the same HSV families on a 1280x720 canvas. No game screenshots in the repo.
"""
import os
import sys
import time

import cv2
import numpy as np
import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))

from shared.src.lib.game.kirby import vision, tactics  # noqa: E402
from shared.src.lib.game.kirby.runner import KirbyRunner, kpi_metadata, summary  # noqa: E402
from shared.src.lib.game.kirby.vision import (  # noqa: E402
    KIRBY_BAR, MATE_BAR, PLATE_BOX, boss_x, hp, in_fight, kirby_x, read,
)


# --- helpers --------------------------------------------------------------------------

def _empty_frame(h=720, w=1280):
    return np.zeros((h, w, 3), dtype=np.uint8)


def _blob(img, x, y, r, color_bgr):
    """Filled circle, used to paint Kirby / boss / clock on the synthetic frame."""
    cv2.circle(img, (int(x), int(y)), int(r), tuple(int(c) for c in color_bgr), thickness=-1, lineType=cv2.LINE_AA)


def _bar(img, x0, x1, end_x, hue=60):
    """HP bar from x0 up to end_x within the HUD strip (hue 60 green, 25 yellow, 2 red)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    g = np.array([hue, 200, 200], dtype=np.uint8)
    for x in range(int(x0), int(min(end_x, x1))):
        hsv[668:680, x] = g
    img[:, :] = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def _clock(img, cx=35, cy=45, r=18, color=(60, 180, 240)):
    """Clock icon: orange normally, grey during banners. The fight detection must not depend on it."""
    cv2.circle(img, (int(cx), int(cy)), int(r), color, thickness=-1, lineType=cv2.LINE_AA)


def _kirby_blob(img, x=400, y=400):
    """Pink/magenta blob in BGR space (H ~ 165 in HSV)."""
    _blob(img, x, y, 40, (180, 60, 255))


def _boss_blob(img, x=900, y=420):
    """Blue/purple blob in BGR space (H ~ 130 in HSV)."""
    # A bigger blob so the boss mask reaches >= 2000 px.
    cv2.ellipse(img, (int(x), int(y)), (90, 110), 0, 0, 360, (200, 60, 90), thickness=-1, lineType=cv2.LINE_AA)
    cv2.ellipse(img, (int(x), int(y) - 30), (60, 40), 0, 0, 360, (200, 80, 110), thickness=-1, lineType=cv2.LINE_AA)


def _plate(img):
    """Kirby's pink HUD plate, drawn under his HP bar."""
    x0, y0, x1, y1 = PLATE_BOX
    img[y0:y1, x0:x1] = (180, 60, 255)
    img[668:680, KIRBY_BAR[0]:KIRBY_BAR[1]] = (0, 0, 0)


def _fight_frame(kirby_x_px=400, boss_x_px=900, kirby_bar_end=300, mate_bar_end=580, with_clock=True,
                 bar_hue=60):
    img = _empty_frame()
    _plate(img)
    _kirby_blob(img, x=kirby_x_px)
    _boss_blob(img, x=boss_x_px)
    _bar(img, *KIRBY_BAR, kirby_bar_end, hue=bar_hue)
    _bar(img, *MATE_BAR, mate_bar_end)
    if with_clock:
        _clock(img)
    return img


# --- vision ---------------------------------------------------------------------------

def test_kirby_x_returns_blob_centre_within_15px():
    img = _fight_frame(kirby_x_px=420)
    got = kirby_x(img)
    assert got is not None
    assert abs(got - 420) <= 15


def test_kirby_x_returns_none_when_below_min_pixels():
    img = _empty_frame()
    # A handful of pink pixels — well below the 150-px floor.
    for x in range(0, 50):
        img[400, x] = (180, 60, 255)
    assert kirby_x(img) is None


def test_boss_x_returns_blob_centre_within_15px():
    img = _fight_frame(boss_x_px=860)
    got = boss_x(img)
    assert got is not None
    assert abs(got - 860) <= 15


def test_boss_x_returns_none_when_below_min_pixels():
    img = _empty_frame()
    # A sparse handful of purple pixels — well below the 2000-px floor.
    for x in range(0, 30):
        img[300, x] = (200, 60, 90)
    assert boss_x(img) is None


def test_hp_fraction_is_within_0_03_of_bar_end():
    img = _fight_frame(kirby_bar_end=300)
    frac = hp(img, *KIRBY_BAR)
    assert frac is not None
    expected = (300 - KIRBY_BAR[0]) / (KIRBY_BAR[1] - KIRBY_BAR[0])
    assert abs(frac - expected) < 0.03


def test_hp_returns_none_when_no_green():
    img = _empty_frame()
    _kirby_blob(img)
    _boss_blob(img)
    assert hp(img, *KIRBY_BAR) is None


def test_in_fight_true_when_hp_bar_present():
    assert in_fight(_fight_frame()) is True


def test_in_fight_true_with_grey_clock_or_no_clock():
    """Banners ("Hornhead is furious!") grey the clock out: still in fight."""
    grey = _fight_frame(with_clock=False)
    _clock(grey, color=(120, 120, 120))
    assert in_fight(grey) is True
    assert in_fight(_fight_frame(with_clock=False)) is True


def test_in_fight_false_on_beige_menu_with_yellow_in_bar_rows():
    """The village floor / menus are beige-orange: they match the yellow HP hue but have no plate."""
    img = _empty_frame()
    img[600:720, :] = (60, 170, 230)
    assert hp(img, *KIRBY_BAR) is not None
    assert in_fight(img) is False


def test_in_fight_false_when_no_hp_bar():
    img = _empty_frame()
    _kirby_blob(img)
    _boss_blob(img)
    _clock(img)
    assert in_fight(img) is False


@pytest.mark.parametrize("hue", [60, 25, 2])   # green, yellow, red
def test_hp_counts_green_yellow_and_red_bars(hue):
    img = _fight_frame(kirby_bar_end=200, bar_hue=hue)
    frac = hp(img, *KIRBY_BAR)
    assert frac is not None
    expected = (200 - KIRBY_BAR[0]) / (KIRBY_BAR[1] - KIRBY_BAR[0])
    assert abs(frac - expected) < 0.03
    assert in_fight(img) is True


def test_read_returns_all_five_keys():
    img = _fight_frame()
    out = read(img)
    assert set(out.keys()) == {"kirby_x", "boss_x", "kirby_hp", "mate_hp", "in_fight"}
    assert out["in_fight"] is True


# --- tactics --------------------------------------------------------------------------

def _obs(kx=400, bx=900, kirby_hp=1.0, mate_hp=1.0, in_fight_=True):
    return {"kirby_x": kx, "boss_x": bx, "kirby_hp": kirby_hp, "mate_hp": mate_hp, "in_fight": in_fight_}


def _valid_command(cmd):
    """Validate a switch controller command string (mirror of what send_command accepts)."""
    if not isinstance(cmd, str) or not cmd:
        return False
    head, _, arg = cmd.partition(":")
    if head == "press":
        return bool(arg)
    if head == "sequence":
        return arg.startswith("[") and arg.endswith("]")
    if head == "stick":
        parts = arg.split(",")
        return len(parts) >= 2
    if head in ("hold", "release", "pair", "status"):
        return True
    return False


@pytest.mark.parametrize("tactic", list(tactics.TACTICS.keys()))
def test_bot_step_returns_valid_switch_actions_near(tactic):
    obs = _obs(kx=500, bx=600)   # dx=100, near
    actions = tactics.bot_step(tactic, obs, None)
    assert actions, tactic
    for a in actions:
        assert a["action_type"] == "switch"
        assert _valid_command(a["command"])


@pytest.mark.parametrize("tactic", list(tactics.TACTICS.keys()))
def test_bot_step_returns_valid_switch_actions_far(tactic):
    obs = _obs(kx=200, bx=900)   # dx=700, far
    actions = tactics.bot_step(tactic, obs, None)
    assert actions, tactic
    for a in actions:
        assert a["action_type"] == "switch"
        assert _valid_command(a["command"])


def test_bot_step_falls_back_when_no_xs():
    actions = tactics.bot_step("rush", _obs(kx=None, bx=None), None)
    assert actions and actions[0]["command"].startswith("press:")


def test_bot_step_charged_uses_hold_and_release():
    actions = tactics.bot_step("charged", _obs(kx=500, bx=600), None)
    commands = [a["command"] for a in actions]
    assert any(c.startswith("hold:") for c in commands)
    assert "release" in commands


def test_bot_step_guard_counter_includes_a_release_with_pre_wait():
    actions = tactics.bot_step("guard_counter", _obs(kx=500, bx=600), None)
    releases = [a for a in actions if a["command"] == "release"]
    assert releases and any(r.get("pre_wait_ms") for r in releases)


@pytest.mark.parametrize("tactic", list(tactics.TACTICS.keys()))
def test_safety_rule_overrides_every_tactic(tactic):
    actions = tactics.bot_step(tactic, _obs(kx=500, bx=700, kirby_hp=0.2), None)   # boss on the right, 200 px
    assert [a["command"] for a in actions] == ["stick:left,left,300", "press:r"]
    assert actions[1]["params"]["hold_ms"] == 300
    assert "safety retreat active" in tactics.state_text(
        _obs(kx=500, bx=700, kirby_hp=0.2), [], tactic, 0.0, time.time())


def test_safety_rule_off_when_healthy_or_far():
    assert tactics.bot_step("rush", _obs(kx=500, bx=650, kirby_hp=0.5), None)[0]["command"].startswith("sequence")
    far = tactics.bot_step("rush", _obs(kx=100, bx=900, kirby_hp=0.2), None)
    assert far[0]["command"] == "stick:left,right,200"
    assert "safety retreat" not in tactics.state_text(_obs(kx=100, bx=900, kirby_hp=0.2), [], "rush", 0.0, time.time())


def test_state_text_mentions_hp_and_distance():
    obs = _obs(kx=300, bx=800)
    text = tactics.state_text(obs, [], "rush", 0.0, time.time())
    assert "Kirby HP" in text
    assert "Distance" in text
    assert "500 px" in text


def test_fixed_choose_returns_rush():
    res = tactics.fixed_choose("anything", [{"id": "rush", "facts": "x"}], "y")
    assert res["choice"] == "rush"


# --- runner ---------------------------------------------------------------------------

class _FakeIO:
    """A scripted IO the runner drives end-to-end with no device in the way."""

    def __init__(self, frames, steps_per_frame=1):
        self.frames = list(frames)
        self.idx = 0
        self.actions = []
        self.evidence_calls = []
        self.steps_per_frame = steps_per_frame

    def frame(self):
        if self.idx >= len(self.frames):
            return None
        path = self.frames[self.idx]
        # Advance by one frame every N runner ticks to mimic ~5 fps capture.
        if self.idx < len(self.frames) - 1 and (self.steps_per_frame > 0):
            pass
        self.idx += 1
        return path

    def run_actions(self, actions):
        self.actions.extend(actions)
        return {"success": True}

    def evidence(self, name):
        self.evidence_calls.append(name)
        return ""


class _Ctx:
    team_id = "t"
    screenshot_paths = []

    def __init__(self):
        self.step_results = []

    def record_step_immediately(self, step):
        self.step_results.append(step)


_frame_seq = iter(range(10**9))


def _save_frame(tmp_path, img):
    path = os.path.join(tmp_path, f"frame_{next(_frame_seq)}.jpg")
    cv2.imwrite(path, img)
    return path


def test_runner_without_chooser_acts_every_frame(tmp_path):
    frames = [_save_frame(tmp_path, _fight_frame()) for _ in range(40)] + \
        [_save_frame(tmp_path, _empty_frame()) for _ in range(25)]
    io = _FakeIO(frames)
    data = KirbyRunner(io, _Ctx(), choose=None, max_duration=10).run()

    assert data["end_reason"] == "fight_over"
    assert data["chooser"] == "fixed"
    assert data["actions_sent"] >= 40
    assert data["frames"] == 65
    for a in io.actions:
        assert _valid_command(a["command"])
    assert io.actions[-1]["command"] == "release"   # no button left held
    assert "pre_wait_ms" not in str(io.actions)


def test_every_recorded_step_has_a_screenshot(tmp_path, monkeypatch):
    """The report mosaic shows one tile per step: a step without a screenshot is a missing tile."""
    from shared.src.lib.game.kirby import runner as runner_mod
    monkeypatch.setattr(runner_mod, "REPORT_EVERY_S", 0.0)   # a window step on every frame
    frames = [_save_frame(tmp_path, _fight_frame()) for _ in range(5)] + \
        [_save_frame(tmp_path, _empty_frame()) for _ in range(25)]
    io = _FakeIO(frames)
    io.evidence = lambda name: f"/shots/{name}.jpg"
    ctx = _Ctx()
    KirbyRunner(io, ctx, choose=None, max_duration=10).run()
    assert len(ctx.step_results) >= 3
    assert all(step["screenshot_path"] for step in ctx.step_results)


def test_fight_windows_carry_several_screenshots(tmp_path, monkeypatch):
    """Like kpi_measurement: a fight window step holds every screenshot taken during it."""
    from shared.src.lib.game.kirby import runner as runner_mod
    monkeypatch.setattr(runner_mod, "SHOT_EVERY_S", 0.0)    # a screenshot every frame
    monkeypatch.setattr(runner_mod, "REPORT_EVERY_S", 10**6)
    frames = [_save_frame(tmp_path, _fight_frame()) for _ in range(6)] + \
        [_save_frame(tmp_path, _empty_frame()) for _ in range(25)]
    io = _FakeIO(frames)
    io.evidence = lambda name: f"/shots/{name}.jpg"
    ctx = _Ctx()
    runner_mod.REPORT_EVERY_S = 10**6
    KirbyRunner(io, ctx, choose=None, max_duration=10).run()
    fight_shots = sum(len(s["action_screenshots"]) for s in ctx.step_results)
    assert fight_shots >= 6
    assert all(len(s["actions"]) == len(s["action_screenshots"]) for s in ctx.step_results)


def test_runner_switches_tactic_without_blocking(tmp_path):
    """A slow chooser must not stop the bot: it keeps acting while Jev sleeps, then switches."""
    frames = [_save_frame(tmp_path, _fight_frame()) for _ in range(60)] + \
        [_save_frame(tmp_path, _empty_frame()) for _ in range(25)]
    io = _FakeIO(frames)
    calls = []

    def choose(state_text_, options, instructions):
        calls.append(state_text_)
        time.sleep(0.3)
        return {"choice": "retreat", "confidence": 0.9, "probabilities": {"retreat": 0.9},
                "cost": 0.001, "ms": 300, "decision_id": "d-1",
                "usage": {"input_tokens": 470, "output_tokens": 3}}

    outcomes = []
    t0 = time.time()
    runner = KirbyRunner(io, _Ctx(), choose=choose, max_duration=15)
    data = runner.run(outcome_writer=lambda ids, outcome: outcomes.append((ids, outcome)))

    assert data["end_reason"] == "fight_over"
    assert len(calls) >= 1
    assert data["decisions"] >= 1
    assert data["tactics"]["rush"] > 5 and data["tactics"]["retreat"] >= 1
    assert data["jev_cost_usd"] > 0
    assert data["jev_input_tokens"] == 470 * data["decisions"]
    assert data["jev_output_tokens"] == 3 * data["decisions"]
    assert {"jev_input_tokens", "jev_output_tokens"} <= set(kpi_metadata(data))
    assert "470" in summary({**data, "jev_input_tokens": 470}, True)
    assert outcomes and outcomes[0][0] == ["d-1"] and "kirby_hp_lost" in outcomes[0][1]
    assert time.time() - t0 < 6


def test_runner_batches_one_call_per_frame_and_honours_pre_wait(tmp_path):
    runner = KirbyRunner(_FakeIO([]), _Ctx(), choose=None)
    io = runner.io
    batches = []
    io.run_actions = lambda batch: batches.append([a["command"] for a in batch])
    runner._send_actions(tactics.bot_step("guard_counter", _obs(kx=500, bx=600), None))
    assert batches == [["hold:r"], ["release", "sequence:[right,b,b]"]]
    batches.clear()
    runner._send_actions(tactics.bot_step("rush", _obs(kx=500, bx=600), None))
    assert len(batches) == 1


def test_runner_does_not_press_buttons_off_fight(tmp_path):
    frames = [_save_frame(tmp_path, _fight_frame()) for _ in range(3)] + \
        [_save_frame(tmp_path, _empty_frame()) for _ in range(25)]
    io = _FakeIO(frames)
    KirbyRunner(io, _Ctx(), choose=None, max_duration=10).run()
    assert len(io.actions) == 3 + 1   # three fight frames, then the final release


def test_runner_survives_a_few_blank_frames_mid_fight(tmp_path):
    frames = [_save_frame(tmp_path, _fight_frame()) for _ in range(5)] + \
        [_save_frame(tmp_path, _empty_frame()) for _ in range(10)] + \
        [_save_frame(tmp_path, _fight_frame()) for _ in range(5)] + \
        [_save_frame(tmp_path, _empty_frame()) for _ in range(25)]
    data = KirbyRunner(_FakeIO(frames), _Ctx(), choose=None, max_duration=10).run()
    assert data["end_reason"] == "fight_over"
    assert data["frames"] == 45


def test_runner_ends_with_no_fight_when_first_frames_blank(tmp_path, monkeypatch):
    from shared.src.lib.game.kirby import runner as runner_mod
    monkeypatch.setattr(runner_mod, "NO_FIGHT_TIMEOUT_S", 0.3)
    frames = [_save_frame(tmp_path, _empty_frame()) for _ in range(30)]
    data = KirbyRunner(_FakeIO(frames), _Ctx(), choose=None, max_duration=30).run()
    assert data["end_reason"] == "no_fight"
