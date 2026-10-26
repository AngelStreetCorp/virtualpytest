"""TASK-131: recorder folding, minimap zones and the seven scorecard rules on a synthetic timeline.

The timeline is built here in the exact shape ``live_recorder`` writes (no real game was recorded yet:
goal 7). It is a 20-minute Garen top game with known farm, deaths, recalls and objectives.
"""

import pytest

from shared.src.lib.game.leagueoflegends import live_recorder as lr
from shared.src.lib.game.leagueoflegends import minimap, scorecard as sc

ME = "Me#EUW"


def _timeline(cs_per_min=8.0, deaths=(), items_at=None, recalls=(), gold_at_death=0):
    items_at = items_at or {540: ["Berserker's Greaves"], 960: ["Berserker's Greaves", "Stridebreaker"]}
    tl = {
        "version": 1,
        "meta": {"player": ME, "champion": "Garen", "team": "ORDER", "assigned_position": "TOP"},
        "players": [{"name": ME, "team": "ORDER"}, {"name": "Foe#EUW", "team": "CHAOS"}],
        "samples": [], "events": [], "zones": [],
    }
    kills = assists = 0
    items, gold = [], 300.0
    for t in range(0, 1201, 10):
        if t in items_at:
            items = items_at[t]
        dead = any(d <= t < d + 20 for d in deaths)
        gold += 20
        if t in recalls:
            gold -= 800
            items = items + ["Long Sword"]
        if any(t == d for d in deaths):
            gold = gold_at_death or gold
        n_deaths = sum(1 for d in deaths if d <= t)
        tl["samples"].append({
            "t": float(t), "gold": gold, "level": 1 + t // 90, "hp": 500.0 if t % 60 else 650.0, "hp_max": 650.0,
            "dead": dead,
            "scores": {"kills": kills + (t > 600), "deaths": n_deaths, "assists": assists + (t > 800) * 2,
                       "cs": int(max(0, t - 60) / 60 * cs_per_min), "ward": 0.0},
            "items": list(items),
        })
        if t in recalls:
            gold = 0.0
    for i, d in enumerate(deaths):
        tl["events"].append({"EventID": i, "EventName": "ChampionKill", "EventTime": float(d), "VictimName": ME, "KillerName": "Foe#EUW", "Assisters": []})
    return tl


@pytest.fixture(scope="module")
def ref():
    return sc.load_reference()


def test_reference_loads_with_sources(ref):
    assert ref["cs_per_min"]["early"]["target"] == 8.0 and ref["sources"]


def test_farm_scales_with_cs_per_min(ref):
    good = sc.score_farm(_timeline(8.0), ref)["score"]
    mid = sc.score_farm(_timeline(6.5), ref)["score"]
    bad = sc.score_farm(_timeline(4.0), ref)["score"]
    assert good == sc.TARGET_CREDIT and 40 < mid < 80 and 0 < bad < sc.FLOOR_CREDIT


def test_deaths_early_weigh_more(ref):
    none = sc.score_deaths(_timeline(), ref)["score"]
    early = sc.score_deaths(_timeline(deaths=(300, 400)), ref)
    late = sc.score_deaths(_timeline(deaths=(900, 1000)), ref)
    assert none == 100 and early["score"] < late["score"] <= none
    assert early["numbers"]["deaths_before_10"] == 2


def test_kills_share(ref):
    r = sc.score_kills(_timeline(), ref)
    assert r["numbers"]["kills"] == 1 and r["numbers"]["assists"] == 2 and 0 <= r["score"] <= 100


def test_objectives_and_turret_tier(ref):
    tl = _timeline()
    tl["events"] += [
        {"EventID": 50, "EventName": "TurretKilled", "EventTime": 700.0, "TurretKilled": "Turret_T2_L_03_A", "KillerName": ME, "Assisters": []},
        {"EventID": 51, "EventName": "DragonKill", "EventTime": 800.0, "KillerName": "Foe#EUW", "Assisters": []},
        {"EventID": 52, "EventName": "TurretKilled", "EventTime": 900.0, "TurretKilled": "Turret_T1_L_03_A", "KillerName": "Minion_T200L0S0", "Assisters": []},
    ]
    r = sc.score_objectives(tl, ref)
    assert sc.turret_tier("Turret_T2_L_02_A") == "T2"
    t1, drake = ref["objective_points"]["turret_T1"], ref["objective_points"]["dragon"]
    assert r["numbers"]["team_points"] == t1 and r["numbers"]["enemy_points"] == drake + t1
    assert r["numbers"]["player_involved_points"] == t1 and abs(r["score"] - 100 * t1 / (2 * t1 + drake)) < 0.2


def test_objectives_unmeasured_without_events(ref):
    assert sc.score_objectives(_timeline(), ref)["score"] is None


def test_items_on_time_vs_late(ref):
    ok = sc.score_items(_timeline(items_at={500: ["Berserker's Greaves"], 900: ["Berserker's Greaves", "Stridebreaker"]}), ref)
    late = sc.score_items(_timeline(items_at={1100: ["Berserker's Greaves"]}), ref)
    assert ok["score"] > late["score"] and late["score"] == 0


def test_recalls_gold_and_unspent_death(ref):
    rich = sc.score_recalls(_timeline(recalls=(400,)), ref)
    poor = sc.score_recalls(_timeline(recalls=(100,)), ref)
    assert len(rich["numbers"]["recalls"]) == 1 and rich["score"] > poor["score"]
    died = sc.score_recalls(_timeline(deaths=(600,), gold_at_death=1500.0), ref)
    assert died["numbers"]["deaths_with_unspent_gold"] == 1


def test_lane_needs_zones_then_scores(ref):
    tl = _timeline()
    assert sc.score_lane(tl, ref)["score"] is None
    tl["zones"] = [{"t": 100 + 30 * i, "zone": "top" if i % 4 else "jungle"} for i in range(20)]
    assert sc.score_lane(tl, ref)["score"] == 100


def test_scorecard_overall_and_unmeasured(ref, tmp_path):
    card = sc.scorecard(_timeline(), ref)
    assert card["overall"] is not None and "lane" in card["unmeasured"] and "objectives" in card["unmeasured"]
    sc.write_report(card, ref, str(tmp_path / "c.json"), str(tmp_path / "c.html"))
    assert "Garen" in (tmp_path / "c.html").read_text() and (tmp_path / "c.json").exists()


def test_short_game_not_scored(ref):
    tl = _timeline()
    tl["samples"] = tl["samples"][:3]
    assert sc.score_farm(tl, ref)["score"] is None and sc.score_deaths(tl, ref)["score"] is None


# ------------------------------------------------------------------ recorder
def _data(t, cs, events=()):
    return {
        "activePlayer": {"riotId": ME, "currentGold": 500.0, "level": 3, "championStats": {"currentHealth": 400.0, "maxHealth": 600.0}},
        "allPlayers": [{"riotId": ME, "championName": "Garen", "team": "ORDER", "position": "TOP", "isDead": False,
                        "scores": {"kills": 0, "deaths": 0, "assists": 0, "creepScore": cs, "wardScore": 0.0},
                        "items": [{"displayName": "Long Sword", "count": 2}]}],
        "events": {"Events": list(events)},
        "gameData": {"gameTime": t, "mapName": "Map11", "gameMode": "PRACTICETOOL"},
    }


def test_recorder_folds_polls_and_stops_on_game_end(tmp_path):
    seq = [None, _data(10, 1), _data(12, 2, [{"EventID": 1, "EventName": "GameStart"}]),
           _data(12, 2, [{"EventID": 1, "EventName": "GameStart"}]),
           _data(14, 3, [{"EventID": 1, "EventName": "GameStart"}, {"EventID": 2, "EventName": "GameEnd"}])]
    it = iter(seq)
    out = tmp_path / "t.json"
    tl = lr.record_game(str(out), fetch=lambda: next(it), sleep=lambda s: None)
    assert [s["t"] for s in tl["samples"]] == [10, 12, 14]
    assert [e["EventID"] for e in tl["events"]] == [1, 2]
    assert tl["samples"][0]["items"] == ["Long Sword", "Long Sword"] and tl["meta"]["champion"] == "Garen"
    assert lr.load_timeline(str(out))["meta"]["mode"] == "PRACTICETOOL"


def test_recorder_times_out_without_game():
    with pytest.raises(TimeoutError):
        lr.record_game("/nonexistent/x.json", interval=1, wait_start_s=3, fetch=lambda: None, sleep=lambda s: None)


# ------------------------------------------------------------------ minimap
@pytest.mark.parametrize("xy,zone", [
    ((0.08, 0.92), "base"), ((0.93, 0.07), "base"), ((0.08, 0.5), "top"), ((0.5, 0.07), "top"),
    ((0.5, 0.5), "mid"), ((0.5, 0.93), "bot"), ((0.93, 0.5), "bot"), ((0.3, 0.3), "river"),
    ((0.25, 0.55), "jungle"), ((0.75, 0.45), "jungle"),
])
def test_zone_of(xy, zone):
    assert minimap.zone_of(*xy) == zone


def test_find_marker_on_synthetic_minimap():
    import cv2
    import numpy as np

    img = np.zeros((200, 200, 3), np.uint8)
    cv2.circle(img, (40, 60), 9, (255, 80, 0), -1)      # blue ally fill (BGR)
    cv2.circle(img, (40, 60), 9, (255, 255, 255), 2)    # white ring = active player
    x, y = minimap.find_marker(img, "ORDER")
    assert abs(x - 0.2) < 0.03 and abs(y - 0.3) < 0.03
    assert minimap.find_marker(np.zeros((50, 50, 3), np.uint8), "ORDER") is None
    assert minimap.evaluate([{"image": img, "zone": "jungle"}], rect=(0, 0, 1, 1))["agreement"] == 1.0


def test_bad_moments_video_links_and_compare(ref, tmp_path):
    tl = _timeline(deaths=(300,), recalls=(100,))
    bm = sc.bad_moments(tl, ref)
    kinds = {m["kind"] for m in bm}
    assert {"death", "late/poor recall"} <= kinds and bm == sorted(bm, key=lambda m: m["t"])
    assert sc.video_link("http://x/v.mp4", 300, 12) == "http://x/v.mp4#t=312" and sc.video_link(None, 3) is None
    a, b = sc.scorecard(_timeline(8.0), ref), sc.scorecard(_timeline(5.0), ref)
    c = sc.compare([a, b])
    assert c["areas"]["farm"][0] > c["areas"]["farm"][1]
    sc.write_report(b, ref, str(tmp_path / "c.json"), str(tmp_path / "c.html"), moments=bm, video_url="http://x/v.mp4", others=[a])
    page = (tmp_path / "c.html").read_text()
    assert "v.mp4#t=300" in page and "side by side" in page
