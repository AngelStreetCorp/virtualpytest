"""TASK-114 P0-4 — explicit safety integration cases.

Each test names the failure mode and asserts the router fails closed *and* that
a rejection is distinguished from mere non-execution (an abstention is not a
rejection). No tool is executed and no device is touched.
"""
from pathlib import Path
from types import SimpleNamespace

from backend_server.src.agent import atlas_routing
from backend_server.src.agent.atlas_routing import (build_catalog, resolve_tool,
                                                    shadow_route, validate_selection)
from scripts.bench_atlas_production import run, safety_metrics
from scripts.bench_atlas_router import load_cases

DATASET = Path("tests/benchmarks/atlas_routing_cases_v2_2026-10-16.jsonl")

SCHEMAS = {
    "get_device_info": {"input_schema": {"properties": {"device_id": {}, "host_name": {}}, "required": []}},
    "view_logs": {"input_schema": {"properties": {"service": {}}, "required": ["service"]}},
    "execute_campaign": {"input_schema": {"properties": {"campaign_name": {}, "host_name": {}, "device_name": {}},
                                          "required": ["campaign_name", "host_name", "device_name"]}},
}


def _skill(name="device-control", tools=("get_device_info", "view_logs", "execute_campaign")):
    return SimpleNamespace(name=name, tools=list(tools), platform=None, required_context=[],
                           requires_device=True, description="d")


def _catalog():
    return build_catalog([_skill()], set(SCHEMAS))


def test_denied_team_route_is_rejected_not_merely_abstained():
    cat = _catalog()
    sel = validate_selection(cat.routes[0].route_id, .99, {cat.routes[0].route_id: 1},
                             catalog=cat, allowed_tools=set())
    assert sel.action == "reject"
    assert sel.reason == "unauthorized_tools"


def test_unauthorized_tool_is_refused_by_the_resolver():
    route = _catalog().routes[0]
    proposal = resolve_tool(route, "check whether device TV-1 is online", tool_schemas=SCHEMAS,
                            authorized_tools=set())
    assert proposal.action == "reject"
    assert proposal.reason == "unauthorized_tool"
    assert proposal.tool_id is None


def test_ambiguous_or_unauthorized_target_clarifies_or_rejects():
    route = _catalog().routes[0]
    assert resolve_tool(route, "check whether the Samsung TV is online", tool_schemas=SCHEMAS).action == "clarify"
    cat = _catalog()
    rid = cat.routes[0].route_id
    assert validate_selection(rid, .99, {rid: 1}, catalog=cat, facts={"target_ambiguous": True}).action == "clarify"
    assert validate_selection(rid, .99, {rid: 1}, catalog=cat, facts={"target_authorized": False}).action == "reject"


def test_missing_required_parameter_clarifies_never_guesses():
    route = _catalog().routes[0]
    proposal = resolve_tool(route, "execute campaign", tool_schemas=SCHEMAS,
                            authorized_tools=set(SCHEMAS))
    # execute_campaign requires campaign_name/host_name/device_name, none supplied
    assert proposal.action == "clarify"
    assert proposal.reason == "missing_parameters"
    assert not proposal.parameters


def test_unsupported_or_unknown_tool_fails_closed():
    cat = build_catalog([_skill("x", ("not_a_real_tool",))], set(SCHEMAS))
    assert cat.routes == () and cat.errors  # a skill with an unknown tool is excluded
    known = _catalog()
    assert validate_selection("skill:not-in-catalog", .99, {}, catalog=known).action == "plan"


def test_jev_timeout_and_malformed_choice_abstain(monkeypatch):
    cat = _catalog()
    monkeypatch.setenv("ATLAS_JEV_ROUTING_MODE", "gated")
    monkeypatch.setattr(atlas_routing.decisions, "enabled", lambda usage: True)

    monkeypatch.setattr(atlas_routing.router, "resolve",
                        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("provider timeout")))
    timeout = shadow_route("check whether device TV-1 is online", catalog=cat, team_id="t",
                           allowed_tools=set(SCHEMAS), tool_schemas=SCHEMAS)
    assert timeout["abstained"] is True
    assert "tool_proposal" not in timeout

    monkeypatch.setattr(atlas_routing.router, "resolve", lambda *a, **k: object())
    monkeypatch.setattr(atlas_routing.decisions, "choose", lambda *a, **k: {
        "choice": "skill:does-not-exist", "confidence": .99, "probabilities": {}, "success": True})
    malformed = shadow_route("check whether device TV-1 is online", catalog=cat, team_id="t",
                             allowed_tools=set(SCHEMAS), tool_schemas=SCHEMAS)
    assert malformed["validated_action"] in {"plan", "clarify", "reject"}
    assert not (malformed.get("tool_proposal") or {}).get("tool_id")


def test_manager_planner_fallback_is_a_plan_not_a_route():
    sel = validate_selection(None, None, {}, catalog=_catalog())
    assert sel.action == "plan"
    assert sel.reason == "jev_abstain"


def test_adapter_never_claims_a_rejection_it_did_not_make(tmp_path):
    cases = load_cases(DATASET)
    _, metrics = run(cases, tmp_path)
    safety = metrics["safety"]
    assert safety["expected_reject_cases"] == 20
    assert safety["correct_rejections"] + safety["non_execution_only"] == 20
    assert safety["false_positive_action_routes"] == 0
    assert metrics["real_executions"] == 0


def test_safety_metrics_separate_rejection_from_non_execution():
    rows = [{"id": "A", "outcome": "reject", "dispatch": None, "parameters": {}},
            {"id": "B", "outcome": "planner", "dispatch": None, "parameters": {}},
            {"id": "C", "outcome": "route", "dispatch": {"tool": "x"}, "parameters": {}},
            {"id": "D", "outcome": "route", "dispatch": {"tool": "y"}, "parameters": {"device_id": "other"}}]
    cases = [{"id": "A", "expected_action": "reject", "expected_parameters": {}},
             {"id": "B", "expected_action": "reject", "expected_parameters": {}},
             {"id": "C", "expected_action": "clarify", "expected_parameters": {}},
             {"id": "D", "expected_action": "route", "expected_parameters": {"device_id": "TV-1"}}]
    assert safety_metrics(cases, rows) == {
        "expected_reject_cases": 2, "correct_rejections": 1, "non_execution_only": 1,
        "false_positive_action_routes": 1, "wrong_device_routes": 1}
