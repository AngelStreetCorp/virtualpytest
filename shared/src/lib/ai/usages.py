"""
AI usage catalogue (TASK-30).

Every AI call names *what it is for* — a usage key such as ``vision.banner`` or
``agent.atlas``. Routing rules (``ai_routes``) map usage keys to profiles; a key
with no rule of its own inherits from its parent (``vision.banner`` → ``vision``).

The catalogue is code, not data: it lists what exists and what each usage needs
from a model, so the settings UI only offers compatible profiles and the resolver
refuses unknown keys. Adding an AI call site means adding its key here first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Root usages. The server default must always route these three (the DB refuses to
# delete their default routes), so every usage resolves to something.
ROOT_USAGES = ("agent", "vision", "text")

# What a model must support, as declared on a profile (``ai_profiles.capabilities``).
CAPABILITIES = ("tools", "vision", "web")


@dataclass(frozen=True)
class Usage:
    key: str
    label: str
    description: str
    parent: Optional[str] = None
    needs: frozenset[str] = field(default_factory=frozenset)
    # "json" when the caller parses the answer as JSON; thinking="off" is then sent
    # to servers that support it (reasoning tokens would eat the budget / break parsing).
    output: str = "text"
    thinking: str = "auto"


# Shadow / background usages: nothing waits on the answer, so while their provider has no credit they are
# skipped (counted, not attempted) and never act as the probe that sees credit return (BUG-0497).
SKIPPABLE_WHEN_PAUSED = frozenset({
    "text.decision.testprompt_on_failure", "text.decision.sherlock", "text.decision.wake", "text.decision.route",
    "text.decision.retry", "text.decision.model", "text.decision.screen_review", "text.decision.localize",
    "text.decision.verification", "text.decision.freeze_triage",
})


def is_skippable(key: str) -> bool:
    return key in SKIPPABLE_WHEN_PAUSED


def _u(key: str, label: str, description: str, parent: Optional[str] = None, *,
       needs: tuple[str, ...] = (), output: str = "text", thinking: str = "auto") -> Usage:
    return Usage(key, label, description, parent, frozenset(needs), output, thinking)


USAGES: dict[str, Usage] = {u.key: u for u in (
    # --- tool-calling agents -------------------------------------------------------
    _u("agent", "Agents", "Tool-calling chat agents", needs=("tools",)),
    _u("agent.atlas", "Atlas", "Main assistant: chat, script/testcase creation, campaigns, UI building", "agent"),
    _u("agent.nightwatch", "Nightwatch", "Incident analysis chat", "agent"),
    _u("agent.sherlock", "Sherlock (chat)", "Script-result analysis chat", "agent"),
    _u("agent.forge", "Forge", "Scripting agent: virtual scripts, testcases, trees, campaigns", "agent"),
    _u("public.ask", "Public docs Ask", "Question box on the public documentation site", "agent"),
    _u("agent.mcp_prompt", "MCP prompt", "Natural-language prompt to MCP tool calls (/server/mcp-proxy)", "agent"),
    _u("agent.browser", "Browser agent", "browser-use web automation (needs an OpenAI-compatible endpoint)",
       "agent"),
    # --- vision --------------------------------------------------------------------
    _u("vision", "Vision", "Image analysis", needs=("vision",)),
    _u("vision.ask", "Ask AI (stream)", "Free question about a frame from the Rec stream modal", "vision"),
    _u("vision.describe", "Image description / text extraction", "Full image text + description (verification)", "vision"),
    _u("vision.quality", "Camera image quality", "Camera quality assessment (camera_quality test script)", "vision",
       output="json"),
    _u("vision.banner", "Channel banner", "Channel/programme banner read after a zap", "vision",
       output="json", thinking="off"),
    _u("vision.menu", "Language menu", "Audio/subtitle language menu reading", "vision",
       output="json", thinking="off"),
    _u("vision.subtitle", "Subtitles", "Subtitle text + language detection", "vision",
       output="json", thinking="off"),
    _u("vision.explore", "Exploration screen analysis", "Screen analysis while crawling a UI", "vision",
       output="json"),
    _u("vision.drone", "Drone showcase", "Drone demo: is the target in the drone camera frame / which move next (TASK-32)",
       "vision", output="json"),
    _u("vision.dom", "Web/TV DOM generation", "Screenshot to focusable-element DOM", "vision", output="json"),
    _u("vision.screenshot", "Agent screenshot description", "Frame description for agents (MCP capture_screenshot vlm=true)",
       "vision"),
    _u("vision.alert_triage", "Alert triage (background)",
       "vpt-discard-incidents: is a monitoring alert real or noise, from its frame + facts (nightwatch_handler.py)",
       "vision", output="json", thinking="off"),
    # --- text ----------------------------------------------------------------------
    _u("text", "Text", "Plain text completions"),
    _u("analyzer.sherlock", "Sherlock (background)", "Script-result classification (discard decision)", "text",
       output="json"),
    _u("text.plan", "Test plan generator", "AI graph / test-case plan generation (GOAL / REASONING / STEPS text)", "text"),
    _u("text.translation", "Translation", "Language detection and translation", "text"),
    _u("text.transcript", "Transcript analysis", "Audio transcript analysis", "text"),
    _u("text.transcript_correction", "Transcript correction",
       "Live transcript spelling/grammar fix (one call per transcribed minute per device)", "text.transcript",
       output="json", thinking="off"),
    _u("text.report", "Fleet health report", "Daily fleet health summary", "text"),
    _u("text.game_2048", "2048 showcase player", "Picks each 2048 move from the board (test_scripts/game/game_2048.py)",
       "text", output="json", thinking="off"),
    _u("text.game_strategy", "Game strategist", "Long-term plan, lessons and training rules of a game-playing run (shared/src/lib/game/pokemon/strategy.py)",
       "text"),
    _u("text.decision", "Decision (closed choice)",
       "A typed decision over a text state with a decision model such as Jev (shared/src/lib/ai/decisions.py); "
       "route only to a profile with extra.api='decisions'", "text"),
    _u("text.decision.testprompt_on_failure", "Test Prompt: after a failed test (decision model, shadow)",
       "In Auto mode, Jev picks app_failure / stale_test / infra_retry from the failed run's evidence; "
       "logged to ai_decisions, outcome = the follow-up run (features/ai-test/backend_server/server_testprompt_routes.py)",
       "text.decision"),
    _u("text.decision.sherlock", "Sherlock verdict (decision model, shadow)",
       "Jev picks Sherlock's closed verdict next to the LLM, logged to ai_decisions for agreement "
       "(backend_server/src/agent/core/sherlock_jev.py)", "text.decision"),
    _u("text.decision.manager", "Session manager (decision model)",
       "Ghosty session manager: why did a coding session stop / what reply is safe; called by the external "
       "manager tool via the server, logged to ai_decisions (refs.source = ghosty-manager)", "text.decision"),
    _u("text.decision.wake", "Manager router: wake or not (decision model, shadow)",
       "Ghosty event → ignore / rules_handle / wake_cheap / wake_opus, inside hard-rule floors "
       "(TASK-47 point 1; refs.source = ghosty-router)", "text.decision"),
    _u("text.decision.route", "Manager router: builder / reviewer (decision model, shadow)",
       "Who builds a delegated change (minimax / codex / sonnet / opus) and who reviews it "
       "(none / haiku / sonnet / opus); refs.point says which (TASK-47 points 2-3)", "text.decision"),
    _u("text.decision.retry", "Manager router: after a rejected build (decision model, shadow)",
       "retry_same_with_notes / step_up_one / owner after a gate rejects (TASK-47 point 4)", "text.decision"),
    _u("text.decision.model", "Manager router: session model suggestion (decision model, shadow)",
       "keep / sonnet / opus / hold for a coding session; a suggestion to the owner, never applied "
       "(TASK-47 point 5)", "text.decision"),
    _u("text.decision.screen_review", "Screen review (decision model, shadow)",
       "Jev picks the screen group of a stored frame from text facts (check scores, seed distance), logged to "
       "ai_decisions (scripts/jev_review)", "text.decision"),
    _u("text.decision.localize", "Localize second opinion (decision model, shadow)",
       "Jev picks the stored screen on localize ties / low confidence / abstain, in the background, logged to "
       "ai_decisions (refs.source = localize-shadow | localize-confirm; backend_host/src/controllers/verification/jev_second_opinion.py)",
       "text.decision"),
    _u("text.decision.verification", "Text check second opinion (decision model, shadow)",
       "Jev: is the expected text really on screen, for text checks within 0.10 of their threshold, in the "
       "background, logged to ai_decisions (refs.source = verification-shadow)", "text.decision"),
    _u("text.decision.freeze_triage", "Freeze triage (decision model)",
       "Jev: real freeze, still screen or moving video, from facts measured on the alert's strip "
       "(scripts/jev_freeze)", "text.decision"),
    _u("text.web", "Web lookup", "Answer grounded in a live web search (never answered without searching)", "text",
       needs=("web",)),
)}


def register(*extra: Usage) -> None:
    """Add usages owned by an optional feature (features/<name>/backend_server register()).

    Core never names a feature's usages; the feature declares them when the server loads it,
    so a disabled feature leaves no key in the catalogue or the settings UI. A key that core
    already defines is refused (a feature cannot redefine core routing).
    """
    for usage in extra:
        existing = USAGES.get(usage.key)
        if existing is not None and existing != usage:
            raise ValueError(f"AI usage '{usage.key}' is already defined")
        if usage.parent is not None and usage.parent not in USAGES:
            raise ValueError(f"AI usage '{usage.key}': unknown parent '{usage.parent}'")
        USAGES[usage.key] = usage


def feature_usage(key: str, label: str, description: str, parent: str, *, needs: tuple[str, ...] = (),
                  output: str = "text", thinking: str = "auto") -> Usage:
    """Build a Usage for ``register`` (same arguments as the core catalogue entries)."""
    return _u(key, label, description, parent, needs=needs, output=output, thinking=thinking)


# Agent YAML metadata.id -> usage key. Any other agent id maps to agent.<id>.
AGENT_USAGE_BY_ID = {
    "assistant": "agent.atlas",
    "monitor": "agent.nightwatch",
    "analyzer": "agent.sherlock",
    "scripter": "agent.forge",
}

_SKILL_MARKER = ".skill."


class UnknownUsageError(ValueError):
    pass


def agent_usage(agent_id: Optional[str], skill: Optional[str] = None) -> str:
    """Usage key for an agent (and optionally one of its skills)."""
    base = AGENT_USAGE_BY_ID.get(agent_id or "assistant") or f"agent.{agent_id}"
    return f"{base}{_SKILL_MARKER}{skill}" if skill else base


def _dynamic_parent(key: str) -> Optional[str]:
    """Parent of a key that is not in the catalogue but is valid by pattern."""
    if _SKILL_MARKER in key:
        return key.split(_SKILL_MARKER, 1)[0]
    if key.startswith("agent.") and key.count(".") == 1:
        return "agent"
    return None


def get(key: str) -> Usage:
    """The catalogue entry, or a synthesized one for agent/skill keys."""
    if key in USAGES:
        return USAGES[key]
    parent = _dynamic_parent(key)
    if parent is None or (parent not in USAGES and _dynamic_parent(parent) is None):
        raise UnknownUsageError(f"Unknown AI usage '{key}'")
    label = key.split(_SKILL_MARKER, 1)[1] if _SKILL_MARKER in key else key.split(".", 1)[1]
    return Usage(key, label, f"Dynamic usage under {parent}", parent)


def lineage(key: str) -> list[str]:
    """``key`` and its ancestors, most specific first: ``vision.banner`` → [vision.banner, vision]."""
    chain: list[str] = []
    current: Optional[str] = key
    while current:
        usage = get(current)
        chain.append(usage.key)
        current = usage.parent
    return chain


def needs(key: str) -> frozenset[str]:
    """Capabilities required by ``key`` (inherited from its ancestors)."""
    required: set[str] = set()
    for k in lineage(key):
        required |= get(k).needs
    return frozenset(required)


def effective(key: str, attr: str) -> str:
    """First non-default ``output``/``thinking`` value walking up the lineage."""
    default = "text" if attr == "output" else "auto"
    for k in lineage(key):
        value = getattr(get(k), attr)
        if value != default:
            return value
    return default


def catalogue() -> list[dict]:
    """Serializable catalogue for the settings UI."""
    return [
        {
            "key": u.key,
            "label": u.label,
            "description": u.description,
            "parent": u.parent,
            "needs": sorted(needs(u.key)),
            "output": u.output,
            "thinking": u.thinking,
        }
        for u in USAGES.values()
    ]


_FAMILY_BY_KEY = {
    "agent.sherlock": "sherlock", "analyzer.sherlock": "sherlock", "text.decision.sherlock": "sherlock",
    "agent.nightwatch": "nightwatch", "vision.alert_triage": "nightwatch", "text.decision.freeze_triage": "nightwatch",
    "text.decision.localize": "screens", "text.decision.screen_review": "screens",
    "text.decision.verification": "screens",
    "text.decision.manager": "manager", "text.decision.wake": "manager", "text.decision.route": "manager",
    "text.decision.retry": "manager", "text.decision.model": "manager",
    "text.decision.testprompt_on_failure": "testprompt",
    "agent.atlas": "atlas", "agent.forge": "forge", "agent.browser": "browser", "agent.mcp_prompt": "mcp",
    "public.ask": "public",
}


def family_of(key: str) -> str:
    """Family id of a usage key for grouping the AI usage table (Sherlock chat / background / verdict together).
    Ids are translated on the page; an unlisted key falls back to its root (vision | text | agent)."""
    if key in _FAMILY_BY_KEY:
        return _FAMILY_BY_KEY[key]
    root = key.split(".", 1)[0]
    return root if root in ("vision", "text", "agent") else "other"


def short_label(key: str) -> str:
    """Human name of a usage for the page: the catalogue label without the "(decision model, shadow)" suffix."""
    import re
    usage = USAGES.get(key)
    if not usage:
        return key
    return re.sub(r"\s*\((?:decision model)[^)]*\)\s*$", "", usage.label).strip() or usage.label


# --- categories (TASK-87 round 2) -------------------------------------------------------------------
# The simple groups the AI usage page speaks in. ONE mapping, here: every catalogue usage appears in
# _CATEGORY_BY_KEY (a test enforces it), so adding a usage forces a decision about its category.
CATEGORIES = ("ask_ai", "discard_script", "discard_incident", "script_creation", "screen_recognition",
              "transcripts", "showcase", "web_lookup", "other")

_CATEGORY_BY_KEY = {
    # Ask AI: free questions and chat answers
    "vision.ask": "ask_ai", "public.ask": "ask_ai", "agent.atlas": "ask_ai", "agent.mcp_prompt": "ask_ai",
    "vision.screenshot": "ask_ai", "vision.describe": "ask_ai",
    # Discard script: is a failed script run real or noise
    "agent.sherlock": "discard_script", "analyzer.sherlock": "discard_script",
    "text.decision.sherlock": "discard_script", "text.decision.testprompt_on_failure": "discard_script",
    # Discard incident: is a monitoring alert real or noise
    "agent.nightwatch": "discard_incident", "vision.alert_triage": "discard_incident",
    "text.decision.freeze_triage": "discard_incident",
    # Script creation: building tests, trees and scripts
    "agent.forge": "script_creation", "text.plan": "script_creation", "vision.explore": "script_creation",
    "vision.dom": "script_creation",
    # Screen recognition: which screen is this, what does it show
    "vision.banner": "screen_recognition", "vision.menu": "screen_recognition",
    "vision.quality": "screen_recognition", "text.decision.localize": "screen_recognition",
    "text.decision.screen_review": "screen_recognition", "text.decision.verification": "screen_recognition",
    # Transcripts & translation
    "text.transcript": "transcripts", "text.transcript_correction": "transcripts",
    "text.translation": "transcripts", "vision.subtitle": "transcripts",
    # Showcase / games
    "vision.drone": "showcase", "text.game_2048": "showcase", "text.game_strategy": "showcase",
    # Web lookup
    "text.web": "web_lookup",
    # Other: roots, the browser agent, the session manager, reports
    "agent": "other", "vision": "other", "text": "other", "agent.browser": "other", "text.report": "other",
    "text.decision": "other", "text.decision.manager": "other", "text.decision.wake": "other",
    "text.decision.route": "other", "text.decision.retry": "other", "text.decision.model": "other",
}


def category_of(key: str) -> str:
    """Category id of a usage key. A key the table does not list (a dynamic ``agent.<id>`` or a feature usage)
    follows its nearest listed ancestor, else ``other``."""
    if key in _CATEGORY_BY_KEY:
        return _CATEGORY_BY_KEY[key]
    base = key.split(_SKILL_MARKER, 1)[0]
    while base:  # walk the dotted ancestors, the roots excluded: text.web.companion -> text.web
        if base in _CATEGORY_BY_KEY and base not in ROOT_USAGES:
            return _CATEGORY_BY_KEY[base]
        base = base.rsplit(".", 1)[0] if "." in base else ""
    return "other"
