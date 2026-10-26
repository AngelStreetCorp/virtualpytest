import numpy as np

from shared.src.lib.game.leagueoflegends import coach_policy as cp


class GI:
    def __init__(self):
        self.calls = []

    def key(self, k, ctrl=False):
        self.calls.append(("key", k))

    def right_click(self, x, y):
        self.calls.append(("rc", x, y))

    def type_text(self, t):
        pass

    def __getattr__(self, name):  # any other input call of the rule bot (focus, move, double click) is a no-op here
        return lambda *a, **k: None


def _bot(kind, monkeypatch, reply):
    data = {"activePlayer": {"riotId": "a#b", "currentGold": 900, "level": 2, "championStats": {"currentHealth": 600, "maxHealth": 600, "attackDamage": 70}},
            "allPlayers": [{"riotId": "a#b", "team": "ORDER", "items": [], "scores": {"creepScore": 3}}],
            "gameData": {"gameTime": 100.0}, "events": {"Events": []}}
    clock = [0.0]

    def fetch():
        data["gameData"]["gameTime"] += 2.0
        return data

    def tick():
        clock[0] += 2.0
        return clock[0]

    monkeypatch.setattr(cp, "_post", lambda url, payload, timeout=25.0: dict(reply(url, payload), wall_ms=300))
    bot = cp.CoachBot(GI(), fetch, lambda: np.zeros((1200, 1920, 3), np.uint8), sleep=lambda x: None, clock=tick, kind=kind)
    bot.stop_at_s = 160.0
    return bot


def test_haiku_coach_sets_the_plan_and_logs_the_layer(monkeypatch):
    bot = _bot("haiku-coach", monkeypatch, lambda url, p: {"text": '{"mode":"freeze","recall_now":false,"buy":null,"reason":"low hp"}', "cost_usd": 0.0001, "api_ms": 250})
    out = bot.run(10_000)
    import time

    time.sleep(0.2)
    assert out["model"] == "haiku-coach" and bot.plan["mode"] == "freeze" and bot.plan_changes >= 1
    assert out["strategist_calls"] >= 1 and out["tactician_calls"] == 0 and out["parse_failures"] == 0


def test_jev_coach_recall_choice_starts_the_rule_bots_recall(monkeypatch):
    bot = _bot("jev-coach", monkeypatch, lambda url, p: {"choice": "recall_now", "confidence": 0.9, "probabilities": {"recall_now": 0.9}, "cost_usd": 1e-5, "api_ms": 400})
    bot.run(10_000)
    assert bot.jev_rows and bot.jev_rows[0]["refs"]["contestant"] == "jev-coach"
    assert any(c == ("key", "B") for c in bot.gi.calls)  # the recall key went out through the rule bot's own input path


def test_duo_has_both_layers(monkeypatch):
    def reply(url, p):
        if url.endswith("/jev"):
            return {"choice": "hold", "confidence": 0.7, "probabilities": {"hold": 0.7}, "cost_usd": 1e-5, "api_ms": 400}
        return {"text": '{"mode":"push","recall_now":false,"buy":null,"reason":"ahead"}', "cost_usd": 0.0001, "api_ms": 300}

    bot = _bot("duo", monkeypatch, reply)
    out = bot.run(10_000)
    import time

    time.sleep(0.2)
    assert out["strategist_calls"] >= 1 and out["tactician_calls"] >= 1 and out["cost_usd"] > 0
