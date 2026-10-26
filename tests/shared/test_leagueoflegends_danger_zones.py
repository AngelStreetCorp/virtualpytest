import json

from shared.src.lib.game.leagueoflegends import danger_zones as dz
from shared.src.lib.game.leagueoflegends.game_input import GameInput
from shared.src.lib.game.leagueoflegends.garen_bot import Mem, State
from shared.src.lib.game.leagueoflegends.perception import PLAYER_XY, Bar
from shared.src.lib.game.leagueoflegends.scorecard import turns_section
from shared.src.lib.game.leagueoflegends.turn_log import TurnLog, choice_of, read_turns


def _min(team, x, y, t=None):
    return Bar("minion", x, y, 1.0, team, t)


def _ids(zones, kind):
    return [z for z in zones if z["kind"] == kind]


def test_untanked_enemy_minion_is_danger_tanked_is_caution():
    px, py = PLAYER_XY
    enemy = _min("enemy", px + 100, py - 40)
    z = dz.compute_zones([enemy], [])
    assert _ids(z, "enemy_minion_threat")[0]["level"] == "danger"
    z = dz.compute_zones([enemy], [_min("ally", px + 120, py - 40)])
    assert _ids(z, "enemy_minion_threat")[0]["level"] == "caution"


def test_caster_reach_is_its_own_zone_kind():
    px, py = PLAYER_XY
    melee = dz.compute_zones([_min("enemy", px, py, "melee")], [])
    assert not _ids(melee, "enemy_caster_reach")
    for typ in ("caster", None):
        z = dz.compute_zones([_min("enemy", px, py, typ)], [])
        ring = _ids(z, "enemy_caster_reach")[0]
        assert ring["level"] == "caution" and abs(ring["r"] * dz.FRAME_W - dz.CASTER_REACH_PX) < 1


def test_retreat_point_is_a_safe_spot_outside_threats():
    px, py = PLAYER_XY
    z = dz.compute_zones([_min("enemy", px + 50, py)], [])
    pt = dz.retreat_point(z)
    assert pt is not None and not dz._blocked(pt, [x for x in z if x["kind"] != "safe"])
    assert dz.retreat_point([]) is None


def test_turret_needs_three_allied_minions():
    t = Bar("turret", 1200, 300, 1.0, "enemy")
    two = [_min("ally", 1200, 300 + 60), _min("ally", 1150, 300 + 60)]
    assert _ids(dz.compute_zones([t], two), "enemy_turret")[0]["level"] == "danger"
    assert _ids(dz.compute_zones([t], two + [_min("ally", 1250, 360)]), "enemy_turret")[0]["level"] == "caution"


def test_champion_zone_and_safe_spots_avoid_danger():
    px, py = PLAYER_XY
    ch = Bar("champion", px + 200, py, 0.8, "enemy")
    z = dz.compute_zones([ch], [], retreat_dir=(-1.0, 1.0))
    assert _ids(z, "enemy_champion")[0]["level"] == "danger"
    safe = _ids(z, "safe")
    assert safe and all(not dz._blocked((s["x"] * dz.FRAME_W, s["y"] * dz.FRAME_H), [z[0]]) for s in safe)
    assert {"id", "kind", "level", "shape", "x", "y", "r", "reason"} <= set(z[0])
    assert 0 <= z[0]["x"] <= 1 and 0 <= z[0]["y"] <= 1


def test_standing_in_lists_zones_containing_garen():
    px, py = PLAYER_XY
    z = dz.compute_zones([_min("enemy", px + 50, py)], [])
    assert dz.standing_in(z) == ["min1", "poke1"]


def test_turn_log_records_inputs_and_writes_contract_lines(tmp_path):
    live = tmp_path / "live.json"
    tl = TurnLog(str(tmp_path), live_path=str(live), clock=lambda: 10.0)
    gi = GameInput(guard=type("G", (), {"check": lambda self: None})(), dry_run=True)
    gi.on_input = tl.add_input
    gi.key("Q")
    gi.right_click(960, 600)
    gi.right_click(1700, 1000)  # inside the minimap
    gi.left_click(100, 100)
    gi.type_text("abc")
    s = State(t=1.0, game_t=84.3, hp=640, max_hp=810, gold=215, level=3, dead=False, items=["Doran's Shield"], enemies=[], allies=[])
    bot = type("B", (), {"mem": Mem(), "last_cs": 7})()
    tl.tick(bot, s, {"activePlayer": {"championStats": {"armor": 38, "magicResist": 32, "moveSpeed": 340}}}, [("right", 1, 2)])
    turns = read_turns(str(tmp_path / "turns.jsonl"))
    assert len(turns) == 1 and turns[0]["turn"] == 1
    kinds = [i["kind"] for i in turns[0]["inputs"]]
    assert kinds == ["key", "right_click", "minimap", "left_click", "type_text"]
    assert turns[0]["inputs"][0]["key"] == "Q" and turns[0]["inputs"][1]["x"] == 0.5
    assert turns[0]["state"]["armor"] == 38 and turns[0]["state"]["cs"] == 7 and turns[0]["decision"]["choice"] == "attack"
    zl = json.loads((tmp_path / "zones.jsonl").read_text().splitlines()[0])
    assert zl["frame"] == {"w": 1920, "h": 1200} and zl["t"] == 84.3
    lv = json.loads(live.read_text())
    assert len(lv["recent_inputs"]) == 5 and lv["recent_inputs"][0]["age_s"] == 0.0 and "zones" in lv
    assert "show turns" in turns_section(turns) and 'id="turn-1"' in turns_section(turns)


def test_choice_of():
    assert choice_of([]) == "hold" and choice_of([("key", "E")]) == "cast_E" and choice_of([("minimap", 1, 2)]) == "move_minimap"


def test_world_block_units_summary_and_spells(tmp_path):
    from shared.src.lib.game.leagueoflegends.perception import Bar

    px, py = PLAYER_XY
    en = [Bar("minion", px + 100, py - 50 + 0, 0.4, "enemy"), Bar("minion", px + 600, py, 1.0, "enemy"), Bar("champion", px + 300, py - 100, 0.9, "enemy")]
    al = [Bar("minion", px - 50, py - 50, 0.8, "ally"), Bar("champion", px, py - 150, 1.0, "ally")]  # the last is Garen's own bar
    s = State(t=5.0, game_t=100.0, hp=600, max_hp=800, gold=0, level=3, dead=False, items=[], enemies=en, allies=al)
    s.target_hp = (180, 450)
    mem = Mem()
    mem.sel = {"x": px + 100, "y": py}
    data = {"activePlayer": {"summonerName": "me", "championStats": {"abilityHaste": 100.0, "moveSpeed": 340},
                             "abilities": {"Q": {"abilityLevel": 1}, "W": {"abilityLevel": 0}, "E": {"abilityLevel": 1}, "R": {"abilityLevel": 0}}},
            "allPlayers": [{"summonerName": "me", "team": "ORDER", "championName": "Garen", "level": 3, "isDead": False,
                            "summonerSpells": {"summonerSpellOne": {"displayName": "Flash"}, "summonerSpellTwo": {"displayName": "Ignite"}}},
                           {"summonerName": "foe", "team": "CHAOS", "championName": "Darius", "level": 3, "isDead": False, "items": []}]}
    mem.last_attack_t = 4.0
    tl = TurnLog(str(tmp_path), clock=lambda: 1.0)
    tl.add_input("key", key="Q")
    s.attack_speed = 1.0
    tl.tick(type("B", (), {"mem": mem})(), s, data, [])
    t = read_turns(str(tmp_path / "turns.jsonl"))[0]
    w = t["world"]
    kinds = [u["kind"] for u in w["units"]]
    assert kinds.count("enemy_minion") == 2 and kinds.count("ally_minion") == 1 and "ally_champion" not in kinds and w["self"]["bar_seen"]
    e0 = next(u for u in w["units"] if u["kind"] == "enemy_minion")
    assert e0["in_attack_range"] and e0["hp_exact"] == 180 and e0["hp_max"] == 450 and e0["walk_eta_s"] == 0.0
    far = [u for u in w["units"] if u["kind"] == "enemy_minion"][-1]
    assert far["walk_eta_s"] == round((600 - 210) / 340, 2)
    foe = next(u for u in w["units"] if u["kind"] == "enemy_champion")
    assert foe["champion"] == "Darius"
    assert w["summary"]["within_500_units"] == {"ally_minion": 1, "enemy_minion": 1}
    assert w["summary"]["lowest_hp_enemy_minion_in_range"]["hp_frac"] == 0.4 and w["summary"]["targeting_garen"] is None
    sp = t["state"]["spells"]
    assert sp["Q"]["cooldown_s"] == 4.0 and sp["Q"]["ready_in_s"] == 4.0 and sp["W"]["ready_in_s"] is None and sp["E"]["ready_in_s"] == 0.0
    assert sp["D"]["name"] == "Flash" and sp["auto"]["attack_period_s"] == 1.0 and sp["auto"]["next_auto_in_s"] == 0.0


def test_minion_type_learned_from_hp_max_then_kept_on_the_bar(tmp_path):
    from shared.src.lib.game.leagueoflegends.perception import Bar
    from shared.src.lib.game.leagueoflegends.turn_log import minion_type_from_hp_max

    assert [minion_type_from_hp_max(h) for h in (290, 500, 570, 835, 750)] == ["caster", "melee", "melee", "cannon", None]
    px, py = PLAYER_XY
    mem = Mem()
    mem.sel = {"x": px + 100, "y": py}
    tl = TurnLog(str(tmp_path), clock=lambda: 1.0)
    bot = type("B", (), {"mem": mem})()
    s = State(t=1.0, game_t=10.0, hp=800, max_hp=800, gold=0, level=1, dead=False, items=[],
              enemies=[Bar("minion", px + 100, py - 50, 0.6, "enemy"), Bar("minion", px + 400, py - 50, 0.9, "enemy")], allies=[])
    s.target_hp = (300, 500)
    tl.tick(bot, s, {}, [])
    s2 = State(t=2.0, game_t=10.4, hp=800, max_hp=800, gold=0, level=1, dead=False, items=[],
               enemies=[Bar("minion", px + 105, py - 50, 0.5, "enemy"), Bar("minion", px + 405, py - 50, 0.9, "enemy")], allies=[])
    tl.tick(bot, s2, {}, [])
    t1, t2 = read_turns(str(tmp_path / "turns.jsonl"))
    assert t1["world"]["units"][0]["type"] == "melee" and t1["world"]["units"][0]["type_source"] == "hp_max"
    assert t2["world"]["units"][0]["type"] == "melee" and t2["world"]["units"][0]["type_source"] == "track"
    assert t2["world"]["units"][1]["type"] is None
