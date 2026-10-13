"""Stage 2 — enrich: facts about the identified programme, looked up on the web once.

Keyed by the programme (``entity_key``), so every device on the same match shares one lookup.
Lookups run in the background: the card shows 'pending' until the answer lands. The call uses
the ``text.web.companion`` usage, which the gateway only ever answers with a live web search —
a fact is either sourced or null, never recalled from model memory.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date
from typing import Callable, Optional

from .identify import extract_json
from .profiles import Profile
from .usages import FACTS
from .gates import FACTS_QUESTIONS, build_facts_state, read_facts_answer as _read_facts_answer

import logging

logger = logging.getLogger("companion")

TTL_S = 6 * 3600
_UNSTABLE = ("competition", "year")
FAILED_RETRY_S = 10 * 60


def _slug(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def entity_key(profile: Profile, entity: dict, day: Optional[date] = None) -> Optional[str]:
    """Stable id for 'this programme today', or None when the entity is not named enough."""
    # A match needs both teams; anything else needs at least one named field.
    if profile.render == "match" and not (_slug(entity.get("home_team")) and _slug(entity.get("away_team"))):
        return None
    if profile.render == "title" and not _slug(entity.get("title")):
        return None
    # competition / year come and go between identify calls; they must not change the key.
    named = [slug for slug in (_slug(entity.get(f)) for f in profile.entity if f not in _UNSTABLE) if slug]
    if not named:
        return None
    return f"{profile.id}/{'_'.join(named)}/{(day or date.today()).isoformat()}"


def build_prompt(profile: Profile, entity: dict) -> str:
    what = ", ".join(f"{k}: {v}" for k, v in entity.items() if v)
    keys = "\n".join(f'  "{k}": {desc}' for k, desc in profile.facts.items())
    return (
        f"Search the web for this {profile.subcategory or profile.category} programme on TV today "
        f"({date.today().isoformat()}): {what}.\n"
        "Answer ONLY with one JSON object with exactly these keys:\n"
        f"{keys}\n"
        '  "sources": list of the URLs of the pages you took these facts from\n'
        "Use null for anything the search results do not state. Do not guess or use memory."
    )


def parse(content: str, profile: Profile) -> Optional[dict]:
    raw = extract_json(content)
    if raw is None:
        return None
    facts = {}
    for key in profile.facts:
        value = raw.get(key)
        if isinstance(value, str) and value.strip().lower() in ("", "null", "none", "unknown", "n/a"):
            value = None
        facts[key] = value
    return facts


def listed_sources(content: str) -> list[dict]:
    """The pages the model says it used (the ``sources`` key): providers drop their own
    citations when the answer must be bare JSON, so the prompt asks for them explicitly."""
    raw = extract_json(content) or {}
    urls = raw.get("sources") if isinstance(raw.get("sources"), list) else []
    return [{"url": u.strip(), "title": ""} for u in urls
            if isinstance(u, str) and u.strip().startswith(("http://", "https://"))]


def _merge_sources(*lists: list) -> list[dict]:
    seen, merged = set(), []
    for source in (s for lst in lists for s in lst or []):
        url = (source or {}).get("url")
        if url and url not in seen:
            seen.add(url)
            merged.append(source)
    return merged


LookupFn = Callable[[str], dict]


def default_lookup(team_id: Optional[str]) -> LookupFn:
    def lookup(prompt: str) -> dict:
        from shared.src.lib.ai import gateway
        return gateway.complete(FACTS, prompt, max_tokens=1500, temperature=None, team_id=team_id)
    return lookup


class FactCache:
    """Per-process cache of looked-up facts, filled by background threads.

    With ``gate`` set (TASK-45 goal 5), each new lookup first asks Jev whether the entity is
    worth a web search (a programme / film / series / match). A skip is cached like ``ready``
    (``TTL_S``) and returns ``{"status": "skipped", "facts": {}, "sources": [], "at"}`` — the
    UI renders nothing. Failures (no answer / ``success`` false / exception) fall through to the
    web lookup: today's path runs.
    """

    def __init__(self, lookup: LookupFn, gate: Optional[Callable[..., dict]] = None):
        self._lookup = lookup
        self._gate = gate
        self._entries: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get(self, key: str, profile: Profile, entity: dict, *, background: bool = True,
            category: Optional[str] = None, subcategory: Optional[str] = None,
            channel: Optional[str] = None, device_id: Optional[str] = None) -> dict:
        """The entry for ``key``; starts a lookup when missing or expired.

        Entry: ``{status: pending|ready|failed|skipped, facts, sources, at}``. ``category``,
        ``subcategory`` and ``channel`` are passed to the Jev gate so it can tell a programme
        from a strap.
        """
        now = time.time()
        with self._lock:
            entry = self._entries.get(key)
            fresh = entry is not None and (
                entry["status"] == "pending"
                or (entry["status"] == "ready" and now - entry["at"] < TTL_S)
                or (entry["status"] == "skipped" and now - entry["at"] < TTL_S)
                or (entry["status"] == "failed" and now - entry["at"] < FAILED_RETRY_S)
            )
            if fresh and entry is not None:
                return dict(entry)
            entry = {"status": "pending", "facts": {}, "sources": [], "at": now}
            self._entries[key] = entry
        if background:
            threading.Thread(target=self._run, args=(key, profile, entity, category, subcategory, channel, device_id),
                             daemon=True,
                             name=f"companion-facts-{key[:40]}").start()
        else:
            self._run(key, profile, entity, category, subcategory, channel, device_id)
        with self._lock:
            return dict(self._entries[key])

    def _gate_check(self, entity: dict, category: Optional[str], subcategory: Optional[str],
                    channel: Optional[str], device_id: Optional[str], key: str) -> bool:
        """Ask Jev whether this entity is worth a web lookup; return True on skip. ``False``
        on any failure / exception (fail open)."""
        try:
            state = build_facts_state(entity, category, subcategory, channel)
            refs = {"source": "companion", "gate": "facts", "device_id": device_id,
                    "programme": (entity or {}).get("title"), "key": key}
            out = self._gate(state, FACTS_QUESTIONS, refs, 5)
            skip = _read_facts_answer(out)
        except Exception as e:
            logger.info(f"[companion] {device_id} facts gate error, falling back to lookup: {e}")
            return False
        if skip:
            logger.info(f"[companion] {device_id} gate facts skipped: not worth a lookup ({key})")
        return skip

    def _run(self, key: str, profile: Profile, entity: dict, category: Optional[str] = None,
             subcategory: Optional[str] = None, channel: Optional[str] = None,
             device_id: Optional[str] = None) -> None:
        # The gate runs here (the background thread), never in the caller's step()/result().
        if self._gate is not None and self._gate_check(entity, category, subcategory, channel, device_id, key):
            with self._lock:
                self._entries[key] = {"status": "skipped", "facts": {}, "sources": [], "at": time.time()}
            return
        try:
            result = self._lookup(build_prompt(profile, entity))
            content = result.get("content") or ""
            facts = parse(content, profile) if result.get("success") else None
            entry = {
                "status": "ready" if facts is not None else "failed",
                "facts": facts or {},
                "sources": _merge_sources(result.get("sources"), listed_sources(content))[:8],
                "error": None if facts is not None else (result.get("error") or "unparseable answer")[:300],
                "at": time.time(),
            }
        except Exception as e:  # never let a lookup kill the monitor
            entry = {"status": "failed", "facts": {}, "sources": [], "error": str(e)[:300], "at": time.time()}
        with self._lock:
            self._entries[key] = entry


def facts_payload(entry: dict) -> dict:
    """What the UI gets: status, facts, and the pages they came from."""
    return {"status": entry["status"], "facts": entry.get("facts") or {},
            "sources": entry.get("sources") or [], **({"error": entry["error"]} if entry.get("error") else {})}
