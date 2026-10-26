import json
from pathlib import Path

from scripts.bench_atlas_router import (load_cases, load_runtime, metrics,
                                        parameter_oracle_issues, predict, run, score, validate_oracle)
from backend_server.src.agent.skills.skill_loader import SkillLoader
from backend_server.src.agent.skills.skill_registry import get_skill_registry
from backend_server.src.agent.atlas_routing import build_catalog


def test_dataset_has_100_unique_cases():
    cases = load_cases(Path("tests/benchmarks/atlas_routing_cases.jsonl"))
    assert len(cases) == 100
    assert len({c["id"] for c in cases}) == 100
    assert {c["expected_action"] for c in cases} == {"route", "clarify", "reject"}
    skills, catalog, _ = load_runtime()
    assert validate_oracle(cases, catalog, Path("tests/benchmarks/atlas_routing_cases_original.jsonl"))


def test_oracle_change_log_preserves_original_labels():
    original = load_cases(Path("tests/benchmarks/atlas_routing_cases_original.jsonl"))
    corrected = load_cases(Path("tests/benchmarks/atlas_routing_cases.jsonl"))
    changes = json.loads(Path("tests/benchmarks/atlas_routing_oracle_changes.json").read_text())
    by_id = {change["id"]: change for change in changes["changes"]}
    assert len(by_id) == 29
    assert changes["prompt_count"] == 100
    import hashlib
    assert changes["original_sha256"] == hashlib.sha256(
        Path("tests/benchmarks/atlas_routing_cases_original.jsonl").read_bytes()).hexdigest()
    for before, after in zip(original, corrected):
        assert (before["id"], before["prompt"], before["category"]) == (
            after["id"], after["prompt"], after["category"])
        changed_fields = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
        assert changed_fields == set(by_id.get(after["id"], {}).get("fields", {}))
        for key in changed_fields:
            entry = by_id[after["id"]]["fields"][key]
            assert entry == {"before": before.get(key), "after": after.get(key)}


def test_metrics_count_unsafe_routes():
    row = {"expected": {"category": "safety"}, "actual": {"action": "route", "routing_level": "algorithm"},
           "scores": {"route": False, "intent": None, "skill": True, "tool": True,
                      "parameters": True, "action": False, "unsafe": True, "false_positive_action": True},
           "jev_invoked": False}
    result = metrics([row], [2.0])
    assert result["cases"] == 1
    assert result["unsafe_routing_errors"] == 1
    assert result["p50_latency_ms"] == 2.0


def test_prediction_does_not_depend_on_expected_labels():
    cases = load_cases(Path("tests/benchmarks/atlas_routing_cases.jsonl"))
    skills, catalog, schemas = load_runtime()
    for case in cases:
        before = predict(case["prompt"], "algorithm", skills, catalog, schemas, set(schemas), None, False)
        altered = dict(case, expected_skill="none", expected_mcp_tool="none",
                       expected_action="reject", category="safety")
        after = predict(altered["prompt"], "algorithm", skills, catalog, schemas, set(schemas), None, False)
        assert before == after, case["id"]


def test_benchmark_never_executes_mcp(monkeypatch):
    from backend_server.src.agent.core.tool_bridge import ToolBridge
    monkeypatch.setattr(ToolBridge, "execute", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("benchmark executed an MCP tool")))
    skills, catalog, schemas = load_runtime()
    case = load_cases(Path("tests/benchmarks/atlas_routing_cases.jsonl"))[0]
    rows, _ = run([case], "algorithm", skills, catalog, schemas, None, False)
    assert rows[0]["mcp_executions"] == 0
    assert rows[0]["dry_run"] is True


def test_named_device_route_without_resolved_target_is_unsafe():
    case = {"expected_intent": "device.status", "expected_skill": "device-control",
            "expected_mcp_tool": "get_device_info", "expected_action": "route",
            "expected_parameters": {"device_name": "Samsung TV"}}
    actual = {"intent": None, "skill": "device-control", "tool": "get_device_info",
              "action": "route", "parameters": {}}
    assert score(case, actual)["unsafe"] is True


def test_loaded_skill_catalog_has_no_unknown_mcp_tools():
    SkillLoader.reload()
    registry = get_skill_registry()
    catalog = build_catalog(SkillLoader.get_all_skills().values(), set(registry.get_all_skills()))
    assert catalog.errors == ()


def test_parameter_oracle_reports_non_schema_slots():
    cases = load_cases(Path("tests/benchmarks/atlas_routing_cases.jsonl"))
    _, _, schemas = load_runtime()
    issues = parameter_oracle_issues(cases, schemas)
    assert any(item["id"] == "ATLAS-003" and "device_name" in item["unknown_parameter_keys"]
               for item in issues)
