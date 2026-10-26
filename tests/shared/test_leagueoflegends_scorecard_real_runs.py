"""TASK-131 goal 7: banded scoring (different games differ), camera-box finder, automatic scoring of a finished run."""

import json
import os

import numpy as np
import pytest

from shared.src.lib.game.leagueoflegends import minimap, score_run, scorecard as sc
from tests.shared.test_leagueoflegends_scorecard import ME, _timeline


def test_banded_ranks_games_below_the_floor():
    assert sc._banded(0, 5, 8) == 0
    assert sc._banded(1.5, 5, 8) < sc._banded(4.6, 5, 8) < sc._banded(5, 5, 8) == sc.FLOOR_CREDIT
    assert sc._banded(8, 5, 8) == 100


def test_elite_band_tops_the_farm_scale():
    assert sc._banded(8, 5, 8, 10) == sc.TARGET_CREDIT and sc._banded(10, 5, 8, 10) == 100 and sc._banded(12, 5, 8, 10) == 100
    assert sc._banded(8, 5, 8) == 100  # no elite band: the target is the top


def test_two_poor_farmers_no_longer_tie():
    ref = sc.load_reference()
    a, b = sc.score_farm(_timeline(1.5), ref)["score"], sc.score_farm(_timeline(4.0), ref)["score"]
    assert 0 < a < b < sc.FLOOR_CREDIT


def _minimap_with_box(cx, cy, w=150, h=145):
    img = np.full((h, w, 3), (40, 56, 52), np.uint8)
    bw, bh = int(minimap.CAM_W * w), int(minimap.CAM_H * h)
    x0, y0 = int(cx * w - bw / 2), int(cy * h - bh / 2)
    img[y0:y0 + bh, x0] = img[y0:y0 + bh, x0 + bw] = (200, 215, 212)
    img[y0, x0:x0 + bw + 1] = img[y0 + bh, x0:x0 + bw + 1] = (200, 215, 212)
    return img


@pytest.mark.parametrize("cx,cy,zone", [(0.2, 0.5, "top"), (0.5, 0.5, "mid"), (0.5, 0.85, "bot")])
def test_camera_box_gives_player_zone(cx, cy, zone):
    pos = minimap.find_camera_box(_minimap_with_box(cx, cy))
    assert pos and abs(pos[0] - cx) < 0.03 and abs(pos[1] - cy) < 0.03
    assert minimap.zone_of(*pos) in (zone, "river", "jungle")  # geometry is checked on real frames, not here


def test_finished_run_is_scored_once(tmp_path):
    run = tmp_path / "garen-run-1"
    run.mkdir()
    (run / "timeline.json").write_text(json.dumps(_timeline(6.0)))
    assert score_run.score_finished_runs(str(tmp_path)) == []  # no result.json, no GameEnd: still playing
    (run / "result.json").write_text("{}")
    assert score_run.score_finished_runs(str(tmp_path)) == [str(run)]
    card = json.loads((run / score_run.JSON_NAME).read_text())
    assert card["overall"] is not None and os.path.exists(run / score_run.HTML_NAME)
    assert score_run.score_finished_runs(str(tmp_path)) == []  # up to date


def test_auto_record_skips_while_bot_run_is_fresh(tmp_path, monkeypatch):
    pytest.importorskip("psutil")
    import importlib.util
    import time

    spec = importlib.util.spec_from_file_location("auto_record", os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "lol_practice", "auto_record.py"))
    ar = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ar)
    import psutil

    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [])  # other sessions on this machine run the bot
    run = tmp_path / "garen-run-1"
    run.mkdir()
    (run / "timeline.json").write_text("{}")
    assert ar.bot_is_playing(tmp_path) is True
    (run / "result.json").write_text("{}")
    assert ar.bot_is_playing(tmp_path) is False
    os.utime(run / "timeline.json", (time.time() - 999, time.time() - 999))
    (run / "result.json").unlink()
    assert ar.bot_is_playing(tmp_path) is False


def test_minion_gold_orders_cannon_melee_caster():
    assert sc.minion_gold("cannon", 300) > sc.minion_gold("melee", 300) > sc.minion_gold("caster", 300)
    assert sc.minion_gold("cannon", 600) == 59 and sc.minion_gold("cannon", 1500) == 66 and sc.minion_gold("cannon", 3000) == 69


def test_cannons_missed_weigh_more_than_melee_or_caster():
    ref = sc.load_reference()
    tl = _timeline(6.0)
    assert sc.score_cannons(tl, ref)["score"] is None  # no screen reader data: not measured
    one = lambda kind: sc.score_cannons(dict(tl, missed_minions=[{"t": 300, "kind": kind}]), ref)["score"]
    assert one("cannon") < one("melee") < one("caster") < 100
    assert sc.score_cannons(dict(tl, missed_minions=[]), ref)["score"] == 100


def _hud_frame(name):
    import cv2

    crop = cv2.imread(os.path.join(os.path.dirname(__file__), "fixtures", "lol_cs", name))
    frame = np.zeros((600, 960, 3), np.uint8)
    frame[1:1 + crop.shape[0], 862:862 + crop.shape[1]] = crop  # where the counter sits on a 960x600 shot
    return frame


@pytest.mark.parametrize("cs", [0, 5, 16, 38, 46])
def test_cs_reader_reads_hud_counter(cs):
    pytest.importorskip("cv2")
    from shared.src.lib.game.leagueoflegends import cs_reader

    assert cs_reader.read_cs(_hud_frame(f"cs_{cs}.png")) == cs
    import cv2

    big = cv2.resize(_hud_frame(f"cs_{cs}.png"), (1920, 1200), interpolation=cv2.INTER_CUBIC)  # full-resolution grab
    assert cs_reader.read_cs(big) == cs


def test_scorecard_uses_exact_cs_when_recorded():
    ref = sc.load_reference()
    tl = _timeline(6.0)
    base = sc.score_farm(tl, ref)
    tl["cs_exact"] = [{"t": 90.0, "cs": 0}, {"t": 600.0, "cs": 40}]  # 4.7 CS/min, below the 6.0 creepScore implies
    exact = sc.score_farm(tl, ref)
    assert exact["numbers"]["cs_source"].startswith("hud") and exact["score"] < base["score"]
    assert sc.cs_at(tl, 345.0) == pytest.approx(20.0)


def test_minion_watcher_marks_ours_and_missed_and_scores_them():
    from shared.src.lib.game.leagueoflegends.minion_events import MinionWatcher
    from shared.src.lib.game.leagueoflegends.perception import Bar

    w = MinionWatcher()
    cs = 0
    for i in range(30):  # 15 s at 2 Hz: a cannon at (900, 480) dies at 3 s with a CS step, a minion at (800, 500) at 9 s without
        t = i * 0.5
        bars = []
        if t <= 3.0:
            bars.append(Bar("minion", 900, 480, 0.3, "enemy", "cannon"))
        if t <= 9.0:
            bars.append(Bar("minion", 800, 500, 0.3, "enemy"))
        bars.append(Bar("minion", 100, 100, 0.2, "enemy"))  # far away: never a death near us
        if t >= 3.2:
            cs = 1
        w.update(t, bars, cs)
    d = w.finish(15.0)
    assert [(x["kind"], x["ours"]) for x in d] == [("cannon", True), ("minion", False)]
    tl = _timeline(6.0)
    tl["minion_deaths"] = d
    r = sc.score_cannons(tl, sc.load_reference())
    assert r["score"] is not None and r["numbers"]["last_hit_rate_cannon"] == 1.0 and r["numbers"]["last_hit_rate_minion"] == 0.0
    assert r["numbers"]["gold_lost"]["minion"] == 17


def test_one_cs_credits_one_death_only():
    from shared.src.lib.game.leagueoflegends.minion_events import MinionWatcher
    from shared.src.lib.game.leagueoflegends.perception import Bar

    w = MinionWatcher()
    for i in range(14):  # two duplicate bars on one minion vanish together, one CS step happens
        t = i * 0.5
        bars = [Bar("minion", 900, 480, 0.3, "enemy"), Bar("minion", 904, 482, 0.3, "enemy")] if t <= 3.0 else []
        w.update(t, bars, 1 if t >= 3.2 else 0)
    assert [x["ours"] for x in w.finish(7.0)] == [True]  # the duplicate bar is merged, the one CS goes to the one death


def _run_with_attempts(tmp_path):
    from PIL import Image

    run = tmp_path / "garen-run-9"
    (run / "lasthit" / "a00").mkdir(parents=True)
    tl = _timeline(6.0)
    tl["minion_deaths"] = [{"t": 61.0, "kind": "cannon", "ours": False, "frac": 0.2}]
    (run / "timeline.json").write_text(json.dumps(tl))
    (run / "result.json").write_text("{}")
    (run / "lasthit" / "attempts.json").write_text(json.dumps({"hp_scale": 1.0, "attempts": [
        {"t": 30.0, "type": "minion", "est_hp": 50, "pred_hp": 20, "dmg": 80, "cs0": 1, "result": "hit", "x": 900, "y": 500},
        {"t": 45.0, "type": "cannon", "est_hp": 300, "pred_hp": 200, "dmg": 80, "cs0": 2, "result": "miss", "x": 900, "y": 500}]}))
    Image.new("RGB", (1920, 1200), (40, 60, 40)).save(run / "lasthit" / "a00" / "t00030.20.jpg")
    return run


def test_dataset_rows_have_the_agreed_fields_and_crops(tmp_path):
    from shared.src.lib.game.leagueoflegends import game_review

    run = _run_with_attempts(tmp_path)
    rows = game_review.write_dataset(str(run), str(tmp_path / "ds"))
    assert [r["outcome"] for r in rows] == ["hit", "miss"] and rows[0]["cause"] is None and "too early" in rows[1]["cause"]
    assert {"game_id", "game_t", "minion_type", "bar_frac", "pred_hp", "our_ad", "action", "outcome", "crop"} <= set(rows[0])
    assert rows[0]["crop"] and (tmp_path / "ds" / rows[0]["crop"]).exists() and rows[1]["crop"] is None  # no frames for a01
    assert len((tmp_path / "ds" / "garen-run-9.jsonl").read_text().splitlines()) == 2


def test_review_html_and_score_run_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("LOL_REVIEW_AI", "0")
    monkeypatch.setenv("LOL_DATASET_ROOT", str(tmp_path / "ds"))
    run = _run_with_attempts(tmp_path)
    score_run.score_run_dir(str(run))
    page = (run / "review.html").read_text()
    assert "CANNON MISS" in page.upper() and "died near us, no attempt" not in page.split("const D=")[0]
    assert (tmp_path / "ds" / "garen-run-9.jsonl").exists()


def test_worst_moments_and_review_log(tmp_path):
    from shared.src.lib.game.leagueoflegends import game_review, game_review_ai

    run = _run_with_attempts(tmp_path)
    moments = game_review_ai.worst_moments(game_review.load_run(str(run)))
    assert moments and moments[0]["t"] <= moments[-1]["t"] and any("cannon" in m["what"] for m in moments)
    (run / "review.json").write_text(json.dumps({"game_id": "garen-run-9", "model": "opus", "rule": "Wait 0.2 s longer before Q on a cannon", "cost_usd": 0.12}))
    log = tmp_path / "REVIEW_LOG.md"
    assert game_review_ai.collect_review_log(str(tmp_path), str(log)) == 1
    assert game_review_ai.collect_review_log(str(tmp_path), str(log)) == 0 and "Wait 0.2 s" in log.read_text()


def test_health_area_counts_drops_not_regen_or_respawn():
    ref = sc.load_reference()
    tl = _timeline(6.0)
    for i, s in enumerate(tl["samples"]):
        s["hp"], s["hp_max"], s["dead"] = 1000.0, 1000.0, False
    tl["samples"][30]["hp"] = 100.0   # a 900 hit ...
    for i in range(31, 40):           # ... regenerated back (a rise is not damage)
        tl["samples"][i]["hp"] = min(1000.0, 100.0 + 120 * (i - 30))
    tl["samples"][60]["dead"] = tl["samples"][61]["dead"] = True  # a death and respawn reset is not counted
    tl["samples"][60]["hp"] = 0.0
    r = sc.score_health(tl, ref)
    assert r["numbers"]["damage_taken"] == 900 and r["numbers"]["min_hp_pct"] == 10.0 and r["numbers"]["damage_by_source"] == {"minions/other": 900.0}
    clean = _timeline(6.0)
    for s in clean["samples"]:
        s["hp"], s["hp_max"], s["dead"] = 1000.0, 1000.0, False
    assert sc.score_health(clean, ref)["score"] == 100 and r["score"] < 100


def test_health_source_turret_and_hp_in_dataset_rows(tmp_path):
    from shared.src.lib.game.leagueoflegends import game_review

    tl = _timeline(6.0)
    for s in tl["samples"]:
        s["hp"], s["hp_max"], s["dead"] = 1000.0, 1000.0, False
    tl["samples"][40]["hp"] = 400.0
    tl["events"].append({"EventName": "ChampionKill", "EventTime": tl["samples"][40]["t"] + 2, "VictimName": ME, "KillerName": "Turret_TChaos_L1_P3_1"})
    assert sc.hp_drops(tl)[0]["source"] == "turret"
    run = _run_with_attempts(tmp_path)
    rows = game_review.write_dataset(str(run), str(tmp_path / "ds"))
    assert "hp_before" in rows[0] and "hp_after" in rows[0] and rows[0]["hp_before"] is not None


def test_laning_window_and_headlines():
    ref = sc.load_reference()
    tl = _timeline(6.0)  # a 20-minute game with 6 CS/min from 1:30
    for x in tl["samples"]:
        x["hp"] = x["hp_max"]  # the synthetic timeline wobbles health; this test is about the window
    w = sc.window_timeline(tl, 480)
    assert w["samples"][-1]["t"] <= 480 and len(w["samples"]) < len(tl["samples"])
    card = sc.laning_scorecard(tl, ref)
    assert card["window"].startswith("1:00-8:00") and card["game_minutes"] <= 8.1
    assert card["full_game"]["game_minutes"] >= 19.9 and set(card["headlines"]) == {"5:00", "8:00"}
    h5, h8 = card["headlines"]["5:00"], card["headlines"]["8:00"]
    assert h8["cs"] > h5["cs"] > 0 and h8["cs"] == pytest.approx(6.0 * 7, abs=1)  # 7 min after 1:00
    assert h5["damage_per_min"] == 0 and h5["target"]["cs"] == [32, 38]
    short = sc.window_timeline(tl, 200)
    assert sc.headlines(short, ref)["8:00"] is None and sc.headlines(short, ref)["5:00"] is None


def test_score_run_writes_laning_card_with_full_game_secondary(tmp_path, monkeypatch):
    monkeypatch.setenv("LOL_REVIEW_AI", "0")
    run = _run_with_attempts(tmp_path)
    score_run.score_run_dir(str(run))
    card = json.loads((run / score_run.JSON_NAME).read_text())
    assert card["window_s"] == 480 and "full_game" in card and card["headlines"]["8:00"]["lasthit_attempts"] == 0  # both fixture attempts (30 s, 45 s) are preparation time, before 1:00
    page = (run / score_run.HTML_NAME).read_text()
    assert "Laning headlines" in page and "secondary" in page


def test_rates_run_from_1_30_and_start_sequence_is_separate():
    ref = sc.load_reference()
    tl = _timeline(6.0)  # 6 CS/min from 1:00
    for x in tl["samples"]:
        x["hp"] = x["hp_max"]
    h = sc.headlines(sc.window_timeline(tl, 480), ref)["8:00"]
    assert h["cs_per_min"] == pytest.approx(6.0, abs=0.3)  # (cs at 8:00 - cs at 1:00) / 7 min, not cs / 8
    tl["samples"][5]["hp"] = 100.0  # a hit at 50 s (sample 5): preparation time, no damage counted
    assert sc.score_health(tl, ref)["numbers"]["damage_taken"] == 0
    tl["bot_events"] = [{"t": 0, "kind": "start_items", "detail": "ok [..]"}, {"t": 0, "kind": "camera_locked", "detail": "FAILED after 3 tries"}]
    ss = sc.start_sequence(tl)
    assert ss["checks"]["starter_items_bought"] is True and ss["checks"]["camera_locked"] is False and ss["pass"] is False and ss["scored"] is False
    assert sc.laning_scorecard(tl, ref)["overall"] == sc.laning_scorecard(dict(tl, bot_events=[]), ref)["overall"]  # not part of the score


def test_reward_section_in_scorecard_and_review(tmp_path, monkeypatch):
    monkeypatch.setenv("LOL_REVIEW_AI", "0")
    run = _run_with_attempts(tmp_path)
    (run / "reward_summary.json").write_text(json.dumps({"actions": {"auto": {"n": 10, "reward": 4.0, "mean_reward": 0.4, "mean_return_8s": 0.5, "useless_rate": 0.2}},
                                                         "events": {"last_hit": {"n": 4, "value": 4.0}}, "total_reward": 4.0, "turns": 40, "useless_action_rate": 0.2}))
    score_run.score_run_dir(str(run))
    assert 'id="reward"' in (run / score_run.HTML_NAME).read_text() and 'id="reward"' in (run / "review.html").read_text()


def test_elite_laning_targets_reach_the_headlines():
    ref = sc.load_reference()
    assert ref["laning_targets"]["480"]["cs"] == [64, 69] and ref["laning_targets"]["300"]["cs"] == [32, 38]
    h = sc.headlines(sc.window_timeline(_timeline(6.0), 480), ref)
    assert h["8:00"]["target"]["n"] == 6 and h["8:00"]["target"]["provisional"] is True
