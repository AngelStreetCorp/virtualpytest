"""Prepared FAQ for the anonymous website widget (POST /server/public/ask).

Same store and same normalisation as Atlas (``agent_faq`` + ``faqs.normalize`` + ``faqs.HotFaqCache``),
read through the ``public`` flag: only rows with ``public = TRUE`` are ever served to a visitor. The flag
is FALSE by default, so an Atlas entry (hosts, env blocks, internal runbooks) never leaks; the docs-only
entries are flagged by ``scripts/agent/faq_load_public.py``.

Matching is stricter than Atlas' token overlap, because a wrong cached answer on a public page is worse
than a slow right one: a question matches an entry when its content words (stop words dropped, light
stemming, accents folded) equal those of the entry question or one of its aliases, or overlap them with a
Jaccard of at least ``MIN_SCORE``. "how is fixnet working" and "how does Fixnet work?" both reduce to
``{fixnet, work}``. French and English are separate rows (the question text differs), so the same code
serves both widget languages.

Every function fails soft: a FAQ problem sends the question to the model, never to a 500.
"""

from __future__ import annotations

import hashlib
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Tuple

from pathlib import Path

from shared.src.lib.database import agent_faq_db

from . import faqs

# Entries held in memory; the public set is a few hundred rows at most.
CAPACITY = 1000
# A reload is cheap (one SELECT); stale entries (new seed, flipped flag) show up within this window.
RELOAD_SECONDS = 600
MIN_SCORE = 0.7
SOURCE_PUBLIC = "public_faq"
# Learned (model-written) answers are looser than curated ones: they only match a near-identical re-ask.
LEARNED_MIN_SCORE = 0.85
MAX_LEARNED_CHARS = 2000

_STOP = frozenset("""
a an the is are was were be been being do does did done can could should would will shall may might must
of for to in on at by with from into about as it its this that these those there here
how what which who whom whose why when where whats hows
i you he she we they me my your our their us them
please pls hi hello hey thanks thank
and or but if then so than too very just also
tell explain describe show give me know want need like get got
le la les un une des du de d l et ou mais si donc que qui quoi quel quelle quels quelles dont ou
est sont etait etre ete avoir a ont fait faire font peut peuvent
ce cet cette ces il elle ils elles on nous vous je tu me te se lui leur leurs mon ma mes ton ta tes son sa ses notre votre
dans sur sous avec sans pour par en au aux chez entre vers
comment pourquoi quand combien quoi
svp bonjour salut merci
""".split())

_BRAND = "virtualpytest"
_SUFFIXES = ("ing", "ed", "es", "s", "x")


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _stem(word: str) -> str:
    """Light stemmer: plural / -ing / -ed and a final e fold together (devices, device -> devic)."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    return word[:-1] if word.endswith("e") and len(word) > 3 else word


def token_list(text: str) -> List[str]:
    """Stemmed content words in order, repeats kept (the doc retrieval counts them)."""
    return [_stem(w) for w in _fold(faqs.normalize(text)).split(" ") if len(w) >= 2 and w not in _STOP]


def content_tokens(text: str) -> FrozenSet[str]:
    """Stemmed content words of a question; the unit both the FAQ match and the doc retrieval compare."""
    tokens = set(token_list(text))
    # The brand is in half the questions and says nothing about which one; it only counts when alone.
    return frozenset(tokens - {_BRAND} if len(tokens) > 1 else tokens)


def _docs_root() -> Path:
    return Path(__file__).resolve().parents[3] / "docs"


def manifest_hash(sources: List[str]) -> str:
    """Hash of the cited doc files' content: a learned answer is stale the moment one of them changes."""
    digest = hashlib.sha256()
    for src in sorted(sources):
        try:
            digest.update((_docs_root() / src).read_bytes())
        except OSError:
            digest.update(b"missing:" + src.encode())
    return digest.hexdigest()[:16]


@dataclass(frozen=True)
class PublicFaqHit:
    entry: faqs.FaqEntry
    score: float
    matched: str          # the question or alias that matched, for the log

    @property
    def answer(self) -> str:
        return (self.entry.long or self.entry.short).strip()

    @property
    def sources(self) -> List[str]:
        return list(self.entry.sources)


def _tag(entry: faqs.FaqEntry, prefix: str) -> str:
    return next((t[len(prefix):] for t in entry.tags if t.startswith(prefix)), "")


class _Index:
    """Entries plus the token set of each of their question forms. Replaced whole on reload."""

    def __init__(self, rows: List[Dict]):
        cache = faqs.HotFaqCache(CAPACITY)
        cache.load(rows)
        self.hashes: Dict[str, str] = {str(r.get("id")): r.get("doc_manifest_hash") or "" for r in rows}
        self.forms: List[Tuple[FrozenSet[str], str, faqs.FaqEntry]] = []
        for entry in cache.kv():
            for text in (entry.question_text, *entry.aliases):
                tokens = content_tokens(text)
                if tokens:
                    self.forms.append((tokens, text, entry))
        self.size = len(cache.kv())
        # (group, language) -> entry: the same answer in the visitor's language when it exists.
        self.by_group: Dict[Tuple[str, str], faqs.FaqEntry] = {}
        for entry in cache.kv():
            group, lang = _tag(entry, "group:"), _tag(entry, "lang:")
            if group and lang:
                self.by_group[(group, lang)] = entry

    def add(self, row: Dict) -> None:
        """Make a just-learned answer matchable at once, without waiting for the next reload."""
        entry = faqs.FaqEntry.from_row(row)
        self.hashes[entry.id] = row.get("doc_manifest_hash") or ""
        tokens = content_tokens(entry.question_text)
        if tokens:
            self.forms = [f for f in self.forms if f[2].id != entry.id] + [(tokens, entry.question_text, entry)]
        self.size += 1

    def fresh(self, entry: faqs.FaqEntry) -> bool:
        """Curated entries are always fresh; a learned one only while its cited docs are unchanged."""
        return "learned" not in entry.tags or self.hashes.get(entry.id) == manifest_hash(list(entry.sources))

    def best(self, query: FrozenSet[str]) -> Optional[Tuple[float, str, faqs.FaqEntry]]:
        best: Optional[Tuple[float, str, faqs.FaqEntry]] = None
        for tokens, text, entry in self.forms:
            union = len(query | tokens)
            score = len(query & tokens) / union if union else 0.0
            learned = "learned" in entry.tags
            if score < (LEARNED_MIN_SCORE if learned else MIN_SCORE) or (learned and not self.fresh(entry)):
                continue
            if best is None or score > best[0]:
                best = (score, text, entry)
        return best


_index: Optional[_Index] = None
_loaded_at = 0.0
_lock = threading.Lock()


def _ensure_loaded() -> Optional[_Index]:
    global _index, _loaded_at
    if _index is not None and time.time() - _loaded_at < RELOAD_SECONDS:
        return _index
    with _lock:
        if _index is not None and time.time() - _loaded_at < RELOAD_SECONDS:
            return _index
        rows = agent_faq_db.load_public(CAPACITY)
        if rows or _index is None:
            _index = _Index(rows)
        # Failed or empty reload keeps the previous index; retry after the window either way.
        _loaded_at = time.time()
        return _index


def entry_count() -> int:
    """Public entries currently loaded (admin stats)."""
    return _index.size if _index is not None else 0


def reset() -> None:
    """Drop the loaded index (tests, and a loader that just flagged new rows)."""
    global _index, _loaded_at
    with _lock:
        _index, _loaded_at = None, 0.0


def lookup(question: str, language: str = "") -> Optional[PublicFaqHit]:
    """Prepared answer for a visitor question, or ``None`` (the model takes over).

    ``language`` is the widget locale (``fr``, ``zh-CN``...). When the matched entry has a sibling in that
    language (same ``group:`` tag) the sibling answers; otherwise the matched entry does.
    """
    if not faqs.enabled() or not question:
        return None
    try:
        index = _ensure_loaded()
        query = content_tokens(question)
        if index is None or not query:
            return None
        found = index.best(query)
    except Exception as exc:  # noqa: BLE001 - never break a visitor question
        print(f"[@public_ask] FAQ lookup skipped: {exc}")
        return None
    if found is None:
        return None
    entry = found[2]
    wanted = (language or "").split("-")[0].lower()
    group = _tag(entry, "group:")
    if wanted and group and _tag(entry, "lang:") != wanted:
        entry = index.by_group.get((group, wanted), entry)
    return PublicFaqHit(entry=entry, score=found[0], matched=found[1])


def bump(hit: PublicFaqHit) -> None:
    """Count the hit on the entry (drives the ranking Atlas and the review use). Background, fail soft."""
    threading.Thread(target=agent_faq_db.increment_count, args=(hit.entry.id,), daemon=True).start()


def learn(question: str, answer: str, sources: List[str]) -> None:
    """Store a model answer (that cited docs) as a learned public entry. Background, fail soft.

    The next ask of the same question is then a FAQ hit in this process at once and in every other process
    and after every deploy from the database, until a cited doc changes.
    """
    if not faqs.enabled() or not answer or not sources or len(answer) > MAX_LEARNED_CHARS:
        return
    normalised = faqs.normalize(question)
    if not normalised or not content_tokens(question):
        return

    def work() -> None:
        digest = manifest_hash(sources)
        faq_id = agent_faq_db.upsert_learned_public(question_text=question.strip(), normalised=normalised,
                                                    answer=answer, sources=sources, manifest_hash=digest)
        if faq_id and _index is not None:
            _index.add({"id": faq_id, "question_text": question.strip(), "normalised_question": normalised,
                        "aliases": [], "short": answer[:280], "long": answer, "sources": sources,
                        "tags": ["public", "learned"], "count": 1, "doc_manifest_hash": digest})

    threading.Thread(target=work, daemon=True).start()
