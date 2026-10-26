"""Which agent answers a chat message, decided before any model call (TASK-175).

Three deterministic rules in front of Atlas, all matched on the FAQ's ``normalize()``:

- **Forge owns script work.** Creating or changing a script, a testcase or a virtual script is Forge's
  job (owner, 2026-10-26). An Atlas message that asks for it is handed to Forge before Atlas spends a
  token; running an existing script stays with Atlas.
- **Masterchief owns fleet changes, Sherlock owns failure analysis.** Atlas cannot restart a service
  (its ``system-ops`` skill is read-only), so an ops change gets a short answer and a button to
  Masterchief, with no model call. A "why did it fail" question is still answered by Atlas, with a
  button to Sherlock beside the answer.
- **A vague short ask gets one clarifying question.** "cap 5", "a", "r": the model used to guess a
  meaning and explore the lab (BUG-0914 started that way). Two or three words that name no action,
  no object and no device are answered with a question, no tool, no model call.

Every function is pure and fails closed to "no rule": a message the rules do not recognise goes to
the agent the user picked, unchanged.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from . import faqs

FORGE = "scripter"
MASTERCHIEF = "masterchief"
SHERLOCK = "analyzer"

AGENT_NAMES = {FORGE: "Forge", MASTERCHIEF: "Masterchief", SHERLOCK: "Sherlock"}

# Verbs that create or change script work. "run" / "execute" are not here: running an existing script
# is Atlas's (script-management).
_SCRIPT_WORK_VERBS = frozenset({
    "create", "make", "write", "build", "generate", "add", "new", "edit", "modify", "update", "change",
    "fix", "rename", "refactor", "rewrite", "duplicate", "copy", "convert", "improve", "extend",
})
_SCRIPT_OBJECTS = frozenset({"script", "scripts", "testcase", "testcases", "test-case", "test-cases"})
# How far into the message the verb may sit: "please create a script", "can you write a testcase".
_VERB_WINDOW = 4

_OPS_VERBS = frozenset({"restart", "reboot", "cleanup", "clean", "purge", "free", "kill", "reload"})
_OPS_OBJECTS = frozenset({
    "server", "servers", "service", "services", "host", "hosts", "disk", "space", "storage", "logs",
    "captures", "capture", "cache", "pi", "vm",
})
_OPS_SERVICE_RE = re.compile(r"\bvpt-[a-z][a-z0-9-]*\b")

_ANALYSIS_RE = re.compile(
    r"\b(why did|why does|why is|what went wrong|root cause|analy[sz]e|investigate|explain the failure)\b")
_ANALYSIS_OBJECTS = frozenset({
    "run", "runs", "result", "results", "script", "scripts", "test", "tests", "testcase", "execution",
    "campaign", "fail", "failed", "failure", "failing",
})

# Words that make a short message a real ask: actions, objects, pages, states, greetings. A message of
# at most three words with none of these, and no device name, is vague.
_KNOWN_WORDS = frozenset(faqs.COMMAND_VERBS) | faqs.RUNTIME_NOUNS | faqs.LIVE_STATE_WORDS | frozenset({
    "heatmap", "alerts", "alert", "incidents", "incident", "dashboard", "dashboards", "analytics",
    "devices", "hosts", "scripts", "testcases", "testcase", "campaigns", "campaign", "requirements",
    "results", "reports", "report", "runs", "logs", "status", "health", "storage", "disk", "kpi",
    "kpis", "radar", "settings", "docs", "help", "videos", "video", "screenshot", "screenshots",
    "remote", "keys", "tree", "trees", "navigation", "nodes", "interfaces", "interface", "userinterfaces",
    "pages", "page", "home", "live", "guide", "menu", "back", "ok", "hi", "hello", "hey", "thanks",
    "thank", "yes", "no", "say", "ping", "test", "tests", "drone", "tello", "fly", "land", "takeoff",
    "monitoring", "monitor", "fleet", "deployments", "deployment", "schedule", "queue", "usage",
    "cost", "tokens", "model", "models", "profile", "team", "users", "user", "project", "projects",
    "variant", "variants", "transcript", "audio", "subtitles", "zap", "channel", "volume", "power",
    # follow-ups that only mean something after an answer: the history gives them their meaning
    "again", "retry", "rerun", "redo", "continue", "more", "next", "cancel", "undo", "same", "both",
    "all", "first", "second", "last", "that", "this", "it",
})
_VAGUE_MAX_WORDS = 3


def _words(message: str) -> list[str]:
    return faqs.normalize(message or "").split()


def forge_handoff(message: str) -> bool:
    """True when the message asks to create or change a script, a testcase or a virtual script."""
    try:
        words = _words(message)
        if not words:
            return False
        has_object = bool(_SCRIPT_OBJECTS.intersection(words)) or any(
            a == "test" and b in ("case", "cases") for a, b in zip(words, words[1:]))
        if not has_object:
            return False
        return any(w in _SCRIPT_WORK_VERBS for w in words[:_VERB_WINDOW])
    except Exception:  # noqa: BLE001 - no rule
        return False


def ops_change(message: str) -> bool:
    """True when the message asks to change the fleet (restart, reboot, clean up): Masterchief's job."""
    try:
        words = _words(message)
        if not words or not any(w in _OPS_VERBS for w in words[:_VERB_WINDOW]):
            return False
        return bool(_OPS_OBJECTS.intersection(words)) or bool(_OPS_SERVICE_RE.search(" ".join(words)))
    except Exception:  # noqa: BLE001
        return False


def failure_analysis(message: str) -> bool:
    """True when the message asks why a run failed: Sherlock is the result analyst."""
    try:
        text = faqs.normalize(message or "")
        return bool(_ANALYSIS_RE.search(text)) and bool(_ANALYSIS_OBJECTS.intersection(text.split()))
    except Exception:  # noqa: BLE001
        return False


def is_vague(message: str, device_names: Iterable[str] = ()) -> bool:
    """True when a short message names no action, no object, no page and no device."""
    try:
        words = _words(message)
        if not words or len(words) > _VAGUE_MAX_WORDS:
            return False
        names = {faqs.normalize(n) for n in device_names or () if n}
        text = " ".join(words)
        if any(n and n in text for n in names):
            return False
        return not any(w in _KNOWN_WORDS or _known_prefix(w) for w in words)
    except Exception:  # noqa: BLE001
        return False


def _known_prefix(word: str) -> bool:
    """A device-like token ("stb3", "host1") or an inflected known word ("screenshots", "listing")."""
    if len(word) >= 4 and any(len(n) >= 3 and word.startswith(n) for n in faqs.RUNTIME_NOUNS):
        return True
    return len(word) >= 5 and any(word.startswith(k) for k in _KNOWN_WORDS if len(k) >= 5)


def clarify_text(message: str) -> str:
    shown = (message or "").strip()[:60]
    return (f'I\'m not sure what "{shown}" means. What would you like to do? For example: '
            '"list my test cases", "take a screenshot of <device>", "show the open alerts" '
            'or "create a script that …".')


def ops_text() -> str:
    return ("Restarting services, rebooting and cleaning up hosts is Masterchief's job: every change it "
            "makes is a confirm card you approve. Ask Masterchief to do it.")


def suggestion(message: str) -> Optional[str]:
    """The agent to suggest beside an Atlas answer, or None."""
    if ops_change(message):
        return MASTERCHIEF
    if failure_analysis(message):
        return SHERLOCK
    return None
