"""TASK-87 round 2: usage -> category (one mapping), caller derivation, overview split useful / wasted / saved (pure)."""
import os
import sys

import pytest

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
    assert c({"usage_key": "text.report", "origin": "background"}) == "job:Fleet health report"
    assert c({"usage_key": "vision.banner", "origin": "eval"}) == f"eval:{usages.short_label('vision.banner')}"
    assert c({"usage_key": "vision.ask", "origin": "api"}) == "other:api"


def test_human_model_names_and_incident_rows():
    assert usage_view.model_label("minimax-vlm") == "MiniMax VLM"
    assert usage_view.model_label("jev-1.13", "jev") == "Jev 1.13"
    assert usage_view.model_label(None, "minimax-vlm-minimax-vlm") == "MiniMax VLM"
    rows = [row(usage_key="vision.alert_triage", host_name="h1", device_id="d1", ref_type="alert", ref_kind="freeze",
                calls=4, errors=1)]
    inc = usage_view.overview(rows)["categories"][0]["incidents"]
    assert [(i["host"], i["device"], i["kind"], i["useful"], i["wasted"]) for i in inc] == [("h1", "d1", "freeze", 3, 1)]
    grouped = usage_report.aggregate(rows, "incident")
    assert grouped["rows"][0]["key"] == "freeze"


def test_a_usage_without_a_category_is_its_own_row_never_other():
    assert usages.page_category("agent.browser") == "usage:agent.browser"
    assert usages.page_category("text.report") == "usage:text.report"
    assert usages.page_category("vision.banner") == "screen_recognition"


def test_benchmark_and_proof_calls_are_one_model_tests_row():
    for key in ("eval:text.decision.manager", "eval:vision.banner", "proof:chain", "test:text"):
        assert usages.page_category(key) == "model_tests"
    assert usage_caller.category_label("usage:agent.browser") == "Browser agent"
    assert usage_caller.category_label("usage:agent.somebody") == "Somebody"
    assert usage_caller.category_label("ask_ai") is None
    rows = [{"bucket": "2026-10-16T10:00:00+00:00", "usage_key": "agent.browser", "calls": 3, "origin": "script"}]
    ov = usage_view.overview(rows)
    assert ov["categories"][0]["key"] == "usage:agent.browser" and ov["categories"][0]["label"] == "Browser agent"
    assert ov["category_labels"] == {"usage:agent.browser": "Browser agent"}


def test_wasted_is_failed_unparseable_and_cut_off_and_a_refusal_costs_nothing():
    rows = [row(calls=10, errors=1, parse_total=10, parse_ok_n=8, truncated=1, cost=1.0, priced_calls=10),
            row(calls=5, errors=5, error_type="no_credit", cost=0.5, priced_calls=5)]
    t = usage_view.overview(rows)["totals"]
    assert t["wasted"] == 4 + 5 and t["useful"] == 6  # 1 failed + 2 unparseable + 1 cut off, and 5 refused
    assert t["cost_wasted"] == pytest.approx(0.4)  # the refused calls were not billed: not money wasted
    capped = usage_view.wasted_calls(row(calls=3, errors=3, parse_total=3, parse_ok_n=0, truncated=3))
    assert capped == 3


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
    sources = by["screen_recognition"]["sources"]
    assert [(x["key"], x["useful"], x["wasted"]) for x in sources] == [("process:vpt-monitor", 8, 2)]


def test_result_filter_and_new_groups():
    rows = [row(calls=3), row(calls=2, errors=2, error_type="timeout")]
    failed = usage_report.aggregate(rows, "category", filters={"result": "failed"})
    assert [r["key"] for r in failed["rows"]] == ["screen_recognition"] and failed["totals"]["calls"] == 2
    pair = usage_report.aggregate(rows, "category,caller")
    assert pair["rows"][0]["key"] == "screen_recognition|process:vpt-monitor"
    assert pair["rows"][0]["parts"] == ["screen_recognition", "process:vpt-monitor"]
    with pytest.raises(ValueError):
        usage_report.aggregate(rows, "category,category")
    with pytest.raises(ValueError):
        usage_report.aggregate(rows, "category,caller,model")
    assert pair["rows"][0]["profile_last"]["p"]


def test_model_names_keep_known_words_glued_to_their_version():
    from shared.src.lib.ai.usage_view import model_label
    assert model_label("qwen/qwen3-vl-8b-instruct") == "Qwen3 VL 8b Instruct"
    assert model_label("minimax-vlm") == "MiniMax VLM"
    assert model_label("typesafe/jev-1.13") == "Jev 1.13"
