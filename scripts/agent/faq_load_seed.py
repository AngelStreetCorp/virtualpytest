#!/usr/bin/env python3
"""faq_load_seed.py — load the TASK-152 FAQ seed into ``agent_faq``.

Reads ``docs/tasks/TASK-152-faq-seed.md`` (the curated seed of 100 questions grouped by topic),
parses each row, and upserts every entry into ``agent_faq``. Idempotent on re-run (the SQL upsert
matches on ``normalised_question``). Use after a successful integration lane merge and a server-only
deploy — the table is created by ``setup/db/schema/078_agent_faq.sql``.

Usage
-----
    DATABASE_URL=postgres://...    python3 scripts/agent/faq_load_seed.py           # via supabase client
    python3 scripts/agent/faq_load_seed.py --dry-run                                  # parse and print, no DB
    python3 scripts/agent/faq_load_seed.py --seed docs/tasks/TASK-152-faq-seed.md      # point at a custom seed

The loader reads ``AUTO_SIGN_TOKEN`` is unnecessary (it only writes). It logs every row it upserts
and prints a summary; exit code is non-zero on a DB error so CI / deploy scripts can detect a
seed-loading failure.

Why a separate script (not part of the daily review):
- the seed is the curated knowledge; the review pass is for learned entries the model wrote.
- one-shot idempotent path keeps the deploy simple: docs push → migration → seed → done.

Companion task doc: ``docs/tasks/TASK-152-atlas-answers-under-10s.md`` § Phase 9 — Prepared FAQ.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend_server" / "src"))

from shared.src.lib.database import agent_faq_db  # noqa: E402


# Parsing the seed markdown ---------------------------------------------------

_ROW_PATTERN = re.compile(
    r"^\|\s*([a-z]+-\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([YN])\s*\|\s*$"
)


def parse_seed(path: Path) -> List[Dict]:
    """Parse the seed table rows out of the markdown. Skip blanks, headers, and preamble."""
    rows: List[Dict] = []
    if not path.exists():
        raise FileNotFoundError(f"seed file not found: {path}")
    in_table = False
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip()
            if not line:
                continue
            if line.startswith("| id "):
                in_table = True
                continue
            if in_table and line.startswith("|---"):
                continue
            if in_table and not line.startswith("|"):
                in_table = False
            if not in_table or not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 6:
                continue
            row_id, topic, question, short, pointer, has_doc_answer = cells[:6]
            if not re.fullmatch(r"[a-z]+-\d+", row_id):
                continue
            rows.append({
                "id": row_id,
                "topic": topic,
                "question": question,
                "short": short,
                "pointer": pointer,
                "has_doc_answer": has_doc_answer == "Y",
            })
    return rows


# Aliases are NOT derived from the question phrasing any more.
#
# The loader used to write the first 3-4 content words of the question plus a "topic firstword"
# pair ("IR what", "why are my", "Devices can"). Those aliases are broken in two ways: they do not
# resolve to their own row (they carry only generic words, which other rows carry too), and they
# squat on queries — a stray "Setup my" was enough to stop another row from claiming its own
# question. Measured on the live corpus, 166 of them landed on another row or on nothing.
#
# An alias built from the question's own words is worthless anyway: the alias tier already scores
# the query against the canonical question's tokens, so an alias made of those same words adds no
# coverage and only adds collision risk.
#
# Aliases that carry real value are wordings with DIFFERENT words, and only a model can write
# those. The single owner of aliases is therefore the validated backfill
# (``scripts/agent/faq_alias_backfill.py``), which generates them, checks that each one resolves
# to its own row, and refuses the ones that would steal another row's query. The loader writes
# questions and answers only.


def alias_seed(question: str, topic: str) -> List[str]:
    """No aliases from the loader — see the note above.

    Kept as a function because the loader, the public loader and the tests call it; it now
    returns an empty list, and ``upsert_seeded`` only fills an EMPTY alias set, so re-seeding
    never touches the alias set the backfill owns.
    """
    return []


def _normalise(text: str) -> str:
    """Same as ``shared/src/lib/database/agent_faq_db._norm``. Duplicated here to keep the loader
    standalone when ``--dry-run`` is used (no DB connect)."""
    import unicodedata
    if not text:
        return ""
    nfkc = unicodedata.normalize("NFKC", text).lower()
    no_punct = re.sub(r"[^\w\s]", " ", nfkc, flags=re.UNICODE)
    return re.sub(r"\s+", " ", no_punct).strip()[:200]


def short_and_long(row: Dict) -> Dict:
    """Build the short and long forms from the row. The seed has the short line; the long is
    derived from the row's pointer so a follow-up "more" request can show the doc + section."""
    short = row["short"].strip()
    pointer = row["pointer"]
    long = f"{short}\n\nSource: {pointer}"
    return {"short": short, "long": long}


# --------------------------------------------------------------------------- main


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--seed",
        default=str(REPO / "docs" / "tasks" / "TASK-152-faq-seed.md"),
        help="path to the seed markdown (default: docs/tasks/TASK-152-faq-seed.md)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and print what would be written; no DB calls",
    )
    args = parser.parse_args(argv)

    seed_path = Path(args.seed)
    rows = parse_seed(seed_path)
    if not rows:
        print(f"faq_load_seed: no rows parsed from {seed_path}", file=sys.stderr)
        return 2

    print(f"faq_load_seed: parsed {len(rows)} rows from {seed_path}")

    enriched: List[Dict] = []
    for row in rows:
        sl = short_and_long(row)
        topic = (row["topic"] or "").strip().lower() or "misc"
        enriched.append({
            "id": row["id"],
            "question_text": row["question"],
            "normalised_question": _normalise(row["question"]),
            "aliases": alias_seed(row["question"], row["topic"]),
            "short": sl["short"],
            "long": sl["long"],
            "sources": [row["pointer"]] if row["has_doc_answer"] else [],
            "tags": [topic, "seed"],
        })

    if args.dry_run:
        for entry in enriched:
            print(
                f"  {entry['id']:>10}  {entry['question_text'][:60]:<60}  "
                f"aliases={len(entry['aliases'])} tag={entry['tags'][0]}"
            )
        print(f"faq_load_seed: --dry-run (no writes)")
        return 0

    # Real path — upsert each row.
    written = 0
    failed = 0
    for entry in enriched:
        faq_id = agent_faq_db.upsert_seeded(
            question_text=entry["question_text"],
            normalised=entry["normalised_question"],
            aliases=entry["aliases"],
            short=entry["short"],
            long=entry["long"],
            sources=entry["sources"],
            tags=entry["tags"],
        )
        if faq_id:
            written += 1
        else:
            failed += 1
            print(f"faq_load_seed: row {entry['id']} upsert failed", file=sys.stderr)

    print(f"faq_load_seed: upserted {written} of {len(enriched)} rows ({failed} failed)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
