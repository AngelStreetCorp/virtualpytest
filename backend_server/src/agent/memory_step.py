"""Atlas daily memory — manager-side hook (TASK-172).

The Atlas chat loop (``backend_server/src/agent/core/manager.py`` ``_process_message``) runs this
tier **in front of** the quick step and the Prepared FAQ:

    memory  →  quick step  →  Prepared FAQ  →  model

Why in front of the quick step: the quick step answers a short command with one small model call
plus one tool, and it short-circuits the turn. If the memory sat behind it, a user who asks the
same thing twice would never reach the memory — the quick step would answer both times and the
memory would never be exercised.

Why the memory still stands down for the FAQ: the FAQ holds a *curated, reviewed* answer for the
docs questions, and it answers them in under 10 ms. A user's own recollection is more specific but
it is not more correct. So when the FAQ hot cache has a row for the question, the memory steps
aside and the FAQ answers, exactly as today. The FAQ lookup is an in-process dict hit — free.

A hit answers the turn from the memory and short-circuits the model: the second ask returns the
artefact of the first ask instead of creating a second one. The answer says so, in words, and offers
"say 'again' to run it now". Before it answers, the artefacts the memory names (a script, a
userinterface) are checked to still exist; a memory of something deleted is dropped, not recalled.

(A "context" mode that injected the memory into the prompt instead was measured to save nothing —
TASK-172 §8 — and was removed.)

Switch: ``ATLAS_MEMORY=optin|off|on`` (default optin = on demand per user).
Every public function fails soft — a memory problem never breaks an Atlas turn.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import faqs, memory
from .core.message_types import AgentEvent, EventType

# Match sources reported in the memory log.
SOURCE_RECALL = "memory_recall"
SOURCE_NONE = "none"


# Session keys. The memory remembers, per session, which questions it already answered from the
# memory, so asking the same thing again in the same session (or saying "again") runs it for real.
_RECALLED_KEYS = "atlas_memory_recalled_keys"
_LAST_RECALL = "atlas_memory_last_recall"

# The words that mean "run what you just recalled, now". Normalised (faqs.normalize) forms.
RERUN_WORDS = frozenset({
    "again", "do it again", "run it again", "run it now", "again please", "redo", "rerun",
    "re run", "once more", "do it now", "run again",
})


@dataclass
class MemoryDecision:
    """What the manager should do with this turn after the memory tier.

    - ``answer``: the text to send. ``None`` when the memory does not answer.
    - ``entry``: the memory entry that matched, ``None`` on a miss.
    - ``source``: ``memory_recall`` or ``none``.
    - ``log``: a dict for the memory log; ``None`` when the memory was never consulted.
    """

    answer: Optional[str]
    entry: Optional[memory.MemoryEntry]
    source: str
    latency_ms: int
    had_answer: bool
    log: Optional[dict] = None


def _log(team_id, session_id, user_id, question, source, entry, latency_ms, had_answer) -> dict:
    return {
        "ts": time.time(),
        "team_id": str(team_id) if team_id else None,
        "session_id": session_id or None,
        "user_id": str(user_id) if user_id else None,
        "question": (question or "")[:200],
        "source": source,
        "day": entry.day if entry else None,
        "entry_ts": entry.ts if entry else None,
        "latency_ms": latency_ms,
        "had_answer": bool(had_answer),
    }


def step(message: str, session, *, team_id: Optional[str] = None, user_id: Optional[str] = None,
         session_id: Optional[str] = None) -> MemoryDecision:
    """One-shot. Returns the decision the manager turns into events.

    Never raises. Never blocks on anything but a small file read.
    """
    started = time.time()

    def _miss(reason: str) -> MemoryDecision:
        return MemoryDecision(
            answer=None, entry=None, source=SOURCE_NONE,
            latency_ms=int((time.time() - started) * 1000), had_answer=False,
        )

    if not message or not memory.enabled_for(team_id, user_id):
        return _miss("off")

    # A live action or a live-state question is never answered from the memory — the same rule
    # the FAQ follows ("send cmd to stb", "is stb3 free?"). A recollection of a command is not the
    # command, and the lab may have changed since.
    if is_live_operation(message):
        return _miss("live_operation")

    # The user already got this answer from the memory in this session and asks again: they want
    # it run, not recalled twice.
    key = memory.question_key(message)
    if key and key in _recalled_keys(session):
        return _miss("asked_again")

    # The FAQ answers the docs questions from a curated store, in under 10 ms. It keeps priority.
    # The lookup is an in-process dict hit (the hot cache), so this costs nothing.
    try:
        faq_hit = faqs.cache().lookup(message)
    except Exception:  # noqa: BLE001
        faq_hit = None
    if faq_hit is not None:
        return _miss("faq_has_a_row")

    try:
        entry = memory.lookup(team_id, user_id, message)
    except Exception:  # noqa: BLE001
        entry = None
    if entry is None:
        return _miss("no_entry")

    gone = artefact_gone(entry, team_id)
    if gone:
        # A memory of a deleted script / userinterface would answer with something that is not
        # there any more: drop it and let the turn run for real.
        memory.forget_key(team_id, user_id, entry.key)
        return _miss("artefact_gone")

    _remember_recall(session, entry)
    elapsed = int((time.time() - started) * 1000)
    log = _log(team_id, session_id, user_id, message, SOURCE_RECALL, entry, elapsed, True)
    return MemoryDecision(
        answer=entry.render(), entry=entry, source=SOURCE_RECALL, latency_ms=elapsed,
        had_answer=True, log=log,
    )


# The FAQ's runtime nouns without "script": a script is an artefact the memory is meant to recall,
# not a piece of the lab.
_LAB_TARGETS = frozenset(faqs.RUNTIME_NOUNS - {"script", "scripts"})


_CREATE_VERBS = frozenset({"create", "make", "build", "add", "new", "write", "generate", "save", "define"})
_RUN_VERBS = frozenset({"run", "rerun", "execute", "launch", "start", "restart", "stop", "replay"})
_RUNNABLES = frozenset({"script", "scripts", "campaign", "campaigns", "testcase", "testcases", "test", "tests"})


def _names_lab_target(token: str) -> bool:
    """A device or host noun, or a name built on one ("stb3", "host1") — the FAQ's own rule."""
    if token in _LAB_TARGETS:
        return True
    return len(token) >= 4 and any(len(noun) >= 3 and noun in token for noun in _LAB_TARGETS)


def is_live_operation(message: str) -> bool:
    """True when the message acts on, or asks the live state of, a device or a host.

    Narrower than the FAQ's ``should_decline``, which hands EVERY short command to the router
    ("create a script" included) because the docs store answers none of them. The memory exists
    for repeated commands, so it only stands down where the lab itself is involved: a command or a
    live-state question that names a runtime target ("send cmd to stb", "is stb3 free?"). Fails
    closed: an error counts as a live operation.
    """
    try:
        if not faqs.is_device_operation(message):
            return False
        words = faqs.normalize(message).split()
        # Creating a script, a userinterface or a page writes to the database, not to the lab:
        # "create a user interface for an android_tv device" names a device MODEL, not a device.
        # It is live only when it also asks to run something.
        if words and words[0] in _CREATE_VERBS:
            return bool(_RUN_VERBS.intersection(words[1:])) and bool(_RUNNABLES.intersection(words))
        if any(_names_lab_target(word) for word in words):
            return True
        # Running a script or a campaign drives devices: a recollection of the run is not a run.
        return bool(_RUN_VERBS.intersection(words)) and bool(_RUNNABLES.intersection(words))
    except Exception:  # noqa: BLE001
        return True


# The artefact ids a recall can check, and how. A generic ``id=`` is ambiguous and not checked.
_CHECKED_IDS = ("virtual_script_id", "script_id", "userinterface_id")


def _artefact_exists(kind: str, value: str, team_id: str) -> bool:
    if kind in ("virtual_script_id", "script_id"):
        from shared.src.lib.database.virtual_scripts_db import get_virtual_script
        return bool(get_virtual_script(value, team_id))
    from shared.src.lib.database.userinterface_db import get_userinterface
    return bool(get_userinterface(value, team_id))


def artefact_gone(entry: memory.MemoryEntry, team_id: Optional[str],
                  exists=None) -> Optional[str]:
    """The first artefact of the entry that no longer exists (``kind=value``), else None.

    Fails open to "still there" on a lookup error: a database hiccup must not erase a memory.
    """
    if not team_id:
        return None
    check = exists or _artefact_exists
    for token in entry.artefacts:
        kind, _, value = token.partition("=")
        if kind not in _CHECKED_IDS or not value:
            continue
        try:
            if not check(kind, value, str(team_id)):
                return token
        except Exception:  # noqa: BLE001
            continue
    return None


def _recalled_keys(session) -> list:
    try:
        value = session.context.get(_RECALLED_KEYS) if getattr(session, "context", None) is not None else None
    except Exception:  # noqa: BLE001
        return []
    return value if isinstance(value, list) else []


def _remember_recall(session, entry: memory.MemoryEntry) -> None:
    try:
        if getattr(session, "context", None) is None:
            return
        keys = _recalled_keys(session)
        if entry.key not in keys:
            session.context[_RECALLED_KEYS] = keys + [entry.key]
        session.context[_LAST_RECALL] = entry.question
    except Exception:  # noqa: BLE001 - a context write never breaks the turn
        pass


def resolve_rerun(message: str, session) -> Optional[str]:
    """The question to run for real when the user says "again" after a recall, else ``None``.

    The recall answer ends with "say 'again' to run it now"; this is the other half. "again" only
    means something right after a recall in the same session, so without one it is left alone.
    """
    try:
        if faqs.normalize(message or "") not in RERUN_WORDS:
            return None
        if getattr(session, "context", None) is None:
            return None
        question = session.context.get(_LAST_RECALL)
        if not question:
            return None
        session.context[_LAST_RECALL] = None
        return str(question)
    except Exception:  # noqa: BLE001
        return None


def emit(decision: MemoryDecision, *, agent_name: str):
    """The events the chat route sends on a recall hit.

    ``message`` + ``session_ended`` so the turn ends cleanly — same as the FAQ tier and the quick
    step. Without the second event the browser waits for a closure that never comes.
    """
    if decision.answer is None:
        return []
    return [
        AgentEvent(
            type=EventType.MESSAGE,
            agent=agent_name,
            content=decision.answer,
            metrics={"duration_ms": decision.latency_ms, "match_source": decision.source,
                     "memory_day": decision.entry.day if decision.entry else None},
        ),
        AgentEvent(
            type=EventType.SESSION_ENDED,
            agent=agent_name,
            content="Done",
        ),
    ]


def write_session(decision: MemoryDecision, session, *, agent_name: str) -> None:
    """Append the assistant text to the session so the next turn's history knows what was said."""
    if decision.answer is None:
        return
    try:
        session.add_message("assistant", decision.answer, agent=agent_name)
    except Exception:  # noqa: BLE001
        pass


def _log_path(team_id: Optional[str], user_id: Optional[str]) -> Optional[Path]:
    directory = memory.user_dir(team_id, user_id)
    if directory is None:
        return None
    return directory / "memory.log.jsonl"


def record_log(decision: MemoryDecision, *, team_id: Optional[str] = None,
               user_id: Optional[str] = None) -> None:
    """Append the decision to the user's memory log. Fire-and-forget; never raises.

    The log is a file next to the memory, not a database table: the prototype must not need a
    migration, and the log is only read by the benchmark.
    """
    if not decision.log:
        return
    path = _log_path(team_id, user_id)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(decision.log, default=str) + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"[MEMORY] log write skipped: {exc}")


def record_turn(*, team_id: Optional[str], user_id: Optional[str], question: str, answer: str,
                tool_calls=None, results=None) -> Optional[Path]:
    """Remember one exchange. Called at the end of a turn that reached the model.

    The write is deterministic: the question, the tools that ran, the artefacts they produced and
    the answer. No model call, so it costs zero tokens.

    Only a turn that DID something is remembered: at least one successful tool call that acts or
    creates (not ``get_`` / ``list_`` / ``search_`` / ``read_`` …). A turn with no tool call ("I
    don't understand", a clarifying question), whose tools all failed, or that only looked has
    nothing worth recalling — replaying it would hand the user the same non-answer for 14 days.
    Failed calls are left out of the entry as well.
    """
    tools = []
    artefacts = []
    for index, call in enumerate(tool_calls or []):
        if not isinstance(call, dict):
            continue
        result = results[index] if results and index < len(results) else None
        if not _call_succeeded(call, result):
            continue
        name = call.get("tool_name") or call.get("name")
        if name:
            tools.append(str(name))
        if is_read_only_tool(name):
            # What the model LOOKED at is not what the turn produced: a script read as a template
            # must not be named as the artefact (quality bench, 2026-10-25).
            continue
        params = call.get("params") if isinstance(call.get("params"), dict) else call.get("input")
        artefacts.extend(memory._artefacts_from(params, result))
    # Only a turn that acted or created something is worth recalling; a turn that only looked
    # (docs, lists, an empty transcript) is the FAQ's job or a live question.
    if not tools or all(is_read_only_tool(t) for t in tools):
        return None
    return memory.record(team_id=team_id, user_id=user_id, question=question, answer=answer,
                         tools=tools, artefacts=artefacts)


# Tools that only look: a turn made of these produced nothing to recall ("cap 5" searched the docs
# and read an empty transcript, 2026-10-25). Prefix match on the MCP tool name.
_READ_ONLY_PREFIXES = (
    "get_", "list_", "search_", "read_", "dump_", "capture_", "describe_", "query_", "view_",
    "ping_", "check_", "preview_", "load_", "analyze_", "verify_", "localize",
)


def is_read_only_tool(name: str) -> bool:
    return str(name or "").startswith(_READ_ONLY_PREFIXES)


def _call_succeeded(call: dict, result) -> bool:
    """True when a tool call worked: not flagged failed, and its result carries no error."""
    if call.get("success") is False:
        return False
    if isinstance(result, dict):
        if result.get("isError") or result.get("success") is False or result.get("error"):
            return False
    return True
