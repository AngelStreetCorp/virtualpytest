"""Fact check (TASK-05 L4c): a checkable claim from a debate digest, checked with a live web search.

Opt-in per device (``DEVICE{N}_COMPANION_FACTCHECK=true``) and capped per device
(``COMPANION_FACTCHECK_PER_HOUR``, default 6): every check is one web-grounded call
(``text.web.companion.factcheck``, which the gateway only answers with a search).

Verdicts are ``supported`` / ``contradicted`` / ``unverified``. A verdict other than unverified needs at
least one source URL, whatever the model says: a claim is never shown as false (or true) without a
page that says so. Opinions, predictions and claims too vague to search come back unverified.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from datetime import date
from typing import Callable, Optional

from .enrich import _merge_sources, listed_sources
from .identify import extract_json
from .usages import FACTCHECK

VERDICTS = ("supported", "contradicted", "unverified")
DEFAULT_PER_HOUR = 6

LookupFn = Callable[[str], dict]


def claim_key(text: str) -> str:
    return re.sub(r"[^\w]+", " ", (text or "").lower()).strip()


def build_prompt(claim: str, speaker: Optional[str], programme: Optional[str], day: Optional[date] = None,
                 topic: Optional[str] = None) -> str:
    who = speaker or "a participant"
    where = f" in « {programme} »" if programme else ""
    # The claim alone is often too short to search: « Sie können bestimmte Leute bestätigen » found
    # help pages about account permissions; with the topic (US midterms) it is about the Senate.
    about = f"The discussion is about: {topic}\n" if topic else ""
    return (
        f"Fact-check this statement, said on live TV today ({(day or date.today()).isoformat()}){where} by {who}:\n"
        f"« {claim} »\n{about}\n"
        "Search the web, then answer ONLY with one JSON object:\n"
        '{"verdict": "supported" | "contradicted" | "unverified",\n'
        ' "note": "one sentence: what the sources say",\n'
        ' "sources": [the URLs of the pages you used]}\n'
        "supported / contradicted only when a page you found states it. Anything else (an opinion, a\n"
        "prediction, a statement too vague to check, nothing found) is unverified. Do not use memory.\n"
        "Write the note in the language of the statement."
    )


def parse(content: str, sources: list[dict]) -> Optional[dict]:
    """``{verdict, note, sources}``; a verdict without any source becomes unverified. An unverified claim
    keeps no sources: the pages a search returned without settling it are not evidence (live, they were
    help pages unrelated to the claim)."""
    raw = extract_json(content)
    if raw is None:
        return None
    verdict = raw.get("verdict") if raw.get("verdict") in VERDICTS else "unverified"
    found = _merge_sources(sources, listed_sources(content))[:4]
    if not found:
        verdict = "unverified"
    if verdict == "unverified":
        found = []
    note = str(raw.get("note") or "").strip()[:300] or None
    return {"verdict": verdict, "note": note, "sources": found}


def default_lookup(team_id: Optional[str]) -> LookupFn:
    def lookup(prompt: str) -> dict:
        from shared.src.lib.ai import gateway
        return gateway.complete(FACTCHECK, prompt, max_tokens=800, temperature=None, team_id=team_id)
    return lookup


class FactChecker:
    """Claim checks, cached by claim text, run in background threads, capped per device per hour.

    Entry: ``{status: pending|done|failed|capped, verdict, note, sources, at}``.
    """

    def __init__(self, lookup: LookupFn, per_hour: int = DEFAULT_PER_HOUR):
        self._lookup = lookup
        self.per_hour = per_hour
        self._entries: dict[str, dict] = {}
        self._started: dict[str, deque] = {}     # device -> start times in the last hour
        self._lock = threading.Lock()

    def request(self, device_id: str, claim: str, speaker: Optional[str], programme: Optional[str],
                now: Optional[float] = None, *, topic: Optional[str] = None, background: bool = True) -> None:
        """Check ``claim`` once (a claim seen again is not checked again)."""
        key = claim_key(claim)
        now = time.time() if now is None else now
        with self._lock:
            if not key or key in self._entries:
                return
            started = self._started.setdefault(device_id, deque())
            while started and now - started[0] >= 3600:
                started.popleft()
            if len(started) >= self.per_hour:
                self._entries[key] = {"status": "capped", "at": now}
                return
            started.append(now)
            self._entries[key] = {"status": "pending", "at": now}
        if background:
            threading.Thread(target=self._run, args=(key, claim, speaker, programme, topic), daemon=True,
                             name=f"companion-factcheck-{key[:30]}").start()
        else:
            self._run(key, claim, speaker, programme, topic)

    def get(self, claim: str) -> Optional[dict]:
        with self._lock:
            entry = self._entries.get(claim_key(claim))
            return dict(entry) if entry else None

    def skip(self, claim: str, reason: str) -> None:
        """Mark ``claim`` as skipped by the Jev gate (TASK-45): the host asked Jev whether the
        web check is worth running and Jev said no. Stored without any web lookup. ``reason``
        is ``vague`` (P(specific) below the threshold) or ``repeat`` (P(repeat) at/above the
        threshold). ``get()`` returns this entry like any other."""
        if reason not in ("vague", "repeat"):
            reason = "vague"
        key = claim_key(claim)
        with self._lock:
            if not key or key in self._entries:   # never overwrite a real verdict
                return
            self._entries[key] = {"status": "skipped", "reason": reason, "at": time.time()}

    def _run(self, key: str, claim: str, speaker: Optional[str], programme: Optional[str],
             topic: Optional[str] = None) -> None:
        try:
            result = self._lookup(build_prompt(claim, speaker, programme, topic=topic))
            checked = parse(result.get("content") or "", result.get("sources") or []) if result.get("success") else None
            if checked is None:
                entry = {"status": "failed", "error": (result.get("error") or "unparseable answer")[:200]}
            else:
                entry = {"status": "done", **checked}
        except Exception as e:  # a check never kills the worker
            entry = {"status": "failed", "error": str(e)[:200]}
        with self._lock:
            self._entries[key] = {**entry, "at": time.time()}
