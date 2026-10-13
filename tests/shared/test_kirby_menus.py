"""Super Kirby Clash menu driver (TASK-51): classify branches, MenuDriver state machine, script loop.

No game screenshots in the repo: every test paints synthetic frames and monkeypatches
``menus._ocr`` so the OCR strings are deterministic. ``vision.in_fight`` is monkeypatched
when a test needs ``classify`` to ignore the synthetic plate.
"""
import importlib
import os
import sys

import cv2
import numpy as np
import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))

from shared.src.lib.game.kirby import menus, vision  # noqa: E402
from shared.src.lib.game.kirby.menus import (  # noqa: E402
    MenuDriver, banner_text, classify, dialog_box, quests_bubble, region_text,
)


# --- helpers -------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_input_lag_wait(monkeypatch):
    """Scripted frames are instant: no lag window unless a test sets REACT_S itself."""
    monkeypatch.setattr(menus, "REACT_S", 0)


def _empty(h=720, w=1280):
    return np.zeros((h, w, 3), dtype=np.uint8)


def _lit_frame(bgr=(60, 60, 60), h=720, w=1280):
    """A non-black frame that still does not match Kirby's pink plate."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = bgr
    return img


def _fill(img, x0, y0, x1, y1, bgr):
    img[y0:y1, x0:x1] = bgr


def _fight_frame():
    """A frame where vision.in_fight returns True."""
    img = _empty()
    x0, y0, x1, y1 = vision.PLATE_BOX
    img[y0:y1, x0:x1] = (180, 60, 255)   # pink plate
    return img


# --- banner_text / region_text / dialog_box / quests_bubble shape -------------

def test_banner_text_returns_empty_when_no_banner(monkeypatch):
    monkeypatch.setattr(menus, "_ocr", lambda img, psm: "")
    assert banner_text(_empty()) == ""


def test_region_text_is_lowercased_and_collapsed(monkeypatch):
    seen = []
    monkeypatch.setattr(menus, "_ocr", lambda img, psm: seen.append((img.shape, psm)) or "  Vigor  is   on screen  ")
    assert region_text(_lit_frame(), "vigor") == "vigor is on screen"
    (x0, y0, x1, y1), psm = menus.REGIONS["vigor"]
    assert seen == [(((y1 - y0) * 2, (x1 - x0) * 2), psm)]   # grey crop, x2


def test_dialog_box_detects_the_beige_box():
    img = _lit_frame()
    _fill(img, 0, 575, 1280, 700, (150, 215, 235))   # beige (BGR): H~22, S~92, V~235
    assert dialog_box(img) is True
    assert dialog_box(_lit_frame()) is False


def test_quests_bubble_false_when_no_components(monkeypatch):
    monkeypatch.setattr(menus, "_ocr", lambda img, psm: "")
    assert quests_bubble(_empty()) is False


def test_quests_bubble_true_when_text_contains_quest(monkeypatch):
    img = _empty()
    # A near-white component in rows 100..420 with the right size.
    _fill(img, 100, 200, 280, 280, (240, 230, 230))   # width 180, height 80
    monkeypatch.setattr(menus, "_ocr", lambda img, psm: "GO Quests,")
    assert quests_bubble(img) is True


def test_quests_bubble_false_when_text_is_talk_only(monkeypatch):
    img = _empty()
    _fill(img, 100, 200, 280, 280, (240, 230, 230))
    monkeypatch.setattr(menus, "_ocr", lambda img, psm: "Talk")
    assert quests_bubble(img) is False


def test_quests_bubble_false_when_component_too_small(monkeypatch):
    img = _empty()
    _fill(img, 100, 200, 130, 280, (240, 230, 230))   # width 30 — below 100
    monkeypatch.setattr(menus, "_ocr", lambda img, psm: "GO Quests,")
    assert quests_bubble(img) is False


# --- classify ------------------------------------------------------------------

def test_classify_fight_short_circuits_everything(monkeypatch):
    monkeypatch.setattr(vision, "in_fight", lambda img: True)
    # the Vigor bar would otherwise yield "village"; in_fight wins.
    monkeypatch.setattr(menus, "region_text", lambda img, name: {"vigor": "vigor"}.get(name, ""))
    monkeypatch.setattr(menus, "banner_text", lambda img: "")
    monkeypatch.setattr(menus, "quests_bubble", lambda img: False)
    assert classify(_lit_frame()) == "fight"


def test_classify_black_when_mean_v_low():
    assert classify(_empty()) == "black"


@pytest.mark.parametrize("expected,banner", [
    ("form_team", "Form a Team"),
    ("game_mode", "Game Mode"),
    ("select_area", "Select Area"),
    ("select_quest", "Select Quest"),
    ("change_role", "Change Role"),
    ("change_role", "Get Ready!"),
    ("shop", "Shoppe"),
    ("shop", "Weapons"),
    ("shop", "Armor"),
    ("shop", "Support"),
    ("shop", "Stickers"),
    ("shop", "Gem Apples"),
])
def test_classify_each_banner(monkeypatch, expected, banner):
    monkeypatch.setattr(menus, "banner_text", lambda img: banner)
    assert classify(_lit_frame()) == expected


def test_classify_confirm_setoff(monkeypatch):
    monkeypatch.setattr(menus, "banner_text", lambda img: "")
    monkeypatch.setattr(menus, "region_text", lambda img, name: {"confirm": "are you ready to set off on your quest?"}.get(name, ""))
    monkeypatch.setattr(menus, "quests_bubble", lambda img: False)
    assert classify(_lit_frame()) == "confirm_setoff"


def test_classify_quest_choice(monkeypatch):
    monkeypatch.setattr(menus, "banner_text", lambda img: "")
    monkeypatch.setattr(menus, "region_text", lambda img, name: {"choice": "play a different quest play the same quest to the village"}.get(name, ""))
    monkeypatch.setattr(menus, "quests_bubble", lambda img: False)
    assert classify(_lit_frame()) == "quest_choice"


def test_classify_village_at_board(monkeypatch):
    monkeypatch.setattr(menus, "banner_text", lambda img: "")
    monkeypatch.setattr(menus, "dialog_box", lambda img: False)
    monkeypatch.setattr(menus, "region_text", lambda img, name: {"vigor": "vigor, mf"}.get(name, ""))
    monkeypatch.setattr(menus, "quests_bubble", lambda img: True)
    assert classify(_lit_frame()) == "village_at_board"


def test_classify_village_when_vigor_only(monkeypatch):
    monkeypatch.setattr(menus, "banner_text", lambda img: "")
    monkeypatch.setattr(menus, "dialog_box", lambda img: False)
    monkeypatch.setattr(menus, "region_text", lambda img, name: {"vigor": "igor al"}.get(name, ""))
    monkeypatch.setattr(menus, "quests_bubble", lambda img: False)
    assert classify(_lit_frame()) == "village"


def test_classify_dialog_fallback(monkeypatch):
    monkeypatch.setattr(menus, "banner_text", lambda img: "")
    monkeypatch.setattr(menus, "region_text", lambda img, name: {}.get(name, ""))
    monkeypatch.setattr(menus, "quests_bubble", lambda img: False)
    assert classify(_lit_frame()) == "dialog"


def test_classify_village_story_dialog_is_dialog(monkeypatch):
    """A story dialog in the village shows the Vigor bar too: the beige box makes it a dialog."""
    monkeypatch.setattr(menus, "banner_text", lambda img: "")
    monkeypatch.setattr(menus, "dialog_box", lambda img: True)
    monkeypatch.setattr(menus, "quests_bubble", lambda img: True)
    monkeypatch.setattr(menus, "region_text", lambda img, name: {"vigor": "e vigor"}.get(name, ""))
    assert classify(_lit_frame()) == "dialog"


def _setoff_frame(lit=True):
    img = _lit_frame()
    x0, y0, x1, y1 = menus.SETOFF_BOX
    img[y0:y1, x0:x1] = (30, 30, 230) if lit else (40, 70, 120)   # bright red vs brown
    return img


def test_form_team_presses_a_only_when_set_off_is_highlighted():
    driver = MenuDriver(io=None, max_steps=10, log=lambda *a, **k: None, settle_s=0)
    assert [a["command"] for a in driver._step_actions("form_team", _setoff_frame(True))] == ["press:a"]
    assert [a["command"] for a in driver._step_actions("form_team", _setoff_frame(False))] == ["press:down"]


def test_select_quest_steps_up_until_the_card_names_hornhead(monkeypatch):
    driver = MenuDriver(io=None, max_steps=10, log=lambda *a, **k: None, settle_s=0)
    monkeypatch.setattr(menus, "region_text", lambda img, name: "taine) doo" if name == "quest_card" else "")
    assert [a["command"] for a in driver._step_actions("select_quest", _lit_frame())] == ["press:up"]
    monkeypatch.setattr(menus, "region_text", lambda img, name: "hornheadpeanss" if name == "quest_card" else "")
    assert [a["command"] for a in driver._step_actions("select_quest", _lit_frame())] == ["press:a"]


def test_change_role_backs_out():
    driver = MenuDriver(io=None, max_steps=10, log=lambda *a, **k: None, settle_s=0)
    assert [a["command"] for a in driver._step_actions("change_role")] == ["press:b"]


def test_shop_never_emits_press_a():
    """The shop class must never feed press:a to the controller (Gem Apples purchase risk)."""
    img = _empty()
    driver = MenuDriver(io=None, max_steps=10, log=lambda *a, **k: None, settle_s=0)
    cmds = [a["command"] for a in driver._step_actions("shop")]
    assert cmds == ["press:b"]


# --- MenuDriver state machine --------------------------------------------------

class _ScriptedIO:
    """Frames returned in order; ``frame()`` advances one step per call."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.idx = 0
        self.actions = []

    def frame(self):
        if self.idx >= len(self.frames):
            return None
        path = self.frames[self.idx]
        self.idx += 1
        return path

    def run_actions(self, actions):
        self.actions.extend(actions)
        return {"success": True}

    def evidence(self, name):
        return ""


def _save(tmp_path, img, tag):
    path = os.path.join(tmp_path, f"{tag}.jpg")
    cv2.imwrite(path, img)
    return path


def test_menu_driver_full_path_village_to_fight(tmp_path, monkeypatch):
    """End-to-end: village ×3 → village_at_board → game_mode → select_area → select_quest
    → form_team → confirm_setoff → dialog → fight."""

    monkeypatch.setattr("time.sleep", lambda s: None)   # tests run fast

    seq = [
        _save(tmp_path, _empty(), "v1"),    # village
        _save(tmp_path, _empty(), "v2"),    # village
        _save(tmp_path, _empty(), "v3"),    # village
        _save(tmp_path, _empty(), "vab"),   # village_at_board
        _save(tmp_path, _empty(), "gm"),    # game_mode
        _save(tmp_path, _empty(), "sa"),    # select_area
        _save(tmp_path, _empty(), "sq"),    # select_quest
        _save(tmp_path, _empty(), "ft"),    # form_team
        _save(tmp_path, _empty(), "cs"),    # confirm_setoff
        _save(tmp_path, _empty(), "dl"),    # dialog
        _save(tmp_path, _fight_frame(), "fight"),
    ]

    classes = [
        "village", "village", "village", "village_at_board", "game_mode", "select_area",
        "select_quest", "form_team", "confirm_setoff", "dialog", "fight",
    ]
    state = {"i": 0}

    def fake_classify(img, cache=None):
        idx = state["i"]
        state["i"] += 1
        return classes[idx]

    monkeypatch.setattr(menus, "classify", fake_classify)

    io = _ScriptedIO(seq)
    driver = MenuDriver(io, max_steps=40, log=lambda *a, **k: None, settle_s=0)
    report = driver.to_fight()

    assert report["reached"] is True
    assert report["steps"] == 11
    assert report["error"] is None
    assert report["screens"][-1] == "fight"
    assert "village" in report["screens"]
    assert "village_at_board" in report["screens"]
    assert "form_team" in report["screens"]

    cmds = [a["command"] for a in io.actions]
    # Village: first step is stick:left,left,2000; further steps stick:left,right,250.
    assert cmds[0] == "stick:left,left,2000"
    assert cmds[1] == "stick:left,right,250"
    assert cmds[2] == "stick:left,right,250"
    # village_at_board → press:up
    assert cmds[3] == "press:up"
    # game_mode → press:a
    assert cmds[4] == "press:a"
    # select_area → press:left, press:left, press:a
    assert cmds[5:8] == ["press:left", "press:left", "press:a"]
    # select_quest, card not Hornhead (blank OCR) → press:up
    assert cmds[8] == "press:up"
    # form_team, Set Off not highlighted (blank frame) → press:down only
    assert cmds[9] == "press:down"
    # confirm_setoff → press:a
    assert cmds[10] == "press:a"
    # dialog after confirm_setoff (not a menu screen) → press:a
    assert cmds[11] == "press:a"


def test_menu_driver_quest_choice_path(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    seq = [_save(tmp_path, _empty(), f"qc{i}") for i in range(3)] + \
          [_save(tmp_path, _fight_frame(), "fight")]
    classes = ["quest_choice", "quest_choice", "quest_choice", "fight"]
    state = {"i": 0}

    def fake_classify(img, cache=None):
        idx = state["i"]
        state["i"] += 1
        return classes[idx]

    monkeypatch.setattr(menus, "classify", fake_classify)

    io = _ScriptedIO(seq)
    driver = MenuDriver(io, max_steps=10, log=lambda *a, **k: None, settle_s=0)
    report = driver.to_fight()

    assert report["reached"] is True
    cmds = [a["command"] for a in io.actions]
    assert cmds == ["press:down", "press:a", "press:down", "press:a", "press:down", "press:a"]


def test_menu_driver_presses_b_after_stuck_repeats(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    seq = [_save(tmp_path, _empty(), f"d{i}") for i in range(11)] + \
          [_save(tmp_path, _fight_frame(), "fight")]
    # 8 dialogs to trigger stuck; on the 9th same_class, the driver sends press:b instead
    # of press:a. The sequence then sees 2 more dialogs, then fight.
    classes = ["dialog"] * 8 + ["dialog", "dialog", "dialog", "fight"]
    state = {"i": 0}

    def fake_classify(img, cache=None):
        idx = state["i"]
        state["i"] += 1
        return classes[idx]

    monkeypatch.setattr(menus, "classify", fake_classify)

    io = _ScriptedIO(seq)
    driver = MenuDriver(io, max_steps=20, log=lambda *a, **k: None, settle_s=0)
    report = driver.to_fight()

    assert report["reached"] is True
    cmds = [a["command"] for a in io.actions]
    # 8 dialogs → 8×press:a, then the 9th same-class step presses b (not a), then the
    # remaining 2 dialogs each yield press:a, then the fight frame stops the loop.
    assert cmds[:7] == ["press:a"] * 7
    assert cmds[7] == "press:b"
    assert cmds[8:] == ["press:a"] * 3


def test_menu_driver_max_steps_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    seq = [_save(tmp_path, _empty(), f"v{i}") for i in range(5)]
    state = {"i": 0}

    def fake_classify(img, cache=None):
        state["i"] += 1
        return "dialog"

    monkeypatch.setattr(menus, "classify", fake_classify)

    io = _ScriptedIO(seq)
    driver = MenuDriver(io, max_steps=5, log=lambda *a, **k: None, settle_s=0)
    report = driver.to_fight()

    assert report["reached"] is False
    assert report["error"] == "menu: max steps"
    assert report["steps"] == 5


def test_menu_driver_village_sweep_restart_and_give_up(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    seq = [_save(tmp_path, _empty(), f"v{i}") for i in range(80)]
    monkeypatch.setattr(menus, "classify", lambda img, cache=None: "village")

    io = _ScriptedIO(seq)
    driver = MenuDriver(io, max_steps=80, log=lambda *a, **k: None, settle_s=0)
    report = driver.to_fight()

    assert report["reached"] is False
    assert report["error"] == "quest board not found"
    cmds = [a["command"] for a in io.actions]
    walk, right = "stick:left,left,2000", "stick:left,right,250"
    # two sweeps: left-edge walk + 20 rights each, then give up
    assert cmds == ([walk] + [right] * 20) * 2


def test_menu_driver_skips_already_used_frame(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    a = _save(tmp_path, _empty(), "a")
    b = _save(tmp_path, _fight_frame(), "b")
    # the capture lags: the same path is returned twice after the action
    io = _ScriptedIO([a, a, a, b])
    monkeypatch.setattr(menus, "classify", lambda img, cache=None: "dialog" if img.max() == 0 else "fight")
    report = MenuDriver(io, max_steps=10, log=lambda *a, **k: None, settle_s=0).to_fight()
    assert report["reached"] is True
    assert [x["command"] for x in io.actions] == ["press:a"]   # acted once, not three times


def test_classify_ocr_budget(monkeypatch):
    calls = []
    monkeypatch.setattr(menus, "_ocr", lambda img, psm: calls.append(psm) or "")
    # fight and black frames: no OCR at all
    assert classify(_fight_frame()) == "fight"
    assert classify(_empty()) == "black"
    assert calls == []
    # a plain lit frame: banner + confirm + choice + vigor crops, never a full-frame pass
    assert classify(_lit_frame()) == "dialog"
    assert len(calls) == 4
    assert 11 not in calls


def test_dialog_right_after_a_menu_screen_waits_one_frame(tmp_path, monkeypatch):
    """Change Role -> B -> the next frame is mid-transition ("dialog"): no A, or it reopens Change Role."""
    monkeypatch.setattr("time.sleep", lambda s: None)
    seq = [_save(tmp_path, _empty(), f"m{i}") for i in range(4)] + [_save(tmp_path, _fight_frame(), "f")]
    classes = iter(["change_role", "dialog", "dialog", "dialog", "fight"])
    monkeypatch.setattr(menus, "classify", lambda img, cache=None: next(classes))
    io = _ScriptedIO(seq)
    MenuDriver(io, max_steps=10, log=lambda *a, **k: None, settle_s=0).to_fight()
    assert [a["command"] for a in io.actions] == ["press:b", "press:a", "press:a"]


def test_same_screen_right_after_acting_is_input_lag_not_a_retry(tmp_path, monkeypatch):
    """Change Role -> B, then two lagging Change Role frames: one B only (a second B would leave
    Form a Team for Select Quest)."""
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(menus, "REACT_S", 3.0)
    seq = [_save(tmp_path, _empty(), f"c{i}") for i in range(3)] + [_save(tmp_path, _fight_frame(), "f")]
    classes = iter(["change_role", "change_role", "change_role", "fight"])
    monkeypatch.setattr(menus, "classify", lambda img, cache=None: next(classes))
    io = _ScriptedIO(seq)
    MenuDriver(io, max_steps=10, log=lambda *a, **k: None, settle_s=0).to_fight()
    assert [a["command"] for a in io.actions] == ["press:b"]


def test_menu_trail_has_one_screenshot_per_screen_change(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    seq = [_save(tmp_path, _empty(), f"t{i}") for i in range(4)] + [_save(tmp_path, _fight_frame(), "f")]
    classes = iter(["game_mode", "game_mode", "select_area", "dialog", "fight"])
    monkeypatch.setattr(menus, "classify", lambda img, cache=None: next(classes))
    io = _ScriptedIO(seq)
    io.evidence = lambda name: f"/shots/{name}.jpg"
    report = MenuDriver(io, max_steps=10, log=lambda *a, **k: None, settle_s=0).to_fight()
    assert [x["label"] for x in report["shots"]] == [
        "step 1 game_mode", "step 3 select_area", "step 4 dialog", "step 5 fight"]


def test_send_filters_a_in_shop():
    io = _ScriptedIO([])
    MenuDriver(io, log=lambda *a, **k: None)._send([MenuDriver._action("press:a")], "shop")
    assert io.actions == []


def test_menu_driver_does_not_press_a_in_shop(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    seq = [_save(tmp_path, _empty(), f"s{i}") for i in range(4)] + \
          [_save(tmp_path, _fight_frame(), "fight")]
    classes = ["shop"] * 4 + ["fight"]
    state = {"i": 0}

    def fake_classify(img, cache=None):
        idx = state["i"]
        state["i"] += 1
        return classes[idx]

    monkeypatch.setattr(menus, "classify", fake_classify)

    io = _ScriptedIO(seq)
    driver = MenuDriver(io, max_steps=10, log=lambda *a, **k: None, settle_s=0)
    driver.to_fight()
    cmds = [a["command"] for a in io.actions]
    assert cmds == ["press:b"] * 4


# --- script-level: --fights 2 -------------------------------------------------

def _play(monkeypatch, reached=(True, True), end_reasons=("fight_over", "fight_over"), n=2, start="any"):
    mod = importlib.import_module("test_scripts.game.game_kirby")
    drivers, runners = [], []

    class _StubDriver:
        def __init__(self, io):
            drivers.append(self)

        def to_fight(self):
            ok = reached[len(drivers) - 1]
            return {"reached": ok, "steps": 5, "menu_s": 1.5, "screens": ["village", "fight"],
                    "error": None if ok else "menu: max steps"}

    class _StubRunner:
        def __init__(self, io, context, choose=None, max_duration=170):
            runners.append(self)

        def run(self, outcome_writer=None):
            return {"chooser": "fixed", "fight_s": 30.0, "end_reason": end_reasons[len(runners) - 1],
                    "frames": 100, "tactics": {"rush": 50}}

    class _Io:
        def evidence(self, name):
            return ""

    class _Ctx:
        def __init__(self):
            self.steps = []

        def record_step_immediately(self, step):
            self.steps.append(step)

    monkeypatch.setattr(mod, "MenuDriver", _StubDriver)
    monkeypatch.setattr(mod, "KirbyRunner", _StubRunner)
    ctx = _Ctx()
    res = mod.play_fights(_Io(), ctx, n, start, 170, "fixed", None, None)
    return res, drivers, runners, ctx


def test_script_fights_two_calls_driver_twice_and_runner_twice(monkeypatch):
    (meta, ok, err, last), drivers, runners, ctx = _play(monkeypatch)
    assert (len(drivers), len(runners)) == (2, 2)
    assert ok is True and err == ""
    assert meta["fights_played"] == 2 and meta["fights_over"] == 2
    assert meta["menu_s_total"] == 3.0 and meta["chooser"] == "fixed"
    assert [f["fight"] for f in meta["fights"]] == [1, 2]
    assert all(f["menu_s"] == 1.5 and f["menu_steps"] == 5 for f in meta["fights"])
    assert sum(1 for s in ctx.steps if s["message"].startswith("Menus")) == 2


def test_script_start_fight_skips_first_menu(monkeypatch):
    (meta, ok, err, last), drivers, runners, ctx = _play(monkeypatch, reached=(True,), start="fight")
    assert (len(drivers), len(runners)) == (1, 2)
    assert meta["fights"][0]["menu_s"] == 0.0 and meta["fights"][0]["menu_steps"] == 0


def test_script_stops_when_menu_fails(monkeypatch):
    (meta, ok, err, last), drivers, runners, ctx = _play(monkeypatch, reached=(True, False))
    assert ok is False and "menu: max steps" in err
    assert meta["fights_played"] == 1 and len(runners) == 1
