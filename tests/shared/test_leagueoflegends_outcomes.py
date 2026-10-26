import json
import os

import pytest

from shared.src.lib.game.leagueoflegends import outcomes as oc
from shared.src.lib.game.leagueoflegends.turn_log import new_events, read_turns


def _unit(kind="enemy_minion", x=0.5, y=0.45, frac=0.2, rng=True, **kw):
    return dict({"kind": kind, "hp_frac": frac, "x": x, "y": y, "dist_px": 100, "in_attack_range": rng}, **kw)


def _turn(n, t, choice, cs=3, hp=800, units=(), zones=(), events=None, inputs=(), nxt=0.0):
    d = {"t": t, "turn": n, "state": {"hp": hp, "hp_max": 800, "cs": cs, "ad": 100,
                                       "spells": {"auto": {"next_auto_in_s": nxt}, "Q": {"rank": 1, "ready_in_s": 0.0, "cooldown_s": 8}}},
         "decision": {"choice": choice, "zones": {"standing_in": list(zones)}}, "inputs": list(inputs), "world": {"units": list(units)}}
    if events:
        d["events"] = events
    return d


def test_last_hit_credited_to_the_auto_before_the_cs_increase():
    ts = [_turn(1, 10.0, "attack", units=[_unit()]), _turn(2, 10.3, "hold", cs=4), _turn(3, 10.6, "hold", cs=4)]
    ann = oc.annotate(ts)
    assert ann[0]["reward"] == 1.0 and ann[0]["outcomes"][0]["event"] == "last_hit" and ann[0]["outcomes"][0]["cause_action"] == "auto"
    assert ann[0]["outcomes"][0]["confidence"] == 0.9 and ann[1]["reward"] == 0.0
    assert ann[0]["return_8s"] == pytest.approx(1.0)  # later turns add nothing


def test_right_click_on_an_enemy_unit_is_an_auto():
    t = _turn(1, 1.0, "move", units=[_unit(x=0.5, y=0.45)], inputs=[{"kind": "right_click", "x": 0.51, "y": 0.46}])
    assert oc.action_of(t) == "auto"
    assert oc.action_of(_turn(2, 1.0, "move", inputs=[{"kind": "right_click", "x": 0.9, "y": 0.1}])) == "move"


def test_death_is_blamed_on_the_turns_in_zones_and_damage_on_the_acting_turn():
    ts = [_turn(1, 1.0, "move", hp=800, zones=["min1"]), _turn(2, 2.0, "hold", hp=700, zones=["min1"]),
          _turn(3, 3.0, "hold", hp=0, events=[{"kind": "death"}])]
    outs = oc.attribute(ts)
    dead = [o for o in outs if o["event"] == "death"]
    assert len(dead) == 2 and sum(o["value"] for o in dead) == pytest.approx(-10, abs=0.01)
    dmg = [o for o in outs if o["event"] == "damage_taken"]
    assert dmg[0]["cause_turn"] == 1 and dmg[0]["value"] == pytest.approx(-1.0) and dmg[0]["zones"] == ["min1"]
    assert not [o for o in dmg if o["cause_turn"] == 2]  # the drop into the death turn is the death, not damage


def test_champion_kill_goes_mostly_to_the_last_damaging_action():
    foe = _unit("enemy_champion", frac=0.5)
    foe["dist_px"] = 300
    ts = [_turn(1, 1.0, "attack", units=[foe]), _turn(2, 2.0, "cast_Q", units=[foe]), _turn(3, 3.0, "hold", events=[{"kind": "champion_kill"}])]
    outs = [o for o in oc.attribute(ts) if o["event"] == "champion_kill"]
    assert outs[0]["cause_turn"] == 2 and outs[0]["value"] == pytest.approx(7.0) and outs[1]["value"] == pytest.approx(3.0)


def test_idle_next_to_a_killable_minion_and_a_missed_last_hit():
    ts = [_turn(1, 1.0, "hold", units=[_unit(frac=0.1)]), _turn(2, 1.3, "hold")]
    ev = {o["event"]: o for o in oc.attribute(ts)}
    assert ev["idle_killable"]["value"] == -0.2 and ev["missed_last_hit"]["value"] == -0.5


def test_action_table_priors_and_decision_rows():
    ts = oc.annotate([_turn(1, 10.0, "attack", units=[_unit()]), _turn(2, 10.3, "hold", cs=4), _turn(3, 12.0, "move")])
    tab = oc.action_table(ts)
    assert tab["actions"]["auto"]["n"] == 1 and tab["actions"]["auto"]["mean_reward"] == 1.0 and tab["events"]["last_hit"]["n"] == 1
    assert tab["actions"]["move"]["useless_rate"] == 1.0
    rows = oc.decision_rows(ts)
    assert rows[0]["chosen"] == "auto" and rows[0]["outcome"]["reward"] == 1.0
    assert {"id", "facts"} <= set(rows[0]["options"][0]) and "1 auto(s) to kill" in rows[0]["options"][0]["facts"]
    pr = oc.priors([ts])
    assert pr["minion=1_hit|auto_ready|no_zone"]["auto"]["p_success"] == 1.0


def test_new_events_keeps_only_garens(tmp_path):
    names = {"me"}
    data = {"events": {"Events": [{"EventID": 1, "EventName": "ChampionKill", "KillerName": "me", "VictimName": "foe"},
                                  {"EventID": 2, "EventName": "ChampionKill", "KillerName": "foe", "VictimName": "me"},
                                  {"EventID": 3, "EventName": "ChampionKill", "KillerName": "x", "VictimName": "y", "Assisters": ["me"]},
                                  {"EventID": 4, "EventName": "TurretKilled", "KillerName": "me"},
                                  {"EventID": 5, "EventName": "ChampionKill", "KillerName": "x", "VictimName": "y"}]}}
    seen: set = set()
    assert [e["kind"] for e in new_events(data, seen, names)] == ["champion_kill", "death", "assist", "turret_kill"]
    assert new_events(data, seen, names) == []


def test_finalize_is_idempotent_and_writes_files(tmp_path):
    ts = [_turn(1, 10.0, "attack", units=[_unit()]), _turn(2, 10.3, "hold", cs=4)]
    (tmp_path / "turns.jsonl").write_text("".join(json.dumps(t) + "\n" for t in ts) + '{"t": 11, "tu')  # truncated last line
    s1 = oc.finalize(str(tmp_path))
    s2 = oc.finalize(str(tmp_path))
    assert s1["total_reward"] == s2["total_reward"] == 1.0
    assert read_turns(str(tmp_path / "turns.jsonl"))[0]["reward"] == 1.0
    for n in ("decisions.jsonl", "outcomes.jsonl", "reward_summary.json"):
        assert (tmp_path / n).exists()
    assert "Reward" in oc.reward_html(s1)


SAVED = os.path.expanduser("~/vpt-deliverables/lol-garen-bot/lol-aggro-turnlog/garen-run-20261019-055521/turns.jsonl")


@pytest.mark.skipif(not os.path.exists(SAVED), reason="saved run not on this machine")
def test_saved_run_every_cs_gain_is_a_last_hit_outcome():
    turns = []
    for ln in open(SAVED, encoding="utf-8"):
        try:
            turns.append(json.loads(ln))
        except ValueError:
            pass
    ann = oc.annotate(turns)
    gained = sum(1 for a, b in zip(turns, turns[1:]) if 0 < (b["state"]["cs"] or 0) - (a["state"]["cs"] or 0) < 10)
    assert sum(1 for t in ann for o in t["outcomes"] if o["event"] == "last_hit") == gained
    assert all(set(o) >= {"event", "value", "t", "cause_turn", "cause_action", "confidence"} for t in ann for o in t["outcomes"])
