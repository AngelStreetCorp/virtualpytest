#!/usr/bin/env python3
"""TASK-114 P0-3b — observe the real Atlas planner turn, dry.

This is the last P0-3 piece: instead of inferring a planner handoff, it runs the
**production router turn** (the same `_build_cached_system` + `_build_cached_tools`
+ `_create_turn` the agent uses) for each prompt, records what the model decided
(load a skill / call a direct tool / text), and validates any proposed tool call
with the dry dispatcher — never executing it.

Runs where the AI route credentials live (the server); the local tests inject a
fake `_create_turn`. No Jev call: `shadow_route` is never invoked and
`ATLAS_JEV_ROUTING_MODE` is left alone.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend_server" / "src"))

from agent.core.manager import QAManagerAgent  # noqa: E402
from agent.core.tool_bridge import ToolBridge  # noqa: E402

from scripts.bench_atlas_production import (SessionContext, dry_dispatch,  # noqa: E402
                                            resolve_named_targets)
from scripts.bench_atlas_router import load_cases, load_runtime  # noqa: E402

LOAD_SKILL = re.compile(r"LOAD\s+SKILL\s*\[([^\]]+)\]", re.I)
CLARIFY_HINTS = ("which device", "which one", "which app", "which service", "which test",
                 "which user", "which host", "what do you mean", "please specify",
                 "could you clarify", "could you tell me", "need to know", "i need more",
                 "more information")
REJECT_HINTS = ("cannot", "can't", "not allowed", "unauthorized", "won't", "not permitted",
                "against policy")


def parse_response(resp) -> dict:
    blocks = list(getattr(resp, "content", None) or [])
    text = "\n".join((getattr(b, "text", "") or "") for b in blocks
                     if getattr(b, "type", None) == "text").strip()
    tool_uses = [b for b in blocks if getattr(b, "type", None) == "tool_use"]
    match = LOAD_SKILL.search(text)
    if tool_uses:
        block = tool_uses[0]
        return {"kind": "direct_tool", "tool": getattr(block, "name", None),
                "parameters": dict(getattr(block, "input", None) or {}),
                "skill": None, "text": text[:800]}
    if match:
        return {"kind": "load_skill", "skill": match.group(1).strip(), "tool": None,
                "parameters": {}, "text": text[:800]}
    low = text.lower()
    # A refusal that also asks which target is a clarification, not a rejection
    # ("I can't delete it without knowing which one").
    if "?" in text or any(h in low for h in CLARIFY_HINTS):
        return {"kind": "clarify", "skill": None, "tool": None, "parameters": {}, "text": text[:800]}
    if any(h in low for h in REJECT_HINTS):
        return {"kind": "reject", "skill": None, "tool": None, "parameters": {}, "text": text[:800]}
    return {"kind": "text", "skill": None, "tool": None, "parameters": {}, "text": text[:800]}


def _usage(resp):
    usage = getattr(resp, "usage", None)
    return {"tokens_in": getattr(usage, "input_tokens", None) if usage else None,
            "tokens_out": getattr(usage, "output_tokens", None) if usage else None}


def _model_info(agent):
    """Best-effort: the local tests have no routing DB; the live run does."""
    try:
        res = agent._resolution()
        return res.primary.model, res.primary.profile_name
    except Exception:
        return None, None


def run(cases, *, agent=None, team_id="bench-team", limit=None, schemas=None):
    context = SessionContext(team_id=team_id)
    if schemas is None:
        _skills, _catalog, schemas = load_runtime()
    agent = agent or QAManagerAgent(user_identifier=team_id, agent_id="assistant")
    selected = cases[:limit] if limit else cases
    model, profile = _model_info(agent)

    real_execute = ToolBridge.execute
    calls = {"execute": 0}

    def guard(*_a, **_k):
        calls["execute"] += 1
        raise AssertionError("planner harness attempted a real ToolBridge.execute")

    ToolBridge.execute = guard
    rows = []
    try:
        for case in selected:
            prompt = case["prompt"]
            tool_names = agent._select_router_tools_for_message(prompt)
            system = agent._build_cached_system({"team_id": team_id}, prompt, tool_names)
            tools = agent._build_cached_tools(tool_names)
            started = time.time()
            error = None
            try:
                resp = agent._create_turn(dict(
                    max_tokens=4096, system=system,
                    messages=[{"role": "user", "content": prompt}],
                    tools=tools, tool_choice={"type": "auto", "disable_parallel_tool_use": True},
                ))
                decision = parse_response(resp)
                usage = _usage(resp)
            except Exception as exc:  # provider/routing failure is recorded, not hidden
                decision = {"kind": "error", "skill": None, "tool": None, "parameters": {},
                            "text": str(exc)[:800]}
                usage = {"tokens_in": None, "tokens_out": None}
                error = str(exc)[:300]
            latency_ms = int((time.time() - started) * 1000)

            dispatch = None
            if decision["kind"] == "direct_tool" and decision["tool"]:
                dispatch = dry_dispatch(decision["tool"], decision["parameters"],
                                        schemas.get(decision["tool"]), set(tool_names))
            targets = resolve_named_targets(prompt, context.devices, context.server_hosts)
            rows.append({
                "id": case["id"], "prompt": prompt, "category": case["category"],
                "expected": {k: case.get(k) for k in ("expected_skill", "expected_mcp_tool", "expected_action")},
                "decision": decision, "dispatch": dispatch,
                "planner_handoff": decision["kind"] in {"text", "clarify"},
                "named_targets": targets,
                "latency_ms": latency_ms, "error": error,
                "model": model, "profile": profile,
                **usage,
            })
    finally:
        ToolBridge.execute = real_execute

    counts = {}
    for row in rows:
        counts[row["decision"]["kind"]] = counts.get(row["decision"]["kind"], 0) + 1
    actionable = [r for r in rows if r["decision"]["kind"] in {"direct_tool", "load_skill"}]
    metrics = {
        "cases": len(rows),
        "decisions": counts,
        "actionable_decisions": len(actionable),
        "planner_handoff_rate": sum(r["planner_handoff"] for r in rows) / len(rows) if rows else None,
        "mocked_dispatches": sum(1 for r in rows if r["dispatch"]),
        "validated_dispatches": sum(1 for r in rows if r["dispatch"] and r["dispatch"]["validated"]),
        "real_executions": calls["execute"],
        "errors": sum(1 for r in rows if r["decision"]["kind"] == "error"),
        "models": sorted({r["model"] for r in rows if r["model"]}),
        "profiles": sorted({r["profile"] for r in rows if r["profile"]}),
        "p50_latency_ms": sorted(r["latency_ms"] for r in rows)[len(rows) // 2] if rows else None,
    }
    return rows, metrics


def load_jsonl(path):
    """Any size (the dev/calibration set is not the 100-case holdout)."""
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("tests/benchmarks/atlas_routing_cases_v2_2026-10-16.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("reports/atlas-routing-benchmark/p03b-planner-2026-10-17"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--team-id", default="bench-team")
    args = parser.parse_args()
    cases = load_jsonl(args.dataset)
    rows, metrics = run(cases, team_id=args.team_id, limit=(args.limit or None))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=1) + "\n")
    print(json.dumps(metrics, indent=1))


if __name__ == "__main__":
    main()
