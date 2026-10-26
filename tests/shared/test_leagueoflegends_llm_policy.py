from shared.src.lib.game.leagueoflegends import llm_policy as lp
from shared.src.lib.game.leagueoflegends.garen_bot import Mem, State
from shared.src.lib.game.leagueoflegends.perception import Bar


def _state(**kw):
    base = dict(t=100.0, game_t=120.0, hp=600, max_hp=700, gold=350, level=3, dead=False, items=["Doran's Shield"],
                enemies=[Bar("minion", 900, 500, 0.2, "enemy"), Bar("minion", 1400, 500, 0.9, "enemy"), Bar("champion", 1000, 480, 0.5, "enemy")],
                allies=[Bar("minion", 800, 500, 1.0, "ally")])
    base.update(kw)
    return State(**base)


def test_pick_json_tolerates_prose():
    assert lp.pick_json('ok {"a":"wait","t":null} done') == {"a": "wait", "t": None}
    assert lp.pick_json("no json") is None


def test_view_ids_sorted_by_distance():
    view, targets = lp.build_view(_state(), 12, 70.0, {})
    assert targets["m1"].x == 900 and targets["c1"].kind == "champion"
    assert view["cs"] == 12 and view["ally_minions_near"] == 1 and view["enemies"][0]["id"] == "m1"


def test_last_hit_right_clicks_the_minion_body():
    s = _state()
    _, targets = lp.build_view(s, 0, 70.0, {})
    acts, note = lp.choice_to_actions({"a": "last_hit", "t": "m1"}, targets, s, Mem(), s.t, {})
    assert note == "" and acts == [("right", *targets["m1"].body)]


def test_bad_target_and_cooldown_are_dropped():
    s = _state()
    _, targets = lp.build_view(s, 0, 70.0, {})
    assert lp.choice_to_actions({"a": "attack", "t": "zz"}, targets, s, Mem(), s.t, {})[0] == []
    cd = {}
    assert lp.choice_to_actions({"a": "e"}, targets, s, Mem(), s.t, cd)[0] == [("key", "E")]
    assert lp.choice_to_actions({"a": "e"}, targets, s, Mem(), s.t + 1, cd)[1] == "E on cooldown"
    assert lp.choice_to_actions({"a": "r", "t": "c1"}, targets, s, Mem(), s.t, {})[1] == "R before level 6"


def test_recall_only_with_gold_or_low_health_and_sets_mode():
    s = _state()
    m = Mem()
    acts, _ = lp.choice_to_actions({"a": "recall"}, {}, s, m, s.t, {})
    assert acts == [("recall",)] and m.mode == "RECALL"
    m2 = Mem()
    poor = _state(gold=100)
    assert lp.choice_to_actions({"a": "recall"}, {}, poor, m2, poor.t, {})[0] == [] and m2.mode == "LANE"
    assert lp.choice_to_actions({"a": "dance"}, {}, s, Mem(), s.t, {})[1].startswith("unknown")


def test_minion_type_and_gold_in_view():
    class Typed(Bar):
        pass

    b = Bar("minion", 900, 500, 0.2, "enemy")
    object.__setattr__(b, "minion_type", "cannon")  # frozen dataclass: perception may add the field
    view, _ = lp.build_view(_state(enemies=[b, Bar("minion", 950, 500, 0.5, "enemy")]), 0, 70.0, {})
    types = {r["id"]: (r["type"], r["gold"]) for r in view["enemies"]}
    assert types["m1"] == ("cannon", lp.MINION_GOLD["cannon"]) and types["m2"] == ("other", None)
    assert "cannon first" in lp.SYSTEM_PROMPT


def test_llm_bot_loop_stops_at_game_minute_five_and_logs_cost():
    import numpy as np

    from shared.src.lib.game.leagueoflegends.llm_policy import LlmBot

    class GI:
        def __init__(self):
            self.calls = []

        def key(self, k, ctrl=False):
            self.calls.append(("key", k))

        def right_click(self, x, y):
            self.calls.append(("rc", x, y))

        def type_text(self, t):
            self.calls.append(("txt", t))

    class Client:
        def decide(self, system, user, image_b64=None):
            return '{"a":"move_lane","t":null}', {"wall_ms": 800, "in_tokens": 300, "out_tokens": 10, "cost_usd": 0.0002}

    clock = [0.0]
    data = {"activePlayer": {"riotId": "a#b", "currentGold": 100, "level": 2, "championStats": {"currentHealth": 500, "maxHealth": 600, "attackDamage": 70}},
            "allPlayers": [{"riotId": "a#b", "team": "ORDER", "items": [], "scores": {"creepScore": 3}}],
            "gameData": {"gameTime": 280.0}, "events": {"Events": []}}

    def fetch():
        data["gameData"]["gameTime"] += 2.0
        return data

    def tick():
        clock[0] += 2.0
        return clock[0]

    bot = LlmBot(GI(), fetch, lambda: np.zeros((1200, 1920, 3), np.uint8), sleep=lambda x: None, clock=tick,
                 model="claude-haiku-5-5", client=Client())
    out = bot.run(10_000)
    assert out["decisions"] == out["errors"] + len(bot.decisions) - out["errors"] and 5 <= len(bot.decisions) <= 15
    assert out["latency_p50_ms"] == 800 and out["cost_usd"] > 0 and out["model"] == "claude-haiku-5-5"


def test_minion_gold_comes_from_basics_md():
    g = lp.MINION_GOLD  # the values come from the cited table in basics.md, not from this test
    assert set(g) == {"cannon", "melee", "caster"} and g["cannon"] > g["melee"] > g["caster"] > 0


def test_walk_to_lane_is_scripted_until_lane_or_110s():
    import numpy as np

    from shared.src.lib.game.leagueoflegends.llm_policy import LlmBot

    class GI:
        def key(self, k, ctrl=False):
            pass

        def right_click(self, x, y):
            self.last = (x, y)

        def type_text(self, t):
            pass

    class Client:
        calls = []

        def decide(self, system, user, image_b64=None):
            Client.calls.append(user)
            return '{"a":"wait","t":null}', {"wall_ms": 500, "in_tokens": 1, "out_tokens": 1, "cost_usd": 0.0}

    clock = [0.0]
    data = {"activePlayer": {"riotId": "a#b", "currentGold": 0, "level": 1, "championStats": {"currentHealth": 600, "maxHealth": 600, "attackDamage": 70}},
            "allPlayers": [{"riotId": "a#b", "team": "ORDER", "items": [], "scores": {"creepScore": 0}}],
            "gameData": {"gameTime": 40.0}, "events": {"Events": []}}

    def fetch():
        data["gameData"]["gameTime"] += 2.0
        return data

    def tick():
        clock[0] += 2.0
        return clock[0]

    bot = LlmBot(GI(), fetch, lambda: np.zeros((1200, 1920, 3), np.uint8), sleep=lambda x: None, clock=tick,
                 model="claude-haiku-5-5", client=Client())
    bot.stop_at_s = 100.0
    bot.run(10_000)
    assert Client.calls == []  # pos unknown, game_t < 110: the rule bot walks, the model is not asked
    bot.stop_at_s = 140.0
    bot.run(10_000)
    assert Client.calls and bot.lane_reached_t is not None


def test_turret_facts_and_veto():
    from shared.src.lib.game.leagueoflegends.llm_policy import LlmBot

    s = _state(enemies=[Bar("turret", 900, 360, 1.0, "enemy"), Bar("minion", 900, 500, 0.3, "enemy")], allies=[Bar("minion", 800, 500, 1.0, "ally")])
    view, _ = lp.build_view(s, 0, 70.0, {})
    assert view["turret"]["allied_minions_inside"] == 1 and view["turret"]["range"] >= 700
    bot = LlmBot(object(), lambda: None, lambda: None, model="rule")
    m = Mem()
    assert bot._turret_veto(s, m, view, "last_hit") == "inside turret range without 3 allied minions"
    assert m.retreat_until > s.t
    assert bot._turret_veto(s, m, view, "retreat") is None  # a retreat itself passes
    far = _state(enemies=[Bar("minion", 900, 500, 0.3, "enemy")])
    v2, _ = lp.build_view(far, 0, 70.0, {})
    assert v2["turret"] is None and bot._turret_veto(far, Mem(), v2, "last_hit") is None


def test_minimap_fence_vetoes_even_without_a_turret_bar():
    from shared.src.lib.game.leagueoflegends.llm_policy import LlmBot

    s = _state(enemies=[Bar("minion", 900, 500, 0.3, "enemy")], pos=(0.26, 0.07))
    s.fence_turret = (0.292, 0.063)
    view, _ = lp.build_view(s, 0, 70.0, {})
    assert view["turret"] is None and view["next_enemy_turret"]["map_dist"] < 0.13
    bot = LlmBot(object(), lambda: None, lambda: None, model="rule")
    assert bot._turret_veto(s, Mem(), view, "last_hit") == "past the lane fence"
    s.pos = (0.12, 0.07)
    view2, _ = lp.build_view(s, 0, 70.0, {})
    assert bot._turret_veto(s, Mem(), view2, "last_hit") is None
