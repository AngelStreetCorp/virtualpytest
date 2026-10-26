"""
Who made an AI call, as one short key for Monitoring → AI usage (TASK-87 round 2).

Derived from fields the call log already has (usage key, origin, script name, host) — no new column:

- ``agent:<id>``      a call made by an agent (Atlas, Sherlock, Forge, Nightwatch…), read from the usage key
- ``script:<name>``   a script run (the script's display name)
- ``process:<name>``  a service that makes calls on its own (``vpt-discard-incidents``, ``vpt-monitor``)
- ``job:<name>``      a background job, named by what it does (the usage's label: "Fleet health report")
- ``eval:<name>``     a model test, named by the feature under test (the page says "Model test · <name>")
- ``other:<origin>``  everything else, named by its origin (web app, public Ask, settings test…); ``other:api`` is
                      a service-key client that named nobody: the page calls it "Unknown API client"

The page turns the key into words; process and script names are shown as they are.
"""

from __future__ import annotations

from typing import Optional

from . import usages

AGENT_NAMES = {
    "atlas": "Atlas", "sherlock": "Sherlock", "forge": "Forge", "nightwatch": "Nightwatch",
    "browser": "Browser agent", "mcp_prompt": "MCP prompt",
}
# Usage key (or prefix) -> the agent it belongs to. A background Sherlock call is still Sherlock.
_AGENT_BY_USAGE = {
    "agent.atlas": "atlas", "agent.sherlock": "sherlock", "analyzer.sherlock": "sherlock",
    "text.decision.sherlock": "sherlock", "agent.forge": "forge", "agent.nightwatch": "nightwatch",
    "agent.browser": "browser", "agent.mcp_prompt": "mcp_prompt",
}
# Usages only the alert-triage worker makes.
_DISCARD_INCIDENT_USAGES = ("vision.alert_triage", "text.decision.freeze_triage")


def agent_of(usage_key: str) -> Optional[str]:
    """Agent id of a usage key, or None when no agent made the call."""
    if usage_key in _AGENT_BY_USAGE:
        return _AGENT_BY_USAGE[usage_key]
    base = usage_key.split(usages._SKILL_MARKER, 1)[0]
    if base in _AGENT_BY_USAGE:
        return _AGENT_BY_USAGE[base]
    if base.startswith("agent.") and base.count(".") == 1:
        return base.split(".", 1)[1]
    return None


def feature_label(usage_key: str) -> str:
    """Human name of a usage key, also for a dynamic agent (``agent.<id>``) the catalogue does not list.

    A pinned (scoring) call carries the label ``eval:<usage key>``; the prefix is dropped so the
    page names the feature under test, not the label of the call.
    """
    if usage_key.startswith('eval:'):
        usage_key = usage_key[len('eval:'):]
    if usage_key in usages.USAGES:
        return usages.short_label(usage_key)
    agent = agent_of(usage_key)
    if agent:
        return AGENT_NAMES.get(agent, agent.replace("_", " ").capitalize())
    return usage_key or "?"


def category_label(category: str) -> Optional[str]:
    """Name of a ``usage:<key>`` category (a usage with no named category); None for a named one, which
    the page translates itself."""
    return feature_label(category[len("usage:"):]) if category.startswith("usage:") else None


def caller_of(row: dict) -> str:
    """Caller key of a call row or rollup row (see module doc)."""
    usage_key = row.get("usage_key") or ""
    origin = row.get("origin") or ""
    agent = agent_of(usage_key)
    if agent:
        return f"agent:{agent}"
    if origin == "eval":
        return f"eval:{feature_label(usage_key)}"
    if origin == "script" or row.get("script_name"):
        name = row.get("script_name")
        return f"script:{name}" if name else "other:script"
    if usage_key in _DISCARD_INCIDENT_USAGES:
        return "process:vpt-discard-incidents"
    if origin == "monitoring":
        return "process:vpt-monitor"
    if origin == "background":
        return f"job:{feature_label(usage_key)}"
    return f"other:{origin or 'unknown'}"
