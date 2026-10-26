import hashlib
import json
from pathlib import Path

import pytest

from scripts.bench_atlas_router import (direct_eligible_tools, load_cases, load_runtime,
                                        parameter_oracle_issues, semantic_slot_cases,
                                        validate_oracle)

BM = Path("tests/benchmarks")
ORIG = BM / "atlas_routing_cases_original.jsonl"
V1 = BM / "atlas_routing_cases.jsonl"
V1_LOG = BM / "atlas_routing_oracle_changes.json"
V2 = BM / "atlas_routing_cases_v2_2026-10-16.jsonl"
V2_LOG = BM / "atlas_routing_oracle_v2_changes_2026-10-16.json"


def test_v2_oracle_validates_against_catalog():
    cases = load_cases(V2)
    assert len(cases) == 100 and len({c["id"] for c in cases}) == 100
    assert {c["expected_action"] for c in cases} == {"route", "clarify", "reject"}
    skills, catalog, _ = load_runtime()
    assert validate_oracle(cases, catalog, ORIG)


def test_v2_change_log_matches_v1_to_v2():
    v1 = load_cases(V1)
    v2 = load_cases(V2)
    log = json.loads(V2_LOG.read_text())
    by_id = {c["id"]: c for c in log["changes"]}
    assert log["prompt_count"] == 100
    assert log["original_sha256"] == hashlib.sha256(ORIG.read_bytes()).hexdigest()
    assert log["v1_sha256"] == hashlib.sha256(V1.read_bytes()).hexdigest()
    assert log["v2_sha256"] == hashlib.sha256(V2.read_bytes()).hexdigest()
    for before, after in zip(v1, v2):
        assert (before["id"], before["prompt"], before["category"]) == (
            after["id"], after["prompt"], after["category"])
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        assert changed == set(by_id.get(after["id"], {}).get("fields", {}))
        for key in changed:
            entry = by_id[after["id"]]["fields"][key]
            assert entry == {"before": before.get(key), "after": after.get(key)}


def test_v2_direct_rows_use_the_manager_direct_route():
    log = json.loads(V2_LOG.read_text())
    v2 = {c["id"]: c for c in load_cases(V2)}
    direct = direct_eligible_tools()
    for rid in log["required_model_extension_rows"]:
        row = v2[rid]
        assert row["expected_action"] == "route", rid
        tools = {row["expected_mcp_tool"]} | set(row.get("expected_execution_plan") or [])
        assert tools & direct, rid
    # every route row names a real skill (or the direct pseudo-skill) and a tool
    for row in v2.values():
        if row["expected_action"] == "route":
            assert row["expected_skill"] != "none", row["id"]
            assert row["expected_mcp_tool"] not in {"none", "clarify"}, row["id"]


def test_v1_oracle_and_original_are_unchanged():
    v1_log = json.loads(V1_LOG.read_text())
    assert v1_log["original_sha256"] == hashlib.sha256(ORIG.read_bytes()).hexdigest()
    assert v1_log["prompt_count"] == 100
    assert len(v1_log["changes"]) == 29


def test_v2_parameters_are_schema_args_or_labelled_slots():
    cases = load_cases(V2)
    skills, catalog, schemas = load_runtime()
    assert parameter_oracle_issues(cases, schemas) == []
    slotted = semantic_slot_cases(cases)
    assert len(slotted) == 16
    by_id = {c["id"]: c for c in cases}
    for item in slotted:
        case = by_id[item["id"]]
        assert set(case["expected_semantic_slots"]) == set(item["slots"])
        assert not (set(case["expected_parameters"]) & set(case["expected_semantic_slots"]))


def test_search_docs_schema_declares_query():
    skills, catalog, schemas = load_runtime()
    props = schemas["search_docs"]["input_schema"]["properties"]
    assert "query" in props


def test_direct_tool_set_covers_the_blocked_tools():
    direct = direct_eligible_tools()
    required = {"list_services", "propose_masterchief_op", "get_coverage_summary",
                "get_installed_apps", "load_testcase", "list_requirements", "get_transcript",
                "get_testcase_requirements", "create_requirement", "link_testcase_to_requirement",
                "get_execution_results"}
    assert required <= direct
    # blocked categories/prefixes are excluded
    assert not any(t.startswith("delete_") for t in direct)


def test_oracle_validator_accepts_a_direct_route_and_rejects_a_bogus_one():
    skills, catalog, _ = load_runtime()
    cases = load_cases(V2)
    first = cases[0]["id"]

    def with_first(**overrides):
        return [dict(c, **overrides) if c["id"] == first else c for c in cases]

    validate_oracle(with_first(expected_skill="direct", expected_mcp_tool="list_services",
                               expected_action="route", expected_parameters={}), catalog, ORIG)
    with pytest.raises(ValueError):
        validate_oracle(with_first(expected_skill="direct", expected_mcp_tool="not_a_real_tool",
                                   expected_action="route"), catalog, ORIG)
    with pytest.raises(ValueError):
        validate_oracle(with_first(expected_skill="device-control",
                                   expected_mcp_tool="list_services", expected_action="route"),
                        catalog, ORIG)
