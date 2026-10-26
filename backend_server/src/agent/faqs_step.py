"""Atlas Prepared FAQ — manager-side hook (TASK-152 phase 9).

The Atlas chat loop (``backend_server/src/agent/core/manager.py`` ``QAManagerAgent._process_message``)
runs this short-circuit right after the quick step (TASK-140) and before the model loop. A hit
answers the user in <10 ms with no model call; a miss logs a row to ``atlas_faq_log`` with
``match_source='none'`` and lets the model take over (a model answer that cites a ``docs/`` path
self-promotes via ``agent_faq_db.upsert_promoted``).

Why a separate module:
- keeps ``manager.py`` diff small;
- the helper is testable in isolation, with a fake cache + DB;
- the contract is two methods: ``enabled()`` to check the kill switch, and ``process(message, session)``
  returning a list of ``(event, faq_log_dict_or_none)`` pairs the manager iterates and yields.

The match source is always reported via ``atlas_faq_log`` so the benchmark, the review pass, and
the dashboard all see one consistent timeline.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Optional

from . import faqs
from shared.src.lib.database import agent_faq_db
from .core.message_types import AgentEvent, EventType


_CITE_PATTERN = re.compile(r"docs/[A-Za-z0-9_./\\-]+\.md\b")


@dataclass
class FaqTurnDecision:
    """What the manager should do for this Atlas turn after the FAQ step.

    - ``answer``: short text to send (the FAQ short version). ``None`` for miss.
    - ``source``: one of faqs.SOURCE_HOT / SOURCE_EXACT / SOURCE_NORMALISED / SOURCE_ALIAS / SOURCE_NONE.
    - ``faq_id``: which row answered, ``None`` on miss.
    - ``log``: a dict shaped for ``agent_faq_db.record_question`` (always present on a consulted
      question, even on a miss). ``None`` when the FAQ was never consulted at all — the message was
      a live device operation and was handed straight back to the router.
    """
    answer: Optional[str]
    source: str
    faq_id: Optional[str]
    latency_ms: int
    had_answer: bool
    log: Optional[dict]


def step(message: str, session, *, team_id: Optional[str] = None, user_id: Optional[str] = None,
         session_id: Optional[str] = None) -> FaqTurnDecision:
    """One-shot. Returns a ``FaqTurnDecision`` the manager converts to events.

    Never raises. Never blocks on a DB problem (every DB read/write is fail-soft via
    ``agent_faq_db``). A hit answers in <5 ms wall clock against the in-memory hot cache; a
    miss adds ~10–30 ms for the canonical SQL fallback.
    """
    started = time.time()
    if not faqs.enabled() or not message:
        return FaqTurnDecision(
            answer=None, source=faqs.SOURCE_NONE, faq_id=None,
            latency_ms=int((time.time() - started) * 1000),
            had_answer=False,
            log=_log(team_id, session_id, user_id, message, faqs.SOURCE_NONE, None, 0, False),
        )

    # A live operation ("Take control of stb3", "Is stb3 free or in use?") is not a documentation
    # question, and this tier short-circuits the turn: a hit here never reaches the router, so the
    # action would never run and the user would get a stored paragraph instead. Hand it back.
    #
    # A miss and a hand-back reach the same place downstream, so this only matters where a hit
    # would be wrong. Nothing is logged for a hand-back: the FAQ was never consulted, so counting
    # it as a miss would make "no FAQ answer was given" look like "the FAQ could not answer this".
    #
    # Nothing is logged for a hand-back: the FAQ was never consulted, so counting it as a miss
    # would make "no FAQ answer was given" look like "the FAQ could not answer this".
    if faqs.should_decline(message):
        return FaqTurnDecision(
            answer=None, source=faqs.SOURCE_NONE, faq_id=None,
            latency_ms=int((time.time() - started) * 1000),
            had_answer=False,
            log=None,
        )

    # Hot cache: rebuild it when it has gone stale. ``maybe_refresh`` is a no-op while the
    # snapshot is fresh (the common case), so this costs one monotonic-time comparison per turn.
    # It replaces the old "load once per process" behaviour that left rows promoted after boot
    # invisible to tier 1 until the next restart.
    try:
        faqs.maybe_refresh()
    except Exception as exc:  # noqa: BLE001 - a refresh problem never breaks a turn
        print(f"[FAQ] hot cache refresh skipped: {exc}")

    cache = faqs.cache()
    hit = cache.lookup(message)

    # A hot-cache *alias* hit is only a guess. If the cache returned nothing, or returned an
    # alias match weaker than a full canonical match, ask the database for the canonical row on
    # the normalised question first: it is an indexed equality lookup and it is exact. Without
    # this, a weak token-overlap guess short-circuits the answer the user actually asked for —
    # that is how "Which IR standard do you use?" came to be answered with the env_backup row.
    canonical = None
    if hit is None or hit.score < 1.0:
        try:
            canonical = agent_faq_db.find_match(faqs.normalize(message))
        except Exception:  # noqa: BLE001
            canonical = None

    if canonical is not None:
        from .faqs import FaqEntry
        elapsed = _ms(started)
        entry = FaqEntry.from_row(canonical)
        return FaqTurnDecision(
            answer=_render_from_entry(entry),
            source=faqs.SOURCE_NORMALISED,
            faq_id=entry.id,
            latency_ms=elapsed,
            had_answer=True,
            log=_log(team_id, session_id, user_id, message,
                     faqs.SOURCE_NORMALISED, entry.id, elapsed, True),
        )

    if hit is None:
        elapsed = _ms(started)
        miss_log = _log(team_id, session_id, user_id, message, faqs.SOURCE_NONE, None, elapsed, False)
        # A miss used to be invisible: the manager only logs a decision that carried an answer, so
        # ``atlas_faq_log`` never got a ``match_source='none'`` row and the log showed what the FAQ
        # answered, never what it failed on. That is the signal that says which questions to add,
        # so the miss is written here — in a thread, because the model is about to run.
        _log_in_background(miss_log)
        return FaqTurnDecision(
            answer=None, source=faqs.SOURCE_NONE, faq_id=None,
            latency_ms=int((time.time() - started) * 1000),
            had_answer=False,
            log=miss_log,
        )

    answer_text = _render(hit)
    elapsed_ms = _ms(started)
    decision = FaqTurnDecision(
        answer=answer_text,
        source=hit.source,
        faq_id=hit.entry.id,
        latency_ms=elapsed_ms,
        had_answer=True,
        log=_log(team_id, session_id, user_id, message, hit.source, hit.entry.id, elapsed_ms, True),
    )
    return decision


def emit(decision: FaqTurnDecision, *, agent_name: str):
    """Yield the events the chat route sends on a hit. On a miss, yields nothing.

    Returns a list so it's a plain function rather than a generator — manager.py calls
    ``for ev in faqs_step.emit(decision, agent_name=self.nickname): yield ev``.

    Emits ``message`` + ``session_ended`` so the chat route ends the turn cleanly on a hit.
    Without the second event, ``atlas_chat.py`` and the browser both wait for a session
    closure that never arrives — same behaviour the quick step has, and same fix.
    """
    if decision.answer is None:
        return []
    return [
        AgentEvent(
            type=EventType.MESSAGE,
            agent=agent_name,
            content=decision.answer,
            metrics={"duration_ms": decision.latency_ms, "match_source": decision.source,
                     "faq_id": decision.faq_id},
        ),
        AgentEvent(
            type=EventType.SESSION_ENDED,
            agent=agent_name,
            content="Done",
        ),
    ]


def write_session(decision: FaqTurnDecision, session, *, agent_name: str) -> None:
    """Append the assistant text to the session so the next turn's history knows what was said."""
    if decision.answer is None:
        return
    session.add_message("assistant", decision.answer, agent=agent_name)


def record_log(decision: FaqTurnDecision) -> None:
    """Persist the log row (async, fire-and-forget; the DB module never raises).

    A hand-back (the FAQ was never consulted) carries no log row.
    """
    if not decision.log:
        return
    agent_faq_db.record_question(**decision.log)


def maybe_promote_from_model_answer(question_text: str, answer_text: str) -> Optional[str]:
    """Self-promotion: when the model answered a docs question and cited a ``docs/*.md`` path, store
    the (question, answer) pair in ``agent_faq`` as ``proposed=true`` for the daily review pass.

    Returns the new entry's id, or ``None``. Never raises. Phase 9a ships the citation regex only;
    phase 9b adds per-path scoring. Today any non-empty answer with at least one cited path
    becomes a candidate.

    The id is also written to ``atlas_faq_log`` with ``match_source='proposed_promote'`` so the
    benchmark sees the learning loop end-to-end.
    """
    if not question_text or not answer_text:
        return None
    paths = sorted(set(_CITE_PATTERN.findall(answer_text)))
    if not paths:
        return None
    normalised = faqs.normalize(question_text)
    if not normalised:
        return None
    short = _short(answer_text)
    long = answer_text.strip()
    faq_id = agent_faq_db.upsert_promoted(
        question_text=question_text,
        normalised=normalised,
        short=short,
        long=long,
        sources=paths,
        tags=["promoted"],
    )
    if faq_id:
        agent_faq_db.record_question(
            team_id=None, session_id=None, user_id=None,
            question_text=question_text, normalised=normalised,
            match_source=faqs.SOURCE_PROPOSED, faq_id=faq_id,
            latency_ms=0, had_answer=True,
        )
    return faq_id


def count_bump(decision: FaqTurnDecision) -> None:
    """Background bump of ``agent_faq.count``. Fire-and-forget; never blocks the turn."""
    if decision.faq_id:
        agent_faq_db.increment_count(decision.faq_id)


def _log_in_background(log: dict) -> None:
    """Write one log row without blocking the turn.

    The miss path runs in front of the model call, so the write must not add its latency to the
    turn. A daemon thread is enough: the row is an audit trail, and the server is restarted
    often enough that a lost row on a hard kill does not matter.
    """
    if not log:
        return
    def _write() -> None:
        try:
            agent_faq_db.record_question(**log)
        except Exception:  # noqa: BLE001 - an audit row never breaks a turn
            pass
    try:
        threading.Thread(target=_write, name="faq-log", daemon=True).start()
    except Exception as exc:  # noqa: BLE001 - an audit row never breaks a turn
        # Creating the thread can fail on its own (no thread slots left, a patched threading
        # module). That must not take the user's turn down with it.
        print(f"[FAQ] background miss log could not be started: {exc}")


# --------------------------------------------------------------------------- internals

def _render(hit: faqs.FaqHit) -> str:
    """The text the chat sends. Short version; the long form is reserved for "more" later."""
    text = hit.entry.short.strip()
    sources = hit.entry.sources or ()
    if sources:
        text += "\n\nSources: " + ", ".join(sources[:3])
    return text


def _render_from_entry(entry) -> str:
    """Same shape as ``_render`` but for tier-2 (DB) hits where we don't have a ``FaqHit``."""
    text = str(getattr(entry, "short", "") or "").strip()
    sources = getattr(entry, "sources", None) or ()
    if sources:
        text += "\n\nSources: " + ", ".join(list(sources)[:3])
    return text


def _short(text: str, limit: int = 280) -> str:
    """First sentence of an answer, length-capped. Used for self-promoted rows."""
    text = " ".join(text.split())
    for sep in (". ", "! ", "? ", "\n"):
        if sep in text:
            text = text.split(sep, 1)[0]
            break
    return text[:limit]


def _log(team_id, session_id, user_id, message, source, faq_id, latency_ms, had_answer) -> dict:
    return {
        "team_id": team_id,
        "session_id": session_id,
        "user_id": user_id,
        "question_text": message or "",
        "normalised": faqs.normalize(message or ""),
        "match_source": source,
        "faq_id": faq_id,
        "latency_ms": int(latency_ms or 0),
        "had_answer": bool(had_answer),
    }


def _ms(started: float) -> int:
    return int((time.time() - started) * 1000)
