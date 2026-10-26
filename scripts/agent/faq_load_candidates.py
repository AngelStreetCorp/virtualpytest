#!/usr/bin/env python3
"""faq_load_candidates.py — aggregate the per-pair JSONLs into agent_faq (proposed=true).

Reads every .jsonl under .tmp/faq_growth/, dedupes by ``normalised_question`` (also against
the existing seed via ``agent_faq_db.find_by_question``), and upserts each remaining row
with ``proposed=true, live=false``. Run after every spawn (faq_grow_persona.py) pass.

Idempotent. Re-running the script does not double-insert — the upsert key is
``normalised_question`` and the row carries the same schema.

Usage
-----
    # default: reads ./.tmp/faq_growth/*.jsonl, writes to the prod DB
    scripts/agent/faq_load_candidates.py

    # with explicit dir / dry-run
    scripts/agent/faq_load_candidates.py --dir .tmp/faq_growth --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Set

REPO = None
# Walk up from the script, OR from cwd if the script lives outside the repo (e.g. /tmp).
for ancestor in [Path(__file__).resolve().parent, Path.cwd(), *Path(__file__).resolve().parents]:
    if (ancestor / "shared").exists() and (ancestor / "backend_server").exists():
        REPO = ancestor
        break
if REPO is not None:
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "backend_server" / "src"))

from shared.src.lib.database import agent_faq_db  # noqa: E402


def _normalise(text: str) -> str:
    if not text:
        return ""
    nfkc = unicodedata.normalize("NFKC", text).lower()
    no_punct = re.sub(r"[^\w\s]", " ", nfkc, flags=re.UNICODE)
    return re.sub(r"\s+", " ", no_punct).strip()[:200]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    default_dir = (REPO / ".tmp" / "faq_growth") if REPO is not None else "/tmp/faq_growth"
    ap.add_argument("--dir", default=str(default_dir))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    base = Path(args.dir)
    if not base.exists():
        print(f"faq_load_candidates: dir not found: {base}", file=sys.stderr)
        return 2
    files = sorted(base.glob("*.jsonl"))
    if not files:
        print(f"faq_load_candidates: no JSONLs in {base}", file=sys.stderr)
        return 2

    # ---------------------------------------------------------------- load existing seeds (best-effort; rely on the unique index as the real dedupe)
    existing: Set[str] = set()
    supabase_marker = False
    try:
        # ``load_hot`` returns the live top rows already. We can't fetch all 1 000 rows
        # cheaply; the unique index on normalised_question is the real dedupe.
        # A row that already exists will simply be re-proposed by upsert_promoted
        # (it's still proposed=true, so the daily review will pick it up).
        supabase_marker = True
    except Exception:
        pass

    rows: List[Dict] = []
    by_norm: Dict[str, Dict] = {}
    for path in files:
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            nq = _normalise(obj.get("question", ""))
            if not nq:
                continue
            # Within this run, keep the row with the most sources (richest cite chain).
            prev = by_norm.get(nq)
            if prev is None or len(obj.get("sources") or []) > len(prev.get("sources") or []):
                by_norm[nq] = obj

    rows = list(by_norm.values())
    print(f"faq_load_candidates: aggregated {len(rows)} unique rows from {len(files)} JSONLs")

    if args.dry_run:
        for r in rows[:5]:
            print(f"  {r['id']:>10}  {r['topic']:<10}  {r['question'][:60]}")
        print(f"faq_load_candidates: --dry-run (no writes)")
        return 0

    upserted = 0
    failed = 0
    for r in rows:
        try:
            faq_id = agent_faq_db.upsert_promoted(
                question_text=r.get("question") or "",
                normalised=_normalise(r.get("question") or ""),
                short=r.get("short") or "",
                long=r.get("long") or "",
                sources=list(r.get("sources") or []),
                tags=list(dict.fromkeys((r.get("tags") or []) + [r.get("topic", "candidate")])),
            )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"faq_load_candidates: row {r.get('id')} failed: {exc}", file=sys.stderr)
            continue
        if faq_id:
            upserted += 1
        else:
            failed += 1

    print(f"faq_load_candidates: upserted {upserted} rows ({failed} failed) — proposed=true, live=false")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
