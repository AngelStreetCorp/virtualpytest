"""Atlas Prepared FAQ (TASK-152 phase 9): in-front-of-the-model answer store.

Atlas answers docs questions in <10 s by reading a curated FAQ entry instead of asking the model to
re-discover the same docs. The module is split into two layers.

- ``faqs`` (this file): pure logic. ``normalize()`` lowercases, NFKC-folds, drops punctuation, and
  collapses whitespace — the canonical dedupe key. ``HotFaqCache(N)`` holds the top-N entries by
  ``count`` in-process; lookups happen there, never blocking on the database.
- ``agent_faq_db`` (``shared/src/lib/database/agent_faq_db.py``): the database I/O. Lazy-loads the
  cache (top-N live), finds a match (canonical + alias), increments the count on a hit, logs every
  question to ``atlas_faq_log``, and upserts a learned answer from a model call that cited a
  ``docs/`` path.

Kill switch: ``ATLAS_FAQ=off`` (default on). Mirrors the ``ATLAS_QUICK_STEP=off`` for the quick step.

Lookup order for one user question (matches the design in
``docs/tasks/TASK-152-atlas-answers-under-10s.md`` § Prepared FAQ):

0. **admission guard** — a live operation or a live-state question is handed to the router
1. **hot cache** — the whole live corpus in-process, exact/normalised/alias in ≤ 5 ms wall clock
2. **(DB tier)** canonical SQL on ``normalised_question``
3. **model** — only on miss. A docs-citing answer is upserted as ``proposed=true``.

Tier 1 has three steps of its own, in this order: the **canonical** question (normalised
equality), then the **exact alias** (normalised equality against a curated alias), then the
**fuzzy alias** (token overlap). The exact-alias step exists because the fuzzy step needs
``ALIAS_MIN_OVERLAP`` shared content tokens, and shared tokens can never exceed the query's own
content-token count: a query with fewer than three content tokens was structurally unreachable,
however often it was asked. On the live corpus that left 33 of 1002 curated aliases dead, all 11
CJK ones among them (the whitespace tokenizer keeps a Chinese phrase as ONE token). Equality needs
no floor.

The alias tiers are part of tier 1: there is no DB-tier alias search, which is why the cache holds
the whole live corpus. An embedding tier (cosine on a vector column) was designed in phase 9b and
refused in phase 9e in favour of the exact-alias lookup above — ``agent_faq`` has no embedding
column and no code reads one. A paraphrase that drops the distinctive words ("is this free or do
i have to pay" for "Is VirtualPyTest free to use?") is still a miss: the lexical tiers cannot
bridge it, and the nightly alias backfill is what closes it, one validated alias at a time.

This module only owns tier 1 and the lookup helpers; tier 2 is in ``agent_faq_db`` because it
hits Postgres.

Every public function fails soft (returns ``None`` / ``[]`` / no-op) — a FAQ problem never breaks an
Atlas turn. The hot cache is a single process-wide instance in ``backend_server/src/agent/`` to
avoid duplicate copies per session.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

# Top-N live entries the in-process cache holds, ranked by count. The doc target is a 5 ms wall
# clock per lookup; the lookup itself is a dict hit, so the cap is a memory knob, not a latency
# knob — measured on the live corpus, a 343-row cache answers in the same 0.01 ms as a 64-row one.
#
# The cap was 64 while the corpus was small. It now covers every live row on purpose: the alias
# tier lives ONLY in this cache (there is no DB-tier alias search), so an alias on a row outside
# the cap is dead weight. With 345 live rows the corpus is fully resident at this size.
HOT_CAP = 512
# How long a loaded cache stays fresh before the agent loop rebuilds it. A persona spawn, a seed
# re-load, or the daily review pass all write new live rows; without this the process would keep
# answering from its boot-time snapshot until the next restart. 10 minutes keeps the rebuild
# well under one FAQ-tier lookup budget and off the hot path of every single question.
CACHE_TTL_S = 600.0
# Maximum length of a normalised question; longer messages get truncated. The cap protects the LRU
# hash keys from getting too wide and the lookup from doing too much string work.
MAX_NORMALISED_LEN = 200

# Alias-tier guards. Phase 9a matched on any single shared token, which answered "Which IR
# standard do you use?" with the IR_PATH-vs-IR_IP entry because both contain the token "ir".
# A match now needs a minimum amount of real overlap, scored over CONTENT words only: the first
# round of guards still let "What is env_backup.py on the host side and what does it do" win
# "Which IR standard do you use, and where is the keymap?" on the shared function words
# is/the/and/do (4 of 11 tokens = 36 %). Function words carry no topical signal.
ALIAS_MIN_QUERY_TOKENS = 2   # a one-word question cannot be resolved by alias alone
ALIAS_MIN_OVERLAP = 3        # at least three shared CONTENT tokens
ALIAS_MIN_SHARE = 0.50       # …and at least half of the query's content tokens
#
# ALIAS_MIN_OVERLAP was 2 until 2026-10-24. Two shared tokens was loose enough to answer a
# non-technical question with the wrong row: on a 100-question set paraphrased into everyday
# wording, 15 of 46 resolved questions landed on a row that was not the one asked about. At 3
# shared tokens that drops to 6 of 29, while the canonical benchmark still resolves 100/100 and
# the technical paraphrases 96/97. A wrong answer is worse than no answer here — a miss falls
# through to the model, which is slow but right.

# Words that carry no topical signal and must not contribute to an alias score.
ALIAS_STOPWORDS = frozenset({
    "a", "an", "the", "of", "for", "to", "in", "on", "is", "are", "was", "be", "been", "do",
    "does", "did", "i", "you", "your", "we", "our", "it", "its", "and", "or", "but", "not",
    "can", "could", "will", "would", "should", "how", "what", "where", "which", "when", "why",
    "who", "whom", "whose", "that", "this", "these", "those", "there", "here", "if", "then",
    "so", "than", "as", "at", "by", "from", "with", "about", "into", "get", "got", "use",
    "used", "using", "make", "made", "does", "any", "all", "some", "no", "yes",
})


# --------------------------------------------------------------------------- admission guard
#
# The FAQ tier runs BEFORE the router and the quick step, and a hit short-circuits the turn: the
# manager returns the FAQ answer and never plans a tool call. So a message that asks for a live
# action must never be answered from the docs store — it would get a static paragraph instead of
# the action it asked for.
#
# Measured on the TASK-163 use-case contract (109 prompts), 38 of them matched a FAQ row with the
# full corpus resident: "Take control of {device}" was answered with "What stops scripts from
# clobbering a manual take-control session?", "Press HOME on {device}" with "What happens if I
# press HOME on an STB?". Every one of those is a live operation that must reach the router.
#
# Two shapes are recognised and handed to the router instead:
#
#   1. a command — a short imperative ("Take control of stb3", "Press HOME on the stb", "List my
#      test cases"). The quick step owns these; the FAQ must not pre-empt it.
#   2. a live-state question about a device or host ("Is stb3 free or in use?", "Who is
#      controlling stb3?", "What is on the screen of stb3?"). The answer depends on the lab right
#      now, so no stored answer can be right.
#
# A documentation question ("Which devices are supported?", "How do I configure a phone slot?")
# still gets its FAQ answer.

# A message opening with one of these is an order, not a question.
COMMAND_VERBS = frozenset({
    "take", "press", "run", "release", "go", "wake", "turn", "screenshot", "capture", "send",
    "open", "close", "execute", "list", "stop", "start", "restart", "reboot", "reset", "navigate",
    "set", "delete", "mute", "volume", "zap", "lock", "unlock", "connect", "disconnect", "control",
    "pair", "unpair", "enable", "disable", "install", "uninstall", "deploy", "copy", "move",
    "search", "find", "show", "display", "put", "quit", "exit", "unlock", "read", "write", "add",
    "remove", "create", "update", "switch", "toggle", "adjust", "increase", "decrease",
})
# Openings that are a request in polite form rather than a question.
COMMAND_OPENINGS = ("i want", "i need", "i'd like", "please ", "can you take", "could you take")
# Words that open a question. A message starting with one of these is not a command.
QUESTION_OPENINGS = frozenset({
    "what", "why", "how", "where", "which", "when", "who", "whom", "whose", "is", "are", "was",
    "were", "do", "does", "did", "can", "could", "will", "would", "should", "may", "might",
    "explain", "tell", "describe", "explain", "any", "am",
})
# A generic noun for a runtime target. Concrete device names (stb3, labox-1) are not listed, but
# a name built on one of these ("stb3", "host1", "cam2") is caught by the substring rule below.
RUNTIME_NOUNS = frozenset({
    "device", "devices", "stb", "stbs", "box", "boxes", "tv", "tvs", "phone", "phones", "host",
    "hosts", "camera", "cameras", "player", "receiver", "hardware", "script", "scripts",
})
# Words that mark the question as being about the state of a target right now.
LIVE_STATE_WORDS = frozenset({
    "free", "busy", "awake", "asleep", "online", "offline", "down", "up", "locked", "unlocked",
    "controlling", "controlled", "screen", "status", "state", "running", "currently", "current",
    "available", "connected", "alive", "reachable", "actions", "ok", "playing", "shown", "run",
    "runs", "pass", "passed", "finish", "finished", "done",
})
# Openings of a live-state question. "how" is deliberately absent: "How do I capture the screen of
# a device?" is a documentation question, not a question about one device right now. "can" is
# absent for the same reason: "Can I run a screen capture test without the device?" asks about
# the absence of a device, which is a documentation question.
#
# "check" is here because "Check which phone_agent are asleep" is a question about the lab right
# now — and the model answers it with a docs paragraph, which is what the learned entry then
# stores. "check" only triggers the rule with a runtime noun AND a live-state word, so
# "Check the leak gate docs" still reaches the FAQ.
LIVE_STATE_OPENINGS = frozenset({
    "is", "are", "was", "who", "what", "which", "does", "do", "did", "check",
})
# The live-state word and the runtime target must sit near the front of the question — that is
# what makes the question about the target right now rather than about how the platform works.
LIVE_STATE_WINDOW = 5
RUNTIME_TARGET_WINDOW = 8
# A command is short. The quick step uses a 12-word bound for its own reasons (the cost of the
# small model call); a command is still a command at 13 words ("Take control of all available stb
# and if not awake wake them up"), so this bound is its own.
MAX_COMMAND_WORDS = 16


def _names_a_runtime_target(token: str) -> bool:
    """True when the token is a runtime target: a runtime noun, or a name built on one.

    Real device names are arbitrary ("stb3", "host1", "cam2"), so the exact nouns alone would
    miss them. A token that CONTAINS a runtime noun of 3+ characters is treated as a target;
    shorter nouns are not, because "tv" is everywhere.
    """
    if token in RUNTIME_NOUNS:
        return True
    if len(token) >= 4:
        return any(len(noun) >= 3 and noun in token for noun in RUNTIME_NOUNS)
    return False


def should_decline(message: str) -> bool:
    """True when the FAQ tier must not answer this message — the router owns it.

    Either a live operation ("Take control of stb3") or a live-state question about a device
    ("Is stb3 free or in use?"). A miss and a hand-back reach the same place downstream, so this
    only matters where a hit would be WRONG: the FAQ answers from the docs store, and a live
    action or a live state has no stored answer.
    """
    return is_device_operation(message)


def _live_state_pair(words: List[str]) -> bool:
    """True when a live-state word and a runtime target sit near the front of the question.

    Both must be close to the front, because that is what makes the question about the target
    RIGHT NOW: "is stb3 free or in use", "who is controlling stb3", "what is the status of stb3",
    "check which phone_agent are asleep".

    Without the window, documentation questions that merely mention a device or a script get
    caught too: "what are the host-side API endpoints for controlling a paired phone" (the word
    "host" in "host-side"), "what does the collect_host_load.sh script capture and how long should
    I run it" (the word "run" is 12 tokens in), "what blocks are available for custom pages" (the
    device is mentioned at the end).
    """
    state_idx = next((i for i, w in enumerate(words) if w in LIVE_STATE_WORDS), None)
    if state_idx is None or state_idx > LIVE_STATE_WINDOW:
        return False
    return any(
        _names_a_runtime_target(w)
        for w in words[: RUNTIME_TARGET_WINDOW]
    )


def is_device_operation(message: str) -> bool:
    """True when the message asks for a live action or the live state of a device/host.

    The caller (the FAQ step) then leaves the turn to the router instead of answering it from the
    docs store. Never raises; an empty or odd message is not an operation.
    """
    if not message:
        return False
    normalised = normalize(message)
    if not normalised:
        return False
    words = normalised.split()
    tokens = set(words)
    lowered = normalised + " "

    # 2. a live-state question about a device or host
    if (
        words[0] in LIVE_STATE_OPENINGS
        and _live_state_pair(words)
    ):
        return True

    # 1. a short imperative command
    if len(words) > MAX_COMMAND_WORDS:
        return False
    if "?" in message:
        return False
    if words[0] in QUESTION_OPENINGS:
        return False
    if words[0] in COMMAND_VERBS or lowered.startswith(COMMAND_OPENINGS):
        return True
    return False


# Match sources reported to atlas_faq_log.match_source (the SQL CHECK constraint lists the same set).
SOURCE_HOT = "hot_cache"
SOURCE_EXACT = "faq_exact"
SOURCE_NORMALISED = "faq_normalised"
SOURCE_ALIAS = "faq_alias"
SOURCE_PROPOSED = "proposed_promote"
SOURCE_NONE = "none"


# --------------------------------------------------------------------------- normalisation

_DROP = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS = re.compile(r"\s+", flags=re.UNICODE)


def enabled() -> bool:
    """``ATLAS_FAQ=off`` switches the Prepared FAQ off; default on."""
    return os.getenv("ATLAS_FAQ", "on").strip().lower() != "off"


def normalize(text: str) -> str:
    """Lowercase, NFKC-fold, drop non-word non-space characters, collapse whitespace. Truncate."""
    if not text:
        return ""
    nfkc = unicodedata.normalize("NFKC", text).lower()
    no_punct = _DROP.sub(" ", nfkc)
    no_ws = _WS.sub(" ", no_punct).strip()
    return no_ws[:MAX_NORMALISED_LEN]


def alias_tokens(normalised: str) -> Set[str]:
    """Content tokens of a normalised question, for alias scoring.

    Function words are dropped: they are shared by nearly every question in the table and
    contribute overlap without carrying any topical signal.
    """
    if not normalised:
        return set()
    return {t for t in normalised.split(" ") if t and t not in ALIAS_STOPWORDS}


# --------------------------------------------------------------------------- HotFaqCache

@dataclass(frozen=True)
class FaqEntry:
    """One row the hot cache holds. Read-only on purpose — the cache rebuilds, it doesn't mutate."""

    id: str
    question_text: str
    normalised: str
    aliases: tuple[str, ...]
    short: str
    long: str
    sources: tuple[str, ...]
    tags: tuple[str, ...]
    count: int

    @classmethod
    def from_row(cls, row: Dict) -> "FaqEntry":
        return cls(
            id=str(row.get("id")),
            question_text=str(row.get("question_text") or ""),
            normalised=str(row.get("normalised_question") or ""),
            aliases=tuple(row.get("aliases") or ()),
            short=str(row.get("short") or ""),
            long=str(row.get("long") or ""),
            sources=tuple(row.get("sources") or ()),
            tags=tuple(row.get("tags") or ()),
            count=int(row.get("count") or 0),
        )


@dataclass(frozen=True)
class FaqHit:
    """One match returned by ``HotFaqCache.lookup`` — enough to answer the turn without a model call."""

    entry: FaqEntry
    source: str
    score: float                       # 1.0 = exact, < 1.0 = alias-token overlap


class HotFaqCache:
    """Top-N FAQ entries by ``count``, kept in-process for sub-5 ms lookups.

    Empty until ``load(entries)`` is called. ``load_reload_later`` schedules a refresh in the
    background (the doc + DB pushes change the ranking; the daily review flips proposed → live).
    Thread-safe so the agent loop and the background reload do not race on the dict.
    """

    def __init__(self, capacity: int = HOT_CAP):
        self._cap = max(1, int(capacity))
        self._by_norm: Dict[str, FaqEntry] = {}
        self._by_alias_norm: Dict[str, FaqEntry] = {}   # normalised alias → its entry
        self._by_aliases: Dict[str, List[FaqEntry]] = {}      # token → entries that have it
        self._entries: List[FaqEntry] = []
        self._lock = threading.Lock()
        self._last_loaded_at: float = 0.0

    # mutation --------------------------------------------------------------

    def load(self, rows: Iterable[Dict]) -> int:
        """Replace the cache with the rows from the DB (top-N by ``count``). Idempotent."""
        sorted_rows = sorted(
            (r for r in rows if r),
            key=lambda r: (-int(r.get("count") or 0), str(r.get("last_asked_at") or "")),
        )[: self._cap]
        entries: List[FaqEntry] = []
        by_norm: Dict[str, FaqEntry] = {}
        by_aliases: Dict[str, List[FaqEntry]] = {}
        by_alias_norm: Dict[str, FaqEntry] = {}
        for row in sorted_rows:
            entry = FaqEntry.from_row(row)
            entries.append(entry)
            n = entry.normalised
            if n and n not in by_norm:
                by_norm[n] = entry
            tokens = alias_tokens(n)
            for alias in entry.aliases:
                an = normalize(alias)
                tokens |= alias_tokens(an)
                # An alias that IS a canonical question must not shadow it: the canonical lookup
                # runs first, so the question keeps its own row.
                if an and an not in by_norm and an not in by_alias_norm:
                    by_alias_norm[an] = entry
            for token in tokens:
                by_aliases.setdefault(token, []).append(entry)
        with self._lock:
            self._entries = entries
            self._by_norm = by_norm
            self._by_aliases = by_aliases
            self._by_alias_norm = by_alias_norm
            self._last_loaded_at = time.time()
        return len(entries)

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def last_loaded_at(self) -> float:
        return self._last_loaded_at

    def kv(self) -> List[FaqEntry]:
        """Snapshot of the current top-N — tests + introspection."""
        with self._lock:
            return list(self._entries)

    # lookup -----------------------------------------------------------------

    def lookup(self, query: str) -> Optional[FaqHit]:
        """hot cache → ``None`` on miss. Never reads the database."""
        if not query:
            return None
        normalised = normalize(query)
        if not normalised:
            return None
        tokens = alias_tokens(normalised)
        with self._lock:
            entry = self._by_norm.get(normalised)
            if entry:
                return FaqHit(entry=entry, source=SOURCE_HOT, score=1.0)
            # Exact alias: the curated alias equals the question. This sits BEFORE the fuzzy
            # overlap path on purpose — the fuzzy tier needs ALIAS_MIN_OVERLAP shared content
            # tokens, so a short alias (or a CJK phrase, which the whitespace tokenizer keeps
            # as ONE token) can never clear the floor and stays unreachable however often it is
            # asked. Equality needs no floor. Canonical still wins: ``load`` never puts an
            # alias that collides with a canonical question into this map.
            exact = self._by_alias_norm.get(normalised)
            if exact:
                return FaqHit(entry=exact, source=SOURCE_HOT, score=1.0)
            if len(tokens) >= ALIAS_MIN_QUERY_TOKENS:
                hits: Dict[str, int] = {}
                for token in tokens:
                    candidates = self._by_aliases.get(token) or ()
                    for candidate in candidates:
                        hits[candidate.id] = hits.get(candidate.id, 0) + 1
                # An alias match needs real evidence: at least ALIAS_MIN_OVERLAP shared tokens
                # AND at least ALIAS_MIN_SHARE of the query's tokens. A single shared token is
                # not enough — "Which IR standard do you use?" and "What's the difference
                # between IR_PATH and IR_IP?" both contain "ir" but are different questions,
                # and the old tier answered the latter for the former.
                best_id, best_hits = None, 0
                for candidate_id, shared in hits.items():
                    if shared > best_hits:
                        best_id, best_hits = candidate_id, shared
                if best_id is not None and best_hits >= ALIAS_MIN_OVERLAP:
                    share = best_hits / max(1, len(tokens))
                    if share >= ALIAS_MIN_SHARE:
                        for entry in self._entries:
                            if entry.id == best_id:
                                return FaqHit(entry=entry, source=SOURCE_HOT, score=share)
        return None

    def is_stale(self, ttl_s: float) -> bool:
        """True when the cache has never been loaded, or was loaded longer than ``ttl_s`` ago."""
        with self._lock:
            if not self._entries:
                return True
            return (time.time() - self._last_loaded_at) > ttl_s


# --------------------------------------------------------------------------- process-wide singleton

_cache: Optional[HotFaqCache] = None
_cache_lock = threading.Lock()


def cache() -> HotFaqCache:
    """One cache per process. The agent loop and the load script go through this."""
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                _cache = HotFaqCache(HOT_CAP)
    return _cache


def reload(rows: Iterable[Dict]) -> int:
    """Replace the cache contents. Used by the loader script and the daily review pass."""
    return cache().load(rows)


def maybe_refresh(ttl_s: float = CACHE_TTL_S, loader=None) -> bool:
    """Rebuild the cache when it has gone stale. Returns True when a reload happened.

    Phase 9a loaded the hot cache once per process and then served that snapshot forever, so a
    row promoted after boot (by the daily review pass, by a persona spawn, or by another
    server) never reached tier 1 until the next restart. This is the rebuild hook the agent
    loop calls; ``loader`` defaults to ``agent_faq_db.load_hot`` and is injectable for tests.
    """
    c = cache()
    if not c.is_stale(ttl_s):
        return False
    if loader is None:
        try:
            from shared.src.lib.database import agent_faq_db  # local import: avoids a cycle
            loader = lambda: agent_faq_db.load_hot(HOT_CAP)  # noqa: E731
        except Exception as exc:  # noqa: BLE001 - never break a turn on a refresh
            logger.warning("faq hot-cache refresh: loader unavailable (%s)", exc)
            return False
    try:
        rows = loader()
    except Exception as exc:  # noqa: BLE001
        logger.warning("faq hot-cache refresh failed: %s", exc)
        return False
    if rows is None:
        return False
    c.load(rows)
    # print, not logger.info: the agent's stdout is what reaches the journal, and an operator
    # watching the [FAQ] lines needs to see the rebuild happen, not just infer it.
    print(f"[FAQ] hot cache refreshed: {c.size()} entries")
    return True
