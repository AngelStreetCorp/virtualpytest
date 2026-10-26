"""Typed, fail-closed Atlas routing primitives (TASK-112).

This module deliberately separates route selection from execution.  Jev may only
choose one of the catalogued ids; the existing manager remains authoritative for
skill loading, target resolution, permissions, and tool calls.
"""

from __future__ import annotations

import logging
import os
import time
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from shared.src.lib.ai import decisions, router

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AtlasRoute:
    route_id: str
    skill_id: str
    description: str
    tool_ids: tuple[str, ...]
    platform: Optional[str] = None
    required_slots: tuple[str, ...] = ()
    risk: str = "planner"
    mode: str = "planner-only"


@dataclass(frozen=True)
class AtlasRouteCatalog:
    routes: tuple[AtlasRoute, ...]
    errors: tuple[str, ...] = ()

    def for_context(self, *, platform: Optional[str] = None,
                    allowed_tools: Optional[set[str]] = None) -> tuple[AtlasRoute, ...]:
        return tuple(r for r in self.routes
                     if (not platform or not r.platform or r.platform == platform)
                     and (allowed_tools is None or set(r.tool_ids) <= allowed_tools))


@dataclass(frozen=True)
class RouteSelection:
    """Validated Jev output; still a proposal until the planner authorizes it."""
    route_id: Optional[str]
    action: str
    reason: str
    confidence: Optional[float] = None
    margin: Optional[float] = None


@dataclass(frozen=True)
class ToolProposal:
    tool_id: Optional[str]
    parameters: dict
    action: str
    reason: str
    route_id: Optional[str] = None


def should_escalate_to_jev(ranked_skills: list[tuple[Any, int, int]]) -> bool:
    """Use Jev unless the existing trigger matcher has a decisive skill match.

    The criterion is fixed before benchmark scoring. It mirrors the manager's
    two-trigger auto-load rule and also requires a score gap to avoid ties.
    """
    if not ranked_skills:
        return True
    _, score, hits = ranked_skills[0]
    runner_up = ranked_skills[1][1] if len(ranked_skills) > 1 else 0
    return hits < 2 or score - runner_up < 3


_TOOL_HINTS: dict[str, tuple[str, ...]] = {
    "capture_screenshot": ("screenshot", "screen capture", "capture the screen"),
    "list_hosts": ("connected devices", "all devices", "list devices", "hosts"),
    "get_device_info": ("device status", "device information", "online", "battery"),
    "get_installed_apps": ("installed apps", "apps installed"),
    "navigate_to_node": ("navigate to", "go to the node", "open the node"),
    "verify_node": ("verify", "check that", "is visible"),
    "list_userinterfaces": ("user interfaces", "interfaces"),
    "list_navigation_nodes": ("navigation nodes", "nodes in tree"),
    "list_campaigns": ("campaigns", "campaign list"),
    "execute_campaign": ("run campaign", "execute campaign"),
    "list_scripts": ("scripts", "script results"),
    "execute_script": ("run script", "execute script"),
    "list_testcases": ("test cases", "testcases"),
    "execute_testcase": ("run testcase", "run test case"),
    "list_docs": ("list docs", "documentation"),
    "search_docs": ("search the docs", "search docs"),
    "show_page": ("show me the reports", "open the reports for", "show me the incidents", "open the companion"),
    "navigate_to_page": ("open the dashboard", "open the page", "navigate to the"),
}
_READ_ONLY_TOOLS = frozenset({
    "list_hosts", "get_device_info", "get_installed_apps", "capture_screenshot",
    "list_userinterfaces", "list_navigation_nodes", "list_campaigns", "list_scripts",
    "list_testcases", "list_docs", "search_docs", "get_alerts", "view_logs",
})


def _extract_parameters(message: str, tool_id: str) -> dict:
    """Extract only explicit, unambiguous scalar slots; never invent defaults."""
    text = message.strip()
    params: dict[str, str] = {}
    if tool_id in {"capture_screenshot", "get_device_info", "get_installed_apps", "execute_device_action"}:
        match = re.search(r"\bdevice\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9_.-]*)\b", text, re.I)
        if not match:
            match = re.search(r"\b(?:on|from|for)\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9 _.-]*?)(?:\s*[.!?,]|$)", text, re.I)
        if match:
            params["device_name"] = match.group(1).strip()
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*-[0-9]+", match.group(1)):
                params["device_id"] = match.group(1)
    if tool_id in {"navigate_to_node", "verify_node"}:
        match = re.search(r"\b(?:to|node)\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9 _.-]*?)(?:\s*[.!?,]|$)", text, re.I)
        if match:
            # Emit the key the tool schema actually declares (target_node_label for
            # navigate_to_node, node_label for verify_node); a bare "node" key was
            # dropped by the schema filter and forced every node route to clarify.
            key = "target_node_label" if tool_id == "navigate_to_node" else "node_label"
            params[key] = match.group(1).strip()
    return params


def resolve_tool(route: AtlasRoute, message: str, *, tool_schemas: Optional[dict[str, dict]] = None,
                 authorized_tools: Optional[set[str]] = None) -> ToolProposal:
    """Map a route to one real MCP tool using deterministic evidence.

    A skill with several tools is not enough to execute.  This resolver only
    returns a tool when one hint wins uniquely and its required schema fields
    are present; otherwise the existing Atlas planner must handle the request.
    """
    text = message.lower()
    candidates = [(sum(text.count(h) for h in hints), tool)
                  for tool, hints in _TOOL_HINTS.items() if tool in route.tool_ids]
    candidates = sorted(((score, tool) for score, tool in candidates if score), reverse=True)
    if not candidates or (len(candidates) > 1 and candidates[0][0] == candidates[1][0]):
        return ToolProposal(None, {}, "plan", "tool_ambiguous", route.route_id)
    tool = candidates[0][1]
    if authorized_tools is not None and tool not in authorized_tools:
        return ToolProposal(None, {}, "reject", "unauthorized_tool", route.route_id)
    params = _extract_parameters(message, tool)
    definition = (tool_schemas or {}).get(tool)
    if definition is None:
        return ToolProposal(None, {}, "plan", "schema_unavailable", route.route_id)
    schema = definition.get("input_schema") or {}
    properties = schema.get("properties") or {}
    if tool in {"capture_screenshot", "get_device_info", "execute_device_action"} and "device_id" in properties:
        mentions_target = bool(re.search(r"\b(device|tv|phone|box|stb|set.top box)\b", message, re.I))
        if mentions_target and "device_id" not in params:
            return ToolProposal(tool, {}, "clarify", "target_unresolved", route.route_id)
    if "device_name" in params and "device_id" in properties and "device_id" not in params:
        return ToolProposal(tool, {}, "clarify", "target_unresolved", route.route_id)
    params = {name: value for name, value in params.items() if name in properties}
    required = set(schema.get("required") or [])
    missing = required - set(params)
    if missing:
        return ToolProposal(tool, params, "clarify", "missing_parameters", route.route_id)
    return ToolProposal(tool, params, "route", "validated_tool", route.route_id)


def validate_selection(choice: Optional[str], confidence: Optional[float],
                       probabilities: Optional[dict], *, catalog: AtlasRouteCatalog,
                       allowed_tools: Optional[set[str]] = None,
                       required_slots: Optional[set[str]] = None,
                       facts: Optional[dict] = None,
                       min_confidence: float = 0.90,
                       min_margin: float = 0.15) -> RouteSelection:
    """Validate a closed Jev choice before it can become an executable plan.

    This function never executes a tool.  It rejects unknown routes, routes
    outside the authorized MCP set, missing context slots, ambiguous targets,
    unsafe routes, and uncalibrated confidence.  ``general_agent`` and
    ``clarify`` are planner outcomes, not executable routes.
    """
    facts = facts or {}
    probabilities = probabilities or {}
    if choice in {None, "clarify", "general_agent"}:
        return RouteSelection(None, "clarify" if choice == "clarify" else "plan", "jev_abstain", confidence)
    route = next((r for r in catalog.routes if r.route_id == choice), None)
    if route is None:
        return RouteSelection(None, "plan", "unknown_route", confidence)
    if facts.get("target_ambiguous") or facts.get("target_authorized") is False:
        return RouteSelection(None, "clarify" if facts.get("target_ambiguous") else "reject", "target_guard", confidence)
    if allowed_tools is not None and not set(route.tool_ids) <= allowed_tools:
        return RouteSelection(None, "reject", "unauthorized_tools", confidence)
    if route.mode != "fast-eligible" or route.risk not in {"read-only", "low"}:
        return RouteSelection(route.route_id, "plan", "planner_only", confidence)
    missing = set(required_slots or route.required_slots) - set(facts)
    if missing:
        return RouteSelection(route.route_id, "clarify", "missing_slots", confidence)
    ranked = sorted((float(v), str(k)) for k, v in probabilities.items())
    margin = ranked[-1][0] - ranked[-2][0] if len(ranked) > 1 else None
    if confidence is None or confidence < min_confidence or (margin is not None and margin < min_margin):
        return RouteSelection(route.route_id, "plan", "below_threshold", confidence, margin)
    return RouteSelection(route.route_id, "route", "validated", confidence, margin)


def build_catalog(skills: Iterable[Any], known_tools: set[str]) -> AtlasRouteCatalog:
    """Build a deterministic catalog from loaded SkillDefinition objects.

    Invalid skills/tools are excluded and returned as errors: callers must fail
    closed rather than expose a route whose MCP schema is unavailable.
    """
    routes: list[AtlasRoute] = []
    errors: list[str] = []
    for skill in sorted(skills, key=lambda s: s.name):
        tool_ids = tuple(sorted(set(skill.tools)))
        missing = sorted(set(tool_ids) - known_tools)
        if missing:
            errors.append(f"{skill.name}: unknown MCP tools: {', '.join(missing)}")
            continue
        read_only = bool(tool_ids) and set(tool_ids) <= _READ_ONLY_TOOLS
        routes.append(AtlasRoute(
            route_id=f"skill:{skill.name}", skill_id=skill.name,
            description=skill.description, tool_ids=tool_ids,
            platform=skill.platform, required_slots=tuple(sorted(skill.required_context)),
            risk="read-only" if read_only else ("device" if skill.requires_device else "planner"),
            mode="fast-eligible" if read_only else "planner-only",
        ))
    return AtlasRouteCatalog(tuple(routes), tuple(errors))


def routing_mode() -> str:
    mode = os.getenv("ATLAS_JEV_ROUTING_MODE", "off").strip().lower()
    return mode if mode in {"off", "shadow", "gated"} else "off"


def shadow_route(message: str, *, catalog: AtlasRouteCatalog, team_id: Optional[str],
                 platform: Optional[str] = None, allowed_tools: Optional[set[str]] = None,
                 baseline_route: Optional[str] = None, refs: Optional[dict] = None,
                 tool_schemas: Optional[dict[str, dict]] = None) -> dict:
    """Ask Jev for a closed-choice route without changing execution.

    The returned decision is telemetry only.  Errors and disabled Jev are
    represented as an abstention so the caller can continue its existing path.
    """
    started = time.monotonic()
    candidates = catalog.for_context(platform=platform, allowed_tools=allowed_tools)
    result: dict[str, Any] = {
        "mode": routing_mode(), "choice": None, "baseline_route": baseline_route,
        "candidates": [r.route_id for r in candidates], "abstained": True,
    }
    if routing_mode() not in {"shadow", "gated"} or not decisions.enabled("text.decision.atlas.routing"):
        result["reason"] = "disabled"
        return result
    if not candidates:
        result["reason"] = "no_candidates"
        return result
    try:
        resolution = router.resolve("text.decision.atlas.routing", team_id=team_id)
        options = [{"id": r.route_id, "facts": f"{r.description}; tools={','.join(r.tool_ids)}"}
                   for r in candidates]
        options.extend([
            {"id": "general_agent", "facts": "Use the existing general Atlas planner"},
            {"id": "clarify", "facts": "Required information or target is ambiguous"},
        ])
        out = decisions.choose(resolution, state=message[:2000], options=options,
                               instructions="Choose only the best route id. Do not infer tool names or arguments.",
                               refs={"source": "atlas-routing", **(refs or {})}, log=True)
        selection = validate_selection(
            out.get("choice"), out.get("confidence"), out.get("probabilities"),
            catalog=catalog, allowed_tools=allowed_tools,
        )
        route = next((r for r in catalog.routes if r.route_id == out.get("choice")), None)
        proposal = resolve_tool(route, message, tool_schemas=tool_schemas,
                                authorized_tools=allowed_tools) if route and selection.action == "route" else ToolProposal(None, {}, selection.action, selection.reason)
        result.update({"choice": out.get("choice"), "confidence": out.get("confidence"),
                       "probabilities": out.get("probabilities") or {},
                       "decision_id": out.get("decision_id"), "success": bool(out.get("success")),
                       "model": out.get("model"), "provider_profile": out.get("profile"),
                       "usage": out.get("usage") or {}, "cost": out.get("cost"),
                       "abstained": not bool(out.get("success")) or out.get("choice") in {None, "clarify", "general_agent"},
                       "reason": out.get("error") or selection.reason,
                       "validated_action": selection.action,
                       "validated_route_id": selection.route_id,
                       "confidence_margin": selection.margin,
                       "tool_proposal": {"tool_id": proposal.tool_id, "parameters": proposal.parameters,
                                         "action": proposal.action, "reason": proposal.reason}})
    except Exception as exc:
        logger.info("Atlas Jev shadow route unavailable: %s", exc)
        result["reason"] = "provider_error"
    result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return result
