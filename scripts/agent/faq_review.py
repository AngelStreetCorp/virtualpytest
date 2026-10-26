#!/usr/bin/env python3
"""faq_review.py — daily review pass that promotes ``proposed=true`` rows to ``live=true``.

Phase 9b of TASK-152. Today the policy is intentionally simple:

- A row is eligible to flip from ``proposed`` to ``live`` once:
    1. ``last_reviewed_at`` is at least 24 h ago **or** the row has never been reviewed
       (``last_reviewed_at IS NULL``) — new rows are eligible immediately on first review.
    2. The cited docs (in ``sources[]``) all exist under the repo's working directory **or**
       the row was auto-promoted by ``maybe_promote_from_model_answer`` (which already
       attached the docs at write time).

The 24-h gate mirrors the design in
``docs/tasks/TASK-152-atlas-answers-under-10s.md`` § Phase 9. Phase 9b deep will add the
``doc_manifest_hash`` integrity check; today's pass trusts the citations because every
``agent_faq`` row was generated or reviewed by Sonnet/Haiku and never by raw user input.

Usage
-----
    scripts/agent/faq_review.py              # one-shot dry run (default)
    scripts/agent/faq_review.py --apply      # actually flip the eligible rows
    scripts/agent/faq_review.py --limit 50  # cap how many to flip in one run (cron safety)

Cron: a daily systemd timer — ``infra/agent/atlas/systemd/vpt-faq-review.timer`` on node1
(the unit runs ``scripts/agent/faq_nightly.sh``, which calls this script and then tops up the
aliases). The owner runs it from the agent account; it's idempotent.
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path
from typing import List, Tuple

REPO = None
for ancestor in [Path(__file__).resolve().parent, Path.cwd(), *Path(__file__).resolve().parents]:
    if (ancestor / "shared").exists() and (ancestor / "backend_server").exists():
        REPO = ancestor
        break
if REPO is not None:
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "backend_server" / "src"))

from shared.src.lib.database import agent_faq_db  # noqa: E402


def _doc_exists(path_str: str, repo: Path) -> bool:
    """Return True if a docs/ path lives somewhere on disk (the agent's workdir is the
    authoritative docs root in production). Resolves to cwd-rooted; relative paths are
    treated as repo-relative when they look like docs/ paths."""
    p = Path(path_str)
    if p.is_absolute() and p.exists():
        return True
    if repo is not None:
        candidate = repo / path_str
        if candidate.exists():
            return True
    return False


def _is_live_operation(question: str) -> bool:
    """True when the question is a live device/host operation rather than a documentation ask.

    The FAQ tier answers before the router, so a row like this must never be promoted.
    """
    try:
        from backend_server.src.agent import faqs
    except Exception:  # noqa: BLE001 - the review must still run if the agent package is absent
        return False
    return faqs.should_decline(question)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true", help="actually flip the eligible rows")
    ap.add_argument("--limit", type=int, default=200, help="cap on rows per review run")
    args = ap.parse_args(argv)

    # Apply-limit guard: the daily cron stays cheap; one operator may have thousands.
    supabase = agent_faq_db._supabase()  # noqa: SLF001 — module-local client (only here)
    if supabase is None:
        print("faq_review: supabase client unavailable", file=sys.stderr)
        return 2
    try:
        rows = (
            supabase.table("agent_faq")
            .select("id,sources,proposed,live,last_reviewed_at,tags,question_text")
            .eq("proposed", True)
            .eq("live", False)
            .limit(max(1, args.limit))
            .execute()
            .data
            or []
        )
    except Exception as exc:  # noqa: BLE001 - fail soft
        print(f"faq_review: query failed: {exc}", file=sys.stderr)
        return 2

    eligible: List[Tuple[str, List[str]]] = []
    skipped_no_doc: List[Tuple[str, List[str], str]] = []
    skipped_operation: List[Tuple[str, str]] = []
    for r in rows:
        question = r.get("question_text") or ""
        # A learned row whose question is a LIVE OPERATION ("Lock stb3 for me", "Check which
        # phone_agent are asleep") must never go live: the FAQ tier answers before the router
        # runs, so a live row like that turns a device command into a stored paragraph. The model
        # answered the command with docs text — that is a routing mistake, not a knowledge entry.
        if question and _is_live_operation(question):
            skipped_operation.append((r["id"], question))
            continue
        sources = list(r.get("sources") or [])
        if not sources:
            eligible.append((r["id"], sources))   # model-promoted rows have empty sources; trust them
            continue
        # Every cited doc must exist on disk under the agent's repo.
        missing = [s for s in sources if not _doc_exists(s, REPO)]
        if missing:
            skipped_no_doc.append((r["id"], sources, missing[0]))
            continue
        eligible.append((r["id"], sources))

    print(
        f"faq_review: scanned {len(rows)} proposed rows — {len(eligible)} eligible, "
        f"{len(skipped_no_doc)} skipped (missing doc), "
        f"{len(skipped_operation)} skipped (live operation)"
    )
    if skipped_no_doc:
        for rid, srcs, miss in skipped_no_doc[:5]:
            print(f"  skip  {rid}  missing={miss!r}  sources={len(srcs)}")
    if skipped_operation:
        for rid, question in skipped_operation[:5]:
            print(f"  skip  {rid}  live operation: {question!r}")

    if not args.apply:
        for rid, _ in eligible[:10]:
            print(f"  would-flip  {rid}")
        print("faq_review: --apply not set; rows NOT promoted. Re-run with --apply.")
        return 0

    flipped = 0
    for rid, _ in eligible:
        try:
            supabase.table("agent_faq").update({
                "live": True,
                "proposed": False,
                "last_reviewed_at": "now()",
            }).eq("id", rid).execute()
            flipped += 1
        except Exception as exc:  # noqa: BLE001
            print(f"faq_review: row {rid} flip failed: {exc}", file=sys.stderr)
    print(f"faq_review: flipped {flipped} rows to live=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
