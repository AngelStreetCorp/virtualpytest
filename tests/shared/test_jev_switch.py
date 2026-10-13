"""JEV_ENABLED / JEV_DISABLED_USAGES (TASK-47 G12): Jev off = no call, no log, every caller keeps its path.
No network, no DB."""
import importlib.util
import os
import sys

import pytest

_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.src.lib.ai import decisions  # noqa: E402
from backend_server.src.agent.core import sherlock_jev  # noqa: E402

OFF = {"success": False, "error": "jev_disabled", "disabled": True}


class Res:
    usage = "text.decision.sherlock"
    team_id = "t1"
    hops = []
    layer = "usage"
    primary = None


def _boom(*a, **k):
    raise AssertionError("must not be called when Jev is off")


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setenv("JEV_ENABLED", "false")
    monkeypatch.setattr(decisions, "_decide", _boom)
    monkeypatch.setattr(decisions, "_log", _boom)
    monkeypatch.setattr(decisions, "_decide_remote", _boom)
    monkeypatch.setattr(decisions.router, "record", _boom)


@pytest.mark.parametrize("value,expected", [("", True), ("true", True), ("1", True), ("false", False),
                                            ("0", False), ("No", False), (" OFF ", False)])
def test_switch_values(monkeypatch, value, expected):
    monkeypatch.setenv("JEV_ENABLED", value)
    assert decisions.enabled() is expected


def test_unset_means_on(monkeypatch):
    monkeypatch.delenv("JEV_ENABLED", raising=False)
    monkeypatch.delenv("JEV_DISABLED_USAGES", raising=False)
    assert decisions.enabled() and decisions.enabled("text.decision.sherlock")


def test_disabled_usages_cover_children_only(monkeypatch):
    monkeypatch.delenv("JEV_ENABLED", raising=False)
    monkeypatch.setenv("JEV_DISABLED_USAGES", " text.decision.sherlock , x ")
    assert not decisions.enabled("text.decision.sherlock")
    assert not decisions.enabled("text.decision.sherlock.deep")
    assert decisions.enabled("text.decision.sherlock2") and decisions.enabled("text.decision.companion")
    assert decisions.enabled()


def test_decide_and_choose_return_disabled_without_work(off, capsys):
    q = {"q": {"type": "noul", "instructions": "?", "criteria": {"true": "a", "false": "b"}}}
    assert decisions.decide(Res(), "s", q) == OFF
    out = decisions.choose(Res(), "s", [{"id": "a", "facts": "x"}], instructions="?")
    assert out["disabled"] is True and out["error"] == "jev_disabled" and out["success"] is False
    assert out["choice"] is None
    assert capsys.readouterr().out.count("disabled by JEV_ENABLED") <= 1


def test_per_usage_off_only_that_usage(monkeypatch):
    monkeypatch.delenv("JEV_ENABLED", raising=False)
    monkeypatch.setenv("JEV_DISABLED_USAGES", "text.decision.sherlock")
    monkeypatch.setattr(decisions, "_decide", _boom)
    assert decisions.decide(Res(), "s", {"q": {"type": "noul"}})["disabled"] is True


def test_server_route_answers_disabled(monkeypatch):
    from flask import Flask
    from backend_server.src.routes import server_ai_routing_routes as routes
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("JEV_ENABLED", "0")
    monkeypatch.setattr(routes.router, "resolve", _boom)
    monkeypatch.setattr(routes.router, "resolve_profile", _boom)
    app = Flask("t")
    app.register_blueprint(routes.server_ai_routing_bp)
    r = app.test_client().post("/server/ai/decide", json={"usage": "text.decision", "state": "s", "questions": {}},
                               headers={"X-API-Key": "k"})
    data = r.get_json()
    assert r.status_code == 200 and data["success"] is False and data["disabled"] is True
    assert data["error"] == "jev_disabled" and data["decision_id"] is None


def test_host_forwards_and_passes_through_server_disabled(monkeypatch):
    from shared.src.lib.ai import gateway
    monkeypatch.delenv("JEV_ENABLED", raising=False)
    monkeypatch.setattr(gateway, "is_local_routing", lambda: False)
    monkeypatch.setattr(gateway, "_host_context", lambda x: {})
    monkeypatch.setattr(gateway, "_server_post", lambda *a, **k: {**OFF, "answers": {}})
    out = decisions.decide(Res(), "s", {"q": {"type": "noul"}})
    assert out["disabled"] is True and out["success"] is False and out["error"] == "jev_disabled"


# ---- call sites -------------------------------------------------------------------------------

RECORD = {"id": "sr-1", "team_id": "team-1", "script_name": "zap", "success": False, "error_msg": "x"}


def test_sherlock_ask_returns_none_when_off(off, capsys):
    assert sherlock_jev.ask(RECORD, "review", 0.9) is None
    assert "Jev failed" not in capsys.readouterr().out


def test_sherlock_ask_none_when_server_says_disabled(monkeypatch, capsys):
    monkeypatch.delenv("JEV_ENABLED", raising=False)
    monkeypatch.setattr(sherlock_jev.router, "resolve", lambda u, t: Res())
    monkeypatch.setattr(sherlock_jev.decisions, "choose", lambda *a, **k: dict(OFF))
    assert sherlock_jev.ask(RECORD, "review", 0.9) is None
    assert "Jev failed" not in capsys.readouterr().out


def test_sherlock_gate_and_ai_error_fallback_run_the_llm(monkeypatch):
    monkeypatch.setenv("JEV_ENABLED", "false")
    monkeypatch.setattr(decisions, "_decide", _boom)
    from backend_server.src.agent.core import sherlock_handler
    h = sherlock_handler.SherlockHandler()
    seen = {"saved": [], "llm": 0, "errors": []}
    monkeypatch.setattr(h, "_mark_ai_error", lambda rid, err: seen["errors"].append(err))
    monkeypatch.setattr(h, "_load_script_result", lambda rid: dict(RECORD))
    monkeypatch.setattr(h, "_fetch_markdown", lambda record: "review")
    monkeypatch.setattr(h, "_save_analysis", lambda rid, a: seen["saved"].append(a))
    monkeypatch.setattr(sherlock_handler.sherlock_args, "for_record", lambda record: [])
    monkeypatch.setattr(sherlock_handler.sherlock_jev.router, "resolve", _boom)

    def llm(record, md, arguments=None):
        seen["llm"] += 1
        return {"classification": "VALID_FAIL", "discard": False, "explanation": "llm"}
    monkeypatch.setattr(h, "_classify_with_llm", llm)
    h.process_task_direct("script", "sr-1", {})
    assert seen["llm"] == 1 and seen["saved"][0]["classification"] == "VALID_FAIL"
    # LLM fails and Jev is off: the ai_error path stays (no Jev verdict to save)
    seen.update(saved=[], llm=0)
    monkeypatch.setattr(h, "_classify_with_llm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("402")))
    h.process_task_direct("script", "sr-1", {})
    assert seen["saved"] == [] and seen["errors"]


def test_testprompt_auto_decision_keeps_the_rule_when_off(off, monkeypatch):
    mod = importlib.import_module("features.ai-test.backend_server.server_testprompt_routes")
    monkeypatch.setattr(decisions.router, "resolve", lambda usage, team: Res())
    d = mod._auto_decide("t1", {"s": 1}, {})
    assert d["success"] is False and d["error"] == "jev_disabled" and d["choice"] is None
    # no choice, not confident: _auto_follow_up keeps its rule action ('explore')
    assert not (d.get("success") and (d.get("confidence") or 0) >= mod.AUTO_MIN_CONFIDENCE)


def test_companion_meter_stores_nothing_when_off(off):
    from features.companion.lib.meter import parse_answers
    out = decisions.decide(Res(), "s", {"q": {"type": "noul"}})
    assert not parse_answers(out).get("scores")


def test_freeze_and_review_write_no_rows_when_off(off, tmp_path):
    for mod in ("scripts.jev_freeze.decide", "scripts.jev_review.decide"):
        m = importlib.import_module(mod)
        (tmp_path / "rows.jsonl").write_text("")
        res = m.run_decide(str(tmp_path))
        assert res["disabled"] is True and res["decided"] == 0
        assert not (tmp_path / "decisions.jsonl").exists()


def test_pokemon_jev_choose_returns_empty_when_off(off):
    from shared.src.lib.ai import router
    spec = importlib.util.spec_from_file_location("game_pokemon", os.path.join(_root, "test_scripts", "game", "game_pokemon.py"))
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except BaseException as e:
        pytest.skip(f"game_pokemon not importable standalone: {e}")
    router.resolve_profile = lambda *a, **k: Res()
    assert mod.jev_choose("t1", {})("s", [{"id": "a", "facts": "x"}], "?") == {}


import importlib  # noqa: E402
