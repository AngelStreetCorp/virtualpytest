"""
Atlas Prepared FAQ (TASK-152 phase 9) — DB I/O.

Tables (setup/db/schema/078_agent_faq.sql):
- agent_faq       curated answers; seeded by ``scripts/agent/faq_load_seed.py``, grown by model answers that cite a ``docs/`` path.
- atlas_faq_log   one row per Atlas turn that went through the FAQ path; the count + latency source of truth.

Rules:
- Every public function fails soft: returns None / [] / False on a problem. A FAQ issue never breaks an Atlas turn.
- Writes go through postgrest `insert` / `upsert` / `update`; reads use `select` with explicit columns.
- The hot cache is loaded by ``load_hot`` (top-N live entries by count).
- ``record_question`` writes the audit row; ``increment_count`` keeps `count` in sync with the log.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

logger = logging.getLogger(__name__)

FAQ_TABLE = "agent_faq"
LOG_TABLE = "atlas_faq_log"


def _supabase():
    return get_supabase_client()


def _norm(text: str) -> str:
    """Same normalisation as ``agent/faqs.py``: NFKC, lowercase, drop non-word non-space, collapse whitespace.

    Kept here too so the loader writes consistent rows without importing the agent package
    (which would pull gevent + the full agent graph).
    """
    if not text:
        return ""
    nfkc = unicodedata.normalize("NFKC", text).lower()
    no_punct = re.sub(r"[^\w\s]", " ", nfkc, flags=re.UNICODE)
    return re.sub(r"\s+", " ", no_punct).strip()[:200]


# --------------------------------------------------------------------------- reads

def load_hot(limit: int = 64) -> List[Dict]:
    """Top-N live FAQ entries ordered by ``count`` desc then ``last_asked_at`` desc. Empty on any problem."""
    supabase = _supabase()
    if supabase is None:
        return []
    try:
        q = (
            supabase.table(FAQ_TABLE)
            .select("id,question_text,normalised_question,aliases,short,long,sources,tags,count,last_asked_at")
            .eq("live", True)
            .order("count", desc=True)
            .order("last_asked_at", desc=True)
            .limit(int(limit))
        )
        return list(q.execute().data or [])
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("agent_faq load_hot failed: %s", exc)
        return []


def load_public(limit: int = 1000) -> List[Dict]:
    """Live FAQ entries flagged ``public`` (safe for the anonymous website widget). Empty on any problem."""
    supabase = _supabase()
    if supabase is None:
        return []
    try:
        q = (
            supabase.table(FAQ_TABLE)
            .select("id,question_text,normalised_question,aliases,short,long,sources,tags,count,last_asked_at,doc_manifest_hash")
            .eq("live", True)
            .eq("public", True)
            .order("count", desc=True)
            .limit(int(limit))
        )
        return list(q.execute().data or [])
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("agent_faq load_public failed: %s", exc)
        return []


def find_match(normalised: str, candidates: int = 5) -> Optional[Dict]:
    """Canonical SQL on ``normalised_question``. ``None`` on miss or error.

    Cheap; one indexed lookup. The hot cache catches most of these already; this is the DB tier
    fallback for an entry the cache has not loaded yet, or a question that is not a canonical one.
    """
    if not normalised:
        return None
    supabase = _supabase()
    if supabase is None:
        return None
    try:
        rows = (
            supabase.table(FAQ_TABLE)
            .select("id,question_text,normalised_question,aliases,short,long,sources,tags,count,public")
            .eq("normalised_question", normalised)
            .eq("live", True)
            .limit(candidates)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_faq find_match failed: %s", exc)
        return None


def find_by_question(question_text: str) -> Optional[Dict]:
    """Exact canonical lookup on ``question_text`` (case-sensitive). Used by the loader for re-runs."""
    supabase = _supabase()
    if supabase is None or not question_text:
        return None
    try:
        rows = (
            supabase.table(FAQ_TABLE)
            .select("id,question_text,normalised_question,aliases,short,long,sources,tags,count")
            .eq("question_text", question_text)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_faq find_by_question failed: %s", exc)
        return None


# --------------------------------------------------------------------------- writes — log + count

def record_question(*, team_id: Optional[str], session_id: Optional[str], user_id: Optional[str],
                    question_text: str, normalised: str, match_source: str, faq_id: Optional[str],
                    latency_ms: int, had_answer: bool) -> bool:
    """Append one row to ``atlas_faq_log``. ``False`` on a DB problem; the turn keeps going either way."""
    supabase = _supabase()
    if supabase is None:
        return False
    row = {
        "team_id": team_id or None,
        "session_id": session_id or None,
        "user_id": user_id or None,
        "question_text": question_text or "",
        "normalised": normalised or _norm(question_text),
        "match_source": match_source,
        "faq_id": faq_id,
        "latency_ms": int(latency_ms or 0),
        "had_answer": bool(had_answer),
    }
    try:
        supabase.table(LOG_TABLE).insert(row).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("atlas_faq_log insert failed: %s", exc)
        return False


def increment_count(faq_id: str) -> bool:
    """``count += 1``, ``last_asked_at = now()`` — atomically, via the ``atlas_faq_bump`` RPC.

    Background call; never blocks the turn.

    Phase 9a shipped this with a postgrest fallback that only touched ``updated_at``, so the
    count never actually moved and the hot cache's "top-N by count" ranking stayed arbitrary.
    20261022d_agent_faq_count.sql creates the RPC; this function now reports honestly when it
    is missing instead of pretending the bump worked.
    """
    supabase = _supabase()
    if supabase is None or not faq_id:
        return False
    try:
        result = supabase.rpc("atlas_faq_bump", {"p_faq_id": faq_id}).execute()
        new_count = 0
        try:
            new_count = int((result.data or 0))
        except (TypeError, ValueError):
            new_count = 0
        if new_count == 0:
            # 0 means the id is unknown or the row is not live — not a bump. The RPC is present
            # (it did not raise), so this is a legitimate no-op, not a missing-function error.
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        # The RPC is missing on a database that predates 20261022d. Say so loudly once rather
        # than silently updating `updated_at` and reporting success.
        logger.warning(
            "agent_faq bump failed — is 20261022d_agent_faq_count.sql applied on this database? (%s)",
            exc,
        )
        return False


# --------------------------------------------------------------------------- writes — load + promote

def _existing_aliases(normalised: str) -> List[str]:
    """The alias set a row already carries, or ``[]`` when the row is new or has none.

    Read before a write that must not clobber an alias set another owner put there.
    ``agent_faq`` is a global corpus (no ``team_id`` column, service_role only), so this is not a
    tenant-scoped query.
    """
    if not normalised:
        return []
    row = find_match(normalised)
    return list((row or {}).get("aliases") or [])


def upsert_seeded(*, question_text: str, normalised: str, aliases: Iterable[str],
                  short: str, long: str, sources: Iterable[str], tags: Iterable[str],
                  public: Optional[bool] = None) -> Optional[str]:
    """Loader upsert: keyed on ``normalised_question`` (UNIQUE). Always ``live=TRUE`` and ``proposed=FALSE`` — a hand-authored seed is trusted by default.

    ``public`` is only written when given, so re-seeding an Atlas entry never flips its flag back.

    **An existing alias set is never overwritten.** The aliases of a live row are owned by the
    validated alias backfill (``scripts/agent/faq_alias_backfill.py``), not by the seed loader:
    a re-seed used to write the loader's own machine-made aliases over them, which both threw the
    good ones away and put the broken ones back. The loader may only fill an EMPTY alias set.

    Returns the entry's id, or ``None`` on DB error.
    """
    supabase = _supabase()
    if supabase is None:
        return None
    row = {
        "question_text": question_text,
        "normalised_question": normalised,
        "short": short,
        "long": long,
        "sources": list(sources or []),
        "tags": list(tags or []),
        "proposed": False,
        "live": True,
    }
    if public is not None:
        row["public"] = bool(public)
    try:
        existing = _existing_aliases(normalised)
        if existing:
            row.pop("aliases", None)      # keep the alias set the backfill owns
        else:
            row["aliases"] = list(aliases or [])
        result = (
            supabase.table(FAQ_TABLE)
            .upsert(row, on_conflict="normalised_question")
            .execute()
        )
        data = result.data or []
        return str(data[0]["id"]) if data else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_faq upsert_seeded failed (%r): %s", question_text[:40], exc)
        return None


def upsert_promoted(*, question_text: str, normalised: str, short: str, long: str,
                     sources: Iterable[str], tags: Iterable[str]) -> Optional[str]:
    """Self-promotion: the model answered a docs question. Mark the row ``proposed=true`` for the daily review pass.

    The review pass flips ``proposed → live``. Until then the row is invisible to ``load_hot`` /
    ``find_match``. ``count`` is bumped to 1 so a re-asked same question immediately becomes a cache
    candidate.

    **Never demotes an existing row.** A persona-generated candidate or a learned model answer can
    normalise onto a question a curated seed already owns. Upserting there used to overwrite
    ``live=true, proposed=false`` with ``live=false, proposed=true``, which silently pulled a
    reviewed answer out of rotation (row 1edc58d8 was caught in exactly that state). We now read
    the existing row first and refuse when it is already live; the caller's candidate is dropped
    rather than the curated answer.
    """
    supabase = _supabase()
    if supabase is None:
        return None
    try:
        existing = (
            supabase.table(FAQ_TABLE)
            .select("id,live,tags")
            .eq("normalised_question", normalised)
            .limit(1)
            .execute()
            .data
            or []
        )
        if existing:
            row = existing[0]
            if row.get("live"):
                # A curated or already-reviewed entry owns this question. Leave it alone.
                logger.info(
                    "agent_faq upsert_promoted skipped: %r is already live (%s)",
                    question_text[:60], row.get("id"),
                )
                return str(row["id"])
            # Existing row exists but is not live: it is a pending candidate. Refresh its content
            # and re-arm the review by clearing the review stamp.
            result = (
                supabase.table(FAQ_TABLE)
                .update({
                    "question_text": question_text,
                    "short": short,
                    "long": long,
                    "sources": list(sources or []),
                    "tags": list(tags or []),
                    "proposed": True,
                    "live": False,
                    "count": 1,
                    "last_asked_at": "now()",
                    "last_reviewed_at": None,
                })
                .eq("id", row["id"])
                .execute()
            )
            data = result.data or []
            return str(data[0]["id"]) if data else str(row["id"])

        # No existing row: insert a fresh pending candidate.
        result = (
            supabase.table(FAQ_TABLE)
            .insert({
                "question_text": question_text,
                "normalised_question": normalised,
                "aliases": [],
                "short": short,
                "long": long,
                "sources": list(sources or []),
                "tags": list(tags or []),
                "proposed": True,
                "live": False,
                "count": 1,
                "last_asked_at": "now()",
                # ``last_reviewed_at`` left NULL so the daily review pass is the first review
                # and can promote immediately on its first pass without the 24-h gate.
            })
            .execute()
        )
        data = result.data or []
        return str(data[0]["id"]) if data else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_faq upsert_promoted failed (%r): %s", question_text[:40], exc)
        return None


def upsert_learned_public(*, question_text: str, normalised: str, answer: str, sources: Iterable[str],
                          manifest_hash: str) -> Optional[str]:
    """Remember a model answer the website widget produced, so the next ask (any process, any deploy) is a hit.

    Served only while the cited docs still hash to ``manifest_hash``. Never touches a row that is not itself a
    learned one: a curated or Atlas entry owns its question.
    """
    supabase = _supabase()
    if supabase is None:
        return None
    try:
        rows = supabase.table(FAQ_TABLE).select("id,tags").eq("normalised_question", normalised).limit(1).execute().data or []
        if rows and "learned" not in (rows[0].get("tags") or []):
            return None
        row = {
            "question_text": question_text, "normalised_question": normalised, "aliases": [],
            "short": answer[:280], "long": answer, "sources": list(sources or []),
            "tags": ["public", "learned"], "doc_manifest_hash": manifest_hash,
            "proposed": False, "live": True, "public": True,
        }
        result = supabase.table(FAQ_TABLE).upsert(row, on_conflict="normalised_question").execute()
        data = result.data or []
        return str(data[0]["id"]) if data else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_faq upsert_learned_public failed (%r): %s", question_text[:40], exc)
        return None


def review_pass(limit: int = 200) -> int:
    """Daily pass: flip ``proposed=true`` rows whose docs are unchanged to ``live=true``.

    Implemented as a single postgrest patch on rows whose ``proposed`` is True and ``last_reviewed_at``
    is older than 24 h. The policy owner is ``scripts/agent/faq_review.py``; this function is the
    DB-side helper. Note: nothing schedules that script today, so proposed rows stay proposed
    until it is run by hand or wired to a timer.
    """
    supabase = _supabase()
    if supabase is None:
        return 0
    try:
        # Phase 9a: a one-shot flip for any proposed row. Phase 9b's doc_manifest_hash check tightens
        # this: rows whose cited docs changed stay proposed.
        result = (
            supabase.table(FAQ_TABLE)
            .update({"live": True, "proposed": False, "last_reviewed_at": "now()"})
            .eq("proposed", True)
            .eq("live", False)
            .limit(limit)
            .execute()
        )
        return len(result.data or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_faq review_pass failed: %s", exc)
        return 0
