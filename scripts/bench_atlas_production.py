#!/usr/bin/env python3
"""TASK-114 P0-3 — production-path dry-run adapter.

Unlike ``bench_atlas_router.py`` (which stops at the classifier/proposal), this
adapter drives the *selection path the manager actually uses* and records what
would happen next, without ever executing a tool:

* ``SkillLoader.rank_skills`` — the trigger matcher (same call as manager.py:1158)
* the production auto-load rule — top skill only when >= 2 triggers match
  (manager.py:1192-1203)
* ``build_catalog`` / ``resolve_tool`` — the route + tool resolver
* ``QAManagerAgent._select_router_tools_for_message`` — the **direct-tool
  payload** offered to the planner in router mode (the same function Atlas runs)

Outcomes per prompt:
  route    — an algorithm skill loads and a schema-valid tool resolves
  clarify  — a skill resolved but the resolver needs more information
  planner  — no algorithm skill: the Atlas planner decides, and this adapter
             records the real direct-tool candidates it would be handed
  reject   — the resolver refuses an unsafe request

The planner's *final* tool choice (skill vs direct vs clarify) is made by the
LLM planner and is NOT in scope here; ``planner_handoff`` is therefore a real
computed decision, and ``planner_candidates`` is the evidence a later, LLM-backed
run needs. ``ToolBridge.execute`` is patched to raise, so a real dispatch can
never happen in this process.

No Jev call, no routing enablement, no device execution.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend_server.src.agent.atlas_routing import build_catalog, resolve_tool, should_escalate_to_jev
from backend_server.src.agent.core.manager import QAManagerAgent
from backend_server.src.agent.core.tool_bridge import ToolBridge
from backend_server.src.agent.skills.skill_loader import SkillLoader
from backend_server.src.agent.skills.skill_registry import get_skill_registry
from backend_server.src.lib.analytics.named_devices import detect_named_devices

from scripts.bench_atlas_router import direct_eligible_tools, load_cases, load_runtime

TRIGGER_AUTOLOAD_THRESHOLD = 2  # manager.py:1196
DEFAULT_TARGET_FIXTURE = Path("tests/benchmarks/atlas_targets_fixture.json")


def load_target_fixture(path=DEFAULT_TARGET_FIXTURE):
    data = json.loads(Path(path).read_text())
    return data.get("devices", []), data.get("server_hosts", []), data.get("team_id")


class _RouterShim:
    """Minimal stand-in for QAManagerAgent so the production direct-tool selector
    can be reused without constructing the full agent (which needs `agent.registry`)."""

    agent_id = 'assistant'
    _ATLAS_ROUTER_KEYWORD_GATED = QAManagerAgent._ATLAS_ROUTER_KEYWORD_GATED
    _ATLAS_ROUTER_CATEGORY_HINTS = QAManagerAgent._ATLAS_ROUTER_CATEGORY_HINTS
    _ATLAS_ROUTER_CATEGORY_CORE_TOOLS = QAManagerAgent._ATLAS_ROUTER_CATEGORY_CORE_TOOLS
    _ATLAS_ROUTER_TOOL_PREREQUISITES = QAManagerAgent._ATLAS_ROUTER_TOOL_PREREQUISITES
    _ATLAS_ROUTER_FALLBACK_TOOLS = QAManagerAgent._ATLAS_ROUTER_FALLBACK_TOOLS

    def __init__(self, router_tool_names):
        self.router_tool_names = sorted(router_tool_names)
        self._tokenize_router_query = types.MethodType(QAManagerAgent._tokenize_router_query, self)

    def select(self, message):
        return QAManagerAgent._select_router_tools_for_message(self, message)


class SessionContext:
    """The session-specific inputs the runner must supply instead of 'all tools'."""

    def __init__(self, team_id=None, platform=None, fixture=DEFAULT_TARGET_FIXTURE):
        self.devices, self.server_hosts, fixture_team = load_target_fixture(fixture)
        self.team_id = team_id or fixture_team or "bench-team"
        self.platform = platform
        self.available_skills = [s.name for s in SkillLoader.get_all_skills().values()]
        self.allowed_tools = set(direct_eligible_tools())


def dry_dispatch(tool_id, params, schema, allowed_tools):
    """Validate a proposed tool call *without executing it* (the dry-run ToolBridge
    handoff Gate A asks for). Returns a mocked dispatch record; it never calls
    ``ToolBridge.execute`` and never reaches a host or device.
    """
    record = {"tool": tool_id, "parameters": dict(params or {}), "mocked": True, "executed": False}
    if allowed_tools is not None and tool_id not in allowed_tools:
        return {**record, "validated": False, "reason": "unauthorized_tool"}
    spec = (schema or {}).get("input_schema") or {}
    props = set(spec.get("properties") or {})
    required = set(spec.get("required") or [])
    unknown = sorted(set(params or {}) - props)
    missing = sorted(required - set(params or {}))
    if unknown or missing:
        return {**record, "validated": False, "reason": "schema_invalid",
                "unknown": unknown, "missing": missing}
    return {**record, "validated": True, "reason": "validated"}


def resolve_named_targets(prompt, devices, server_hosts):
    """Session target identity: map the devices a prompt names to their real
    device_id/host_name/platform, using the production ``detect_named_devices``.

    This is the 'target identity context' Gate A asks the runner to supply; it
    never touches a device.
    """
    named = detect_named_devices(prompt, devices, server_hosts)
    by_name = {d["device_name"]: d for d in devices}
    return [{**by_name[n["name"]], "on_server": n.get("on_server", True)}
            for n in named if n["name"] in by_name]


def algorithm_skill(prompt, skills, available_skills, platform):
    """Production auto-load decision: top-ranked skill only at >= 2 trigger hits."""
    ranked = SkillLoader.rank_skills(prompt, available_skills, platform)
    candidates = [{"skill": s.name, "score": score, "trigger_hits": hits} for s, score, hits in ranked]
    if not ranked:
        return None, candidates, ranked
    top, _score, hits = ranked[0]
    return (top.name if hits >= TRIGGER_AUTOLOAD_THRESHOLD else None), candidates, ranked


def decide(case, skills, catalog, schemas, context, router):
    prompt = case["prompt"]
    skill_id, candidates, ranked = algorithm_skill(prompt, skills, context.available_skills, context.platform)
    named = resolve_named_targets(prompt, context.devices, context.server_hosts)
    base = {"id": case["id"], "prompt": prompt, "category": case["category"],
            "algorithm_skill": skill_id, "algorithm_candidates": candidates,
            "named_targets": named, "target_resolved": bool(named) and all(d.get("device_id") for d in named),
            "escalate_to_jev": should_escalate_to_jev(ranked)}

    if skill_id:
        route = next((r for r in catalog.routes if r.skill_id == skill_id), None)
        proposal = (resolve_tool(route, prompt, tool_schemas=schemas, authorized_tools=context.allowed_tools)
                    if route else None)
        action = proposal.action if proposal else "clarify"
        if action == "route" and proposal.tool_id:
            dispatch = dry_dispatch(proposal.tool_id, proposal.parameters,
                                    schemas.get(proposal.tool_id), context.allowed_tools)
            if not dispatch["validated"]:
                return {**base, "outcome": "clarify", "skill": skill_id, "tool": "none",
                        "parameters": {}, "planner_handoff": False, "planner_candidates": [],
                        "reason": dispatch["reason"], "dispatch": None}
            return {**base, "outcome": "route", "skill": skill_id, "tool": proposal.tool_id,
                    "parameters": proposal.parameters, "planner_handoff": False,
                    "planner_candidates": [], "reason": proposal.reason, "dispatch": dispatch}
        return {**base, "outcome": action if action in ("clarify", "reject") else "clarify",
                "skill": skill_id, "tool": "none", "parameters": {}, "planner_handoff": False,
                "planner_candidates": [], "reason": proposal.reason if proposal else "no_route",
                "dispatch": None}

    # No algorithm skill: the Atlas planner is offered the direct-tool payload.
    offered = router.select(prompt)
    return {**base, "outcome": "planner", "skill": "direct", "tool": "none", "parameters": {},
            "planner_handoff": True, "planner_candidates": offered,
            "reason": "no_algo_skill_planner_decides", "dispatch": None}


# --- semantic-slot extractor (the separate metric P0-2 asked for) ---------------
_QUOTED = re.compile(r"'([^']+)'|\"([^\"]+)\"")


def extract_semantic_slots(prompt):
    """Best-effort, deterministic extraction of the labelled semantic slots.

    Deliberately simple: this is the *plumbing* for a separate metric, not a
    tuned extractor. It returns a subset of {device_name, host_name, app}.
    """
    text = prompt.lower()
    slots = {}
    m = re.search(r'\bdevice\s+([a-z0-9][a-z0-9_.-]*)', text)
    if m:
        slots['device_name'] = m.group(1)
    m = re.search(r'\bhost\s+([a-z0-9][a-z0-9_.-]*)', text)
    if m:
        slots['host_name'] = m.group(1)
    m = re.search(r'\b(?:open|launch|switch to|use)\s+([A-Z][A-Za-z0-9]+)', prompt, re.IGNORECASE)
    if m:
        slots['app'] = m.group(1)
    for a, b in _QUOTED.findall(prompt):
        slots.setdefault('device_name', a or b)
    return slots


def slot_metric(cases):
    total = matched = produced = 0
    rows = []
    for case in cases:
        expected = case.get("expected_semantic_slots") or {}
        if not expected:
            continue
        got = extract_semantic_slots(case["prompt"])
        for key, want in expected.items():
            total += 1
            if key in got:
                produced += 1
                if str(got[key]).lower() == str(want).lower():
                    matched += 1
        rows.append({"id": case["id"], "expected": expected, "extracted": got})
    return {"cases": len(rows), "slots": total, "produced": produced, "matched": matched,
            "produced_rate": produced / total if total else None,
            "exact_accuracy": matched / total if total else None}, rows


def safety_metrics(cases, rows):
    """Measure rejection separately from mere non-execution (P0-4).

    A "correct rejection" is an executable-refusing outcome for a prompt the
    oracle expects to reject. A prompt that neither routes nor rejects is
    "non-execution only" — safer than acting, but not the same as rejecting.
    """
    by_id = {r["id"]: r for r in rows}
    expected_reject = [c for c in cases if c["expected_action"] == "reject"]
    correct = non_exec = false_pos = wrong_device = 0
    for case in cases:
        row = by_id[case["id"]]
        routed = row["outcome"] == "route" and bool(row.get("dispatch"))
        if case["expected_action"] == "reject":
            if row["outcome"] == "reject":
                correct += 1
            elif not routed:
                non_exec += 1
        elif case["expected_action"] != "route" and routed:
            false_pos += 1
        exp_target = (case["expected_parameters"].get("device_id")
                      or (case.get("expected_semantic_slots") or {}).get("device_name"))
        if routed and exp_target:
            got = row.get("parameters") or {}
            if got.get("device_id") != exp_target and got.get("device_name") != exp_target:
                wrong_device += 1
    return {
        "expected_reject_cases": len(expected_reject),
        "correct_rejections": correct,
        "non_execution_only": non_exec,
        "false_positive_action_routes": false_pos,
        "wrong_device_routes": wrong_device,
    }


def run(cases, output: Path):
    skills, catalog, schemas = load_runtime()
    context = SessionContext(team_id="bench-team", platform=None)
    router = _RouterShim(context.allowed_tools)

    real_execute = ToolBridge.execute
    calls = {"execute": 0}

    def guard(*_a, **_k):  # any real dispatch is a failure
        calls["execute"] += 1
        raise AssertionError("production adapter attempted a real ToolBridge.execute")

    ToolBridge.execute = guard
    try:
        rows = [decide(case, skills, catalog, schemas, context, router) for case in cases]
    finally:
        ToolBridge.execute = real_execute

    slot, slot_rows = slot_metric(cases)
    outcome_counts = {}
    for row in rows:
        outcome_counts[row["outcome"]] = outcome_counts.get(row["outcome"], 0) + 1
    dispatched = [r for r in rows if r["dispatch"]]
    algorithm_skill_matches = sum(1 for r, c in zip(rows, cases)
                                  if r["algorithm_skill"] and r["algorithm_skill"] == c["expected_skill"])
    route_expected_but_planner = sum(1 for r, c in zip(rows, cases)
                                     if c["expected_action"] == "route" and r["outcome"] == "planner")
    metrics = {
        "cases": len(rows),
        "outcomes": outcome_counts,
        "planner_handoff_rate": sum(r["planner_handoff"] for r in rows) / len(rows),
        "mocked_dispatches": len(dispatched),
        "real_executions": calls["execute"],
        "allowed_tools": len(context.allowed_tools),
        "algorithm_skill_matches_expected": algorithm_skill_matches,
        "route_expected_but_planner": route_expected_but_planner,
        "named_targets_resolved": sum(1 for r in rows if r["named_targets"]),
        "target_identity_available": True,
        "semantic_slots": slot,
        "safety": safety_metrics(cases, rows),
        "parameter_oracle_issues": None,
    }
    from scripts.bench_atlas_router import parameter_oracle_issues
    metrics["parameter_oracle_issues"] = len(parameter_oracle_issues(cases, schemas))

    output.mkdir(parents=True, exist_ok=True)
    (output / "results.jsonl").write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n')
    (output / "metrics.json").write_text(json.dumps(metrics, indent=1) + '\n')
    (output / "semantic_slots.json").write_text(json.dumps(slot_rows, ensure_ascii=False, indent=1) + '\n')
    return rows, metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("tests/benchmarks/atlas_routing_cases_v2_2026-10-16.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("reports/atlas-routing-benchmark/p03-production-dry-run"))
    args = parser.parse_args()
    cases = load_cases(args.dataset)
    _rows, metrics = run(cases, args.output)
    print(json.dumps(metrics, indent=1))


if __name__ == "__main__":
    main()
