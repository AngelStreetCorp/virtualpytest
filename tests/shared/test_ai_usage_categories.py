"""TASK-87 round 2: usage -> category (one mapping), caller derivation, overview split useful / wasted / saved (pure)."""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from shared.src.lib.ai import usage_caller, usage_report, usage_view, usages  # noqa: E402


def test_every_catalogue_usage_has_exactly_one_listed_category():
    core = [k for k in usages.USAGES if not k.startswith(("vision.companion", "text.web.companion", "text.companion",
                                                          "text.decision.companion"))]
    assert core, "catalogue is empty"
    for key in core:
        assert key in usages._CATEGORY_BY_KEY, f"{key} has no category: add it to usages._CATEGORY_BY_KEY"
        assert usages.category_of(key) in usages.CATEGORIES
    assert set(usages._CATEGORY_BY_KEY.values()) <= set(usages.CATEGORIES)
    assert all(k in usages.USAGES for k in usages._CATEGORY_BY_KEY), "category table lists a usage that does not exist"


def test_dynamic_and_feature_keys_follow_their_parent():
    assert usages.category_of("agent.atlas.skill.create_script") == "ask_ai"
    assert usages.category_of("agent.somebody") == "other"
    assert usages.category_of("text.web.companion") == "web_lookup"
    assert usages.category_of("never.heard.of") == "other"


def test_caller_is_the_agent_then_the_script_then_the_process():
    c = usage_caller.caller_of
    assert c({"usage_key": "agent.atlas", "origin": "chat"}) == "agent:atlas"
    assert c({"usage_key": "analyzer.sherlock", "origin": "background"}) == "agent:sherlock"
    assert c({"usage_key": "agent.atlas.skill.x", "origin": "chat"}) == "agent:atlas"
    assert c({"usage_key": "vision.banner", "origin": "script", "script_name": "game_2048.py"}) == "script:game_2048.py"
    assert c({"usage_key": "vision.alert_triage", "origin": "monitoring"}) == "process:vpt-discard-incidents"
    assert c({"usage_key": "text.transcript", "origin": "monitoring"}) == "process:vpt-monitor"
    assert c({"usage_key": "vision.ask", "origin": "ui"}) == "other:ui"
    assert c({"usage_key": "vision.ask"}) == "other:unknown"


def row(**kw):
    base = {"bucket": "2026-10-16T10:00:00+00:00", "usage_key": "vision.banner", "endpoint": "or", "profile": "p",
            "calls": 10, "errors": 0, "fallbacks": 0, "total_ms": 1000, "tokens_in": 100, "tokens_out": 50,
            "origin": "monitoring", "error_type": ""}
    base.update(kw)
    return base


def test_overview_splits_useful_wasted_and_saved():
    rows = [row(calls=8, cost=0.8, priced_calls=8),
            row(calls=2, errors=2, error_type="empty_answer", cost=0.2, priced_calls=2),
            row(usage_key="text.web", calls=0, avoided=5, origin="ui")]
    ov = usage_view.overview(rows)
    by = {c["key"]: c for c in ov["categories"]}
    sr = by["screen_recognition"]
    assert (sr["useful"], sr["wasted"], sr["saved"]) == (8, 2, 0)
    assert sr["cost_wasted"] == 0.2 and sr["cost_useful"] == 0.8
    assert by["web_lookup"]["saved"] == 5
    assert ov["totals"]["saved"] == 5 and {c["key"] for c in ov["callers"]} == {"process:vpt-monitor", "other:ui"}
    assert ov["callers"][0]["categories"] == {"screen_recognition": 10}


def test_result_filter_and_new_groups():
    rows = [row(calls=3), row(calls=2, errors=2, error_type="timeout")]
    failed = usage_report.aggregate(rows, "category", filters={"result": "failed"})
    assert [r["key"] for r in failed["rows"]] == ["screen_recognition"] and failed["totals"]["calls"] == 2
    pair = usage_report.aggregate(rows, "category_caller")
    assert pair["rows"][0]["key"] == "screen_recognition|process:vpt-monitor"
    assert pair["rows"][0]["profile_last"]["p"]
