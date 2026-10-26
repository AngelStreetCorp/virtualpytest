import json
from pathlib import Path

import scripts.bench_atlas_production as adapter
from scripts.bench_atlas_production import (SessionContext, decide, extract_semantic_slots,
                                            resolve_named_targets, run, slot_metric)
from scripts.bench_atlas_router import load_cases, load_runtime
from backend_server.src.agent.core.tool_bridge import ToolBridge

DATASET = Path("tests/benchmarks/atlas_routing_cases_v2_2026-10-16.jsonl")


def test_production_adapter_runs_offline_with_zero_executions(tmp_path):
    cases = load_cases(DATASET)
    rows, metrics = run(cases, tmp_path)
    assert metrics["cases"] == 100
    assert metrics["real_executions"] == 0
    assert set(metrics["outcomes"]) <= {"route", "clarify", "reject", "planner"}
    # planner_handoff is computed, not a constant marker
    assert 0 < metrics["planner_handoff_rate"] <= 1
    assert metrics["allowed_tools"] > 0
    assert metrics["parameter_oracle_issues"] == 0
    assert len((tmp_path / "results.jsonl").read_text().splitlines()) == 100
    assert len(rows) == 100


def test_planner_outcomes_carry_the_direct_tool_payload():
    cases = {c["id"]: c for c in load_cases(DATASET)}
    skills, catalog, schemas = load_runtime()
    ctx = SessionContext(team_id="bench-team")
    router = adapter._RouterShim(ctx.allowed_tools)
    row = decide(cases["ATLAS-012"], skills, catalog, schemas, ctx, router)
    assert row["outcome"] == "planner"
    assert "get_coverage_summary" in row["planner_candidates"]
    assert row["planner_handoff"] is True


def test_route_outcome_is_dispatched_to_a_mock_not_toolbridge(tmp_path, monkeypatch):
    cases = load_cases(DATASET)
    skills, catalog, schemas = load_runtime()
    ctx = SessionContext(team_id="bench-team")
    router = adapter._RouterShim(ctx.allowed_tools)
    # force the auto-load rule to pick a real skill so a tool can resolve
    monkeypatch.setattr(adapter, "algorithm_skill", lambda *a, **k: ("manage-campaign", [], []))
    case = {"id": "SYNTH", "prompt": "List the campaigns for this team", "category": "direct_skill"}

    def boom(*a, **k):
        raise AssertionError("real ToolBridge.execute must not be called")

    monkeypatch.setattr(ToolBridge, "execute", boom)
    row = decide(case, skills, catalog, schemas, ctx, router)
    assert row["outcome"] == "route", row
    assert row["dispatch"] and row["dispatch"]["tool"] == "list_campaigns"
    assert row["dispatch"]["validated"] is True
    assert row["dispatch"]["executed"] is False and row["dispatch"]["mocked"] is True
    assert row["planner_handoff"] is False


def test_dry_dispatch_validates_without_executing(monkeypatch):
    from scripts.bench_atlas_production import dry_dispatch

    def boom(*a, **k):
        raise AssertionError("dry_dispatch must never execute a tool")

    monkeypatch.setattr(ToolBridge, "execute", boom)
    schema = {"input_schema": {"properties": {"device_id": {}, "host_name": {}}, "required": ["device_id"]}}
    ok = dry_dispatch("capture_screenshot", {"device_id": "tv-1"}, schema, {"capture_screenshot"})
    assert ok["validated"] is True and ok["executed"] is False and ok["mocked"] is True
    bad = dry_dispatch("capture_screenshot", {}, schema, {"capture_screenshot"})
    assert bad["validated"] is False and bad["reason"] == "schema_invalid" and bad["missing"] == ["device_id"]
    denied = dry_dispatch("capture_screenshot", {"device_id": "tv-1"}, schema, set())
    assert denied["validated"] is False and denied["reason"] == "unauthorized_tool"


def test_semantic_slot_metric_is_separate_and_bounded():
    cases = load_cases(DATASET)
    metric, rows = slot_metric(cases)
    assert metric["cases"] == 16
    assert metric["slots"] == 16
    assert 0.0 <= metric["exact_accuracy"] <= 1.0
    assert len(rows) == 16
    assert extract_semantic_slots("Open Netflix on device A")["app"] == "Netflix"


def test_stable_across_runs(tmp_path):
    cases = load_cases(DATASET)
    _, first = run(cases, tmp_path / "a")
    _, second = run(cases, tmp_path / "b")
    assert first["outcomes"] == second["outcomes"]
    assert first["real_executions"] == second["real_executions"] == 0


def test_named_targets_are_resolved_from_the_fixture():
    ctx = SessionContext(team_id="bench-team")
    named = resolve_named_targets("check whether the Samsung TV is online", ctx.devices, ctx.server_hosts)
    assert named and named[0]["device_id"] == "tv-samsung-1"
    assert named[0]["host_name"] == "host-1"
    assert named[0]["on_server"] is True


def test_target_identity_is_available_in_every_row(tmp_path):
    cases = load_cases(DATASET)
    rows, metrics = run(cases, tmp_path)
    assert metrics["target_identity_available"] is True
    assert metrics["named_targets_resolved"] >= 1
    by_id = {r["id"]: r for r in rows}
    # ATLAS-003 names the Samsung TV; the runner now carries its device_id
    assert by_id["ATLAS-003"]["target_resolved"] is True
    assert any(t.get("device_id") for t in by_id["ATLAS-003"]["named_targets"])
