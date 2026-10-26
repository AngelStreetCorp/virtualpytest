#!/usr/bin/env python3
"""Dry-run Atlas routing benchmark. Predictions never read expected labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend_server.src.agent.atlas_routing import (
    build_catalog, resolve_tool, shadow_route, should_escalate_to_jev,
)
from backend_server.src.agent.core.tool_bridge import ToolBridge
from backend_server.src.agent.skills.skill_loader import SkillLoader
from backend_server.src.agent.skills.skill_registry import get_skill_registry


def load_cases(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if len(rows) != 100 or len({row["id"] for row in rows}) != 100:
        raise ValueError(f"dataset must have 100 unique IDs, found {len(rows)}")
    return rows


def direct_eligible_tools() -> set[str]:
    """Manager direct-tool policy, i.e. ``QAManagerAgent.router_tool_names``.

    A direct tool is offered to Atlas outside any skill: every registered MCP tool
    whose category is not blocked, minus the blocked exact names and ``delete_*``.
    This mirrors backend_server/src/agent/core/manager.py:687 without instantiating
    the agent. Direct eligibility is not session authorization.
    """
    from backend_server.src.agent.core.manager import QAManagerAgent
    from backend_server.src.mcp.tool_definitions.build_definitions import get_builder

    blocked_categories = QAManagerAgent._ATLAS_DIRECT_BLOCKED_CATEGORIES
    blocked_exact = QAManagerAgent._ATLAS_DIRECT_BLOCKED_EXACT
    blocked_prefixes = QAManagerAgent._ATLAS_DIRECT_BLOCKED_PREFIXES
    out: set[str] = set()
    for category, definitions in get_builder()._definitions.items():
        if category in blocked_categories:
            continue
        for definition in definitions:
            name = definition["name"]
            if name in blocked_exact or name.startswith(blocked_prefixes):
                continue
            out.add(name)
    return out


def load_runtime():
    SkillLoader.reload()
    skills = SkillLoader.get_all_skills()
    catalog = build_catalog(skills.values(), set(get_skill_registry().get_all_skills()))
    if catalog.errors:
        raise ValueError(f"catalog errors: {catalog.errors}")
    skill_tools = {name for route in catalog.routes for name in route.tool_ids}
    names = sorted(skill_tools | direct_eligible_tools())
    # ToolBridge supplies definitions only; this runner never calls execute().
    # Some manager-direct tools (e.g. take_control/release_control) have no
    # ToolBridge definition; only skill-route tools are required to have one.
    schemas = {item["name"]: item for item in ToolBridge().get_tool_definitions(names)}
    if skill_tools - set(schemas):
        raise ValueError(f"missing schemas: {sorted(skill_tools - set(schemas))}")
    return skills, catalog, schemas


def validate_oracle(cases, catalog, original_path):
    original = load_cases(original_path)
    if [(r["id"], r["prompt"], r["category"]) for r in cases] != [
        (r["id"], r["prompt"], r["category"]) for r in original
    ]:
        raise ValueError("prompt, ID or category differs from the preserved oracle")
    by_skill = {route.skill_id: route for route in catalog.routes}
    direct = direct_eligible_tools()
    known_tools = {tool for route in catalog.routes for tool in route.tool_ids} | direct

    def allowed_tools_for(skill: str) -> set[str]:
        # "direct" is the manager direct-tool outcome: a permitted tool that no
        # loaded skill declares.
        if skill == "direct":
            return direct
        return set(by_skill[skill].tool_ids) if skill in by_skill else set()

    invalid = [row["id"] for row in cases
               if row["expected_mcp_tool"] not in {"none", "clarify"}
               and row["expected_mcp_tool"] not in allowed_tools_for(row["expected_skill"])]
    if invalid:
        raise ValueError(f"invalid expected skill/tool pairs: {invalid}")
    invalid_plans = [row["id"] for row in cases
                     if set(row.get("expected_execution_plan") or []) - known_tools]
    if invalid_plans:
        raise ValueError(f"execution plans contain unknown tools: {invalid_plans}")
    return hashlib.sha256(Path(original_path).read_bytes()).hexdigest()


def parameter_oracle_issues(cases, schemas):
    issues = []
    for case in cases:
        tool = case["expected_mcp_tool"]
        if tool not in schemas:
            continue
        properties = (schemas[tool].get("input_schema") or {}).get("properties") or {}
        unknown = sorted(set(case["expected_parameters"]) - set(properties))
        if unknown:
            issues.append({"id": case["id"], "tool": tool, "unknown_parameter_keys": unknown})
    return issues


def semantic_slot_cases(cases):
    """Cases whose target/argument information is an explicitly labelled semantic
    slot, not a ToolBridge schema argument. Slot extraction is measured separately
    (P0-3); these must never be folded back into expected_parameters."""
    return [{"id": case["id"], "tool": case["expected_mcp_tool"],
             "slots": sorted(case["expected_semantic_slots"])}
            for case in cases if case.get("expected_semantic_slots")]


def algorithm_prediction(prompt, skills, catalog, schemas, allowed_tools):
    ranked = SkillLoader.rank_skills(prompt, list(skills))
    candidates = [{"skill": skill.name, "score": score, "trigger_hits": hits}
                  for skill, score, hits in ranked]
    selected = ranked[0][0] if ranked else None
    route = next((r for r in catalog.routes if selected and r.skill_id == selected.name), None)
    proposal = (resolve_tool(route, prompt, tool_schemas=schemas, authorized_tools=allowed_tools)
                if route else None)
    action = proposal.action if proposal else "clarify"
    return ({"intent": None, "skill": selected.name if selected else "none",
             "tool": proposal.tool_id if proposal and proposal.tool_id else "none",
             "action": "clarify" if action == "plan" else action,
             "parameters": proposal.parameters if proposal else {},
             "routing_level": "algorithm", "algorithm_candidates": candidates,
             "route_id": route.route_id if route else None,
             "reason": proposal.reason if proposal else "no_trigger_match",
             "jev_invoked": False, "planner_handoff": True,
             "llm_fallback_invoked": False, "cost_usd": 0.0,
             "tokens_in": 0, "tokens_out": 0}, ranked)


def jev_prediction(prompt, catalog, schemas, allowed_tools, team_id, mode):
    old_mode = os.environ.get("ATLAS_JEV_ROUTING_MODE")
    os.environ["ATLAS_JEV_ROUTING_MODE"] = "gated" if mode == "hybrid" else "shadow"
    try:
        decision = shadow_route(prompt, catalog=catalog, team_id=team_id,
                                allowed_tools=allowed_tools, tool_schemas=schemas,
                                refs={"source": "atlas-routing-benchmark"})
    finally:
        if old_mode is None:
            os.environ.pop("ATLAS_JEV_ROUTING_MODE", None)
        else:
            os.environ["ATLAS_JEV_ROUTING_MODE"] = old_mode
    proposal = decision.get("tool_proposal") or {}
    validated = decision.get("validated_action")
    action = ("route" if validated == "route" and proposal.get("action") == "route"
              else "reject" if validated == "reject" or proposal.get("action") == "reject"
              else "clarify")
    if decision.get("reason") in {"disabled", "provider_error"}:
        action = "unavailable"
    usage = decision.get("usage") or {}
    return {"intent": None,
            "skill": (decision.get("validated_route_id") or decision.get("choice") or "none").removeprefix("skill:"),
            "tool": proposal.get("tool_id") or "none", "parameters": proposal.get("parameters") or {},
            "action": action, "routing_level": "JEV", "route_id": decision.get("validated_route_id"),
            "jev_invoked": bool(decision.get("decision_id")), "decision_id": decision.get("decision_id"),
            "confidence": decision.get("confidence"), "confidence_margin": decision.get("confidence_margin"),
            "probabilities": decision.get("probabilities") or {}, "jev_candidates": decision.get("candidates") or [],
            "provider_error": decision.get("reason") if decision.get("reason") == "provider_error" else None,
            "reason": proposal.get("reason") or decision.get("reason"),
            "planner_handoff": True, "llm_fallback_invoked": False,
            "model": decision.get("model"), "provider_profile": decision.get("provider_profile"),
            "cost_usd": decision.get("cost"), "tokens_in": usage.get("input_tokens"),
            "tokens_out": usage.get("output_tokens")}


def predict(prompt, mode, skills, catalog, schemas, allowed_tools, team_id, live_jev):
    algorithm, ranked = algorithm_prediction(prompt, skills, catalog, schemas, allowed_tools)
    if mode == "algorithm":
        return algorithm
    if mode == "hybrid" and not should_escalate_to_jev(ranked):
        return {**algorithm, "escalation_reason": "decisive_trigger"}
    if not live_jev:
        return {"intent": None, "skill": "none", "tool": "none", "parameters": {},
                "action": "unavailable", "routing_level": mode,
                "algorithm_candidates": algorithm["algorithm_candidates"],
                "jev_invoked": False, "planner_handoff": False,
                "llm_fallback_invoked": False, "provider_error": "live_jev_not_enabled", "cost_usd": None}
    selected = jev_prediction(prompt, catalog, schemas, allowed_tools, team_id, mode)
    selected["algorithm_candidates"] = algorithm["algorithm_candidates"]
    selected["escalation_reason"] = "weak_or_ambiguous_trigger"
    return selected


def score(case, actual):
    slots = case.get("expected_semantic_slots") or {}
    expected_device = case["expected_parameters"].get("device_id")
    expected_name = case["expected_parameters"].get("device_name") or slots.get("device_name")
    actual_device = actual.get("parameters", {}).get("device_id")
    actual_name = actual.get("parameters", {}).get("device_name")
    return {"intent": None if actual.get("intent") is None else actual["intent"] == case["expected_intent"],
            "skill": actual["skill"] == case["expected_skill"],
            "tool": actual["tool"] == case["expected_mcp_tool"],
            "action": actual["action"] == case["expected_action"],
            "parameters": actual.get("parameters", {}) == case["expected_parameters"],
            "route": (actual["skill"] == case["expected_skill"]
                      and actual["tool"] == case["expected_mcp_tool"]
                      and actual["action"] == case["expected_action"]),
            "unsafe": ((case["expected_action"] == "reject" and actual["action"] == "route")
                       or (expected_device is not None and actual["action"] == "route"
                           and actual_device != expected_device)
                       or (expected_name is not None and actual["action"] == "route"
                           and actual_device is None and actual_name != expected_name)),
            "false_positive_action": case["expected_action"] != "route" and actual["action"] == "route"}


def metrics(rows, times):
    measured = [row for row in rows if row["actual"]["action"] != "unavailable"]
    if len(measured) != len(rows):
        return {"available": False, "cases": len(rows), "measured_cases": len(measured),
                "reason": "live Jev unavailable for some or all cases"}
    result = {"available": True, "cases": len(rows), "measured_cases": len(measured),
              "correct": sum(row["scores"]["route"] for row in measured)}
    for key in ("intent", "skill", "tool", "route", "action"):
        values = [row["scores"][key] for row in measured if row["scores"][key] is not None]
        result[f"{key}_accuracy"] = sum(values) / len(values) if values else None
    result.update({
        "unsafe_routing_errors": sum(row["scores"]["unsafe"] for row in measured),
        "false_positive_action_routes": sum(row["scores"]["false_positive_action"] for row in measured),
        "p50_latency_ms": statistics.median(times),
        "p95_latency_ms": sorted(times)[max(0, int(len(times) * .95) - 1)],
        "jev_invocation_rate": sum(row["jev_invoked"] for row in rows) / len(rows),
        "algorithm_only_rate": sum(row["actual"]["routing_level"] == "algorithm" for row in rows) / len(rows),
        "planner_handoff_rate": sum(row["actual"].get("planner_handoff", False) for row in rows) / len(rows),
        "llm_fallback_invocation_rate": sum(row["actual"].get("llm_fallback_invoked", False) for row in rows) / len(rows),
        "provider_errors": sum(bool(row["actual"].get("provider_error")) for row in rows),
        "tokens_in": sum(row["actual"].get("tokens_in") or 0 for row in rows),
        "tokens_out": sum(row["actual"].get("tokens_out") or 0 for row in rows),
        "cost_usd": sum(row["actual"].get("cost_usd") or 0 for row in rows),
        "by_category": {}, "by_routing_level": {},
    })
    for field, key in (("category", "by_category"), ("routing_level", "by_routing_level")):
        values = {row["expected"][field] if field == "category" else row["actual"][field]
                  for row in measured}
        for value in sorted(values):
            subset = [row for row in measured if (row["expected"][field] if field == "category"
                                                   else row["actual"][field]) == value]
            result[key][value] = {"cases": len(subset),
                                  "route_accuracy": sum(row["scores"]["route"] for row in subset) / len(subset),
                                  "unsafe_routing_errors": sum(row["scores"]["unsafe"] for row in subset)}
    return result


def run(cases, mode, skills, catalog, schemas, team_id, live_jev):
    rows, times = [], []
    for case in cases:
        start = time.perf_counter()
        actual = predict(case["prompt"], mode, skills, catalog, schemas, set(schemas), team_id, live_jev)
        elapsed = (time.perf_counter() - start) * 1000
        rows.append({"id": case["id"], "mode": mode, "expected": case, "actual": actual,
                     "scores": score(case, actual), "latency_ms": elapsed,
                     "jev_invoked": actual["jev_invoked"], "dry_run": True, "mcp_executions": 0})
        times.append(elapsed)
    return rows, times


def render_report(cases, rows, summary, prompt_hash):
    index = {(row["id"], row["mode"]): row for row in rows}
    lines = ["# Atlas P1 routing benchmark", "", "Dry run: zero MCP/device executions.",
             f"Original oracle SHA-256: `{prompt_hash}`. Prompts and IDs unchanged.", "",
             "| Mode | Exact | Skill | MCP tool | Unsafe | Jev rate | P50 ms | P95 ms |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for mode, data in summary.items():
        if not data["available"]:
            lines.append(f"| {mode} | N/A | N/A | N/A | N/A | N/A | N/A | N/A |")
        else:
            lines.append(f"| {mode} | {data['route_accuracy']:.1%} | {data['skill_accuracy']:.1%} | "
                         f"{data['tool_accuracy']:.1%} | {data['unsafe_routing_errors']} | "
                         f"{data['jev_invocation_rate']:.1%} | {data['p50_latency_ms']:.2f} | {data['p95_latency_ms']:.2f} |")
    lines += ["", "Intent is N/A because the production selector emits no independent intent.",
              "Parameter accuracy is N/A where expected semantic slots do not match ToolBridge schema arguments; see metrics.json.",
              "Planner handoff is recorded; actual Atlas LLM fallback is not invoked by this dry run.",
              "", "## All 100 cases", "",
              "| ID | Category | Expected skill / tool / action | Algorithm | Jev | Hybrid |",
              "|---|---|---|---|---|---|"]
    for case in cases:
        cells = []
        for mode in ("algorithm", "jev", "hybrid"):
            row = index[case["id"], mode]
            actual = row["actual"]
            cells.append(f"{actual['skill']} / {actual['tool']} / {actual['action']} "
                         f"{'✓' if row['scores']['route'] else '✗'}")
        expected = f"{case['expected_skill']} / {case['expected_mcp_tool']} / {case['expected_action']}"
        lines.append(f"| {case['id']} | {case['category']} | {expected} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("tests/benchmarks/atlas_routing_cases.jsonl"))
    parser.add_argument("--original", type=Path, default=Path("tests/benchmarks/atlas_routing_cases_original.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("reports/atlas-routing-benchmark/post-p1"))
    parser.add_argument("--live-jev", action="store_true")
    parser.add_argument("--team-id")
    parser.add_argument("--env-file", type=Path, help="load local secrets without copying or logging them")
    parser.add_argument("--rescore-results", type=Path,
                        help="re-score saved dry-run decisions after an oracle correction, without new model calls")
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    if args.live_jev and not args.team_id:
        parser.error("--team-id is required for --live-jev")
    cases = load_cases(args.dataset)
    skills, catalog, schemas = load_runtime()
    prompt_hash = validate_oracle(cases, catalog, args.original)
    parameter_issues = parameter_oracle_issues(cases, schemas)
    results, summary = [], {}
    decision_hash = None
    if args.rescore_results:
        raw = args.rescore_results.read_bytes()
        decision_hash = hashlib.sha256(raw).hexdigest()
        saved = [json.loads(line) for line in raw.splitlines() if line.strip()]
        index = {(row["id"], row["mode"]): row for row in saved}
        if len(saved) != 300 or len(index) != 300 or any(not row.get("dry_run") or row.get("mcp_executions") for row in saved):
            raise ValueError("rescore requires 300 unique dry-run records with zero MCP executions")
        for mode in ("algorithm", "jev", "hybrid"):
            rows = []
            for case in cases:
                row = index[case["id"], mode]
                if row["expected"]["prompt"] != case["prompt"]:
                    raise ValueError(f"prompt changed for {case['id']}")
                row["expected"] = case
                row["scores"] = score(case, row["actual"])
                rows.append(row)
            results.extend(rows)
            summary[mode] = metrics(rows, [row["latency_ms"] for row in rows])
    else:
        for mode in ("algorithm", "jev", "hybrid"):
            rows, times = run(cases, mode, skills, catalog, schemas, args.team_id, args.live_jev)
            results.extend(rows)
            summary[mode] = metrics(rows, times)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "results.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in results) + "\n")
    for mode, data in summary.items():
        data["parameters_accuracy"] = (None if parameter_issues or not data["available"] else
                                       sum(row["scores"]["parameters"] for row in results
                                           if row["mode"] == mode) / data["cases"])
        data["parameters_accuracy_reason"] = (
            f"{len(parameter_issues)} cases use parameter keys outside the ToolBridge schema"
            if parameter_issues else None)
    (args.output / "metrics.json").write_text(json.dumps({"oracle_sha256": prompt_hash,
        "decision_results_sha256": decision_hash, "rescored": bool(args.rescore_results),
        "catalog_errors": catalog.errors, "parameter_oracle_issues": parameter_issues,
        "mcp_executions": 0, "modes": summary}, indent=2) + "\n")
    (args.output / "summary.md").write_text(render_report(cases, results, summary, prompt_hash))
    failures = [row for row in results if row["actual"]["action"] != "unavailable" and not row["scores"]["route"]]
    (args.output / "failures.md").write_text("# Atlas P1 failed cases\n\n" +
        "\n".join(f"- {row['mode']} {row['id']}: expected {row['expected']['expected_skill']} / "
                  f"{row['expected']['expected_mcp_tool']} / {row['expected']['expected_action']}; "
                  f"actual {row['actual']['skill']} / {row['actual']['tool']} / {row['actual']['action']} "
                  f"({row['actual'].get('reason', 'no_reason')})" for row in failures) + "\n")
    print(json.dumps({"output": str(args.output), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
