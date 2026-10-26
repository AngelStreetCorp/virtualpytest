#!/usr/bin/env python3
"""faq_load_public.py — load the website widget's public FAQ into ``agent_faq`` (``public = TRUE``).

Two sources, both docs-only and already public on the website / in the public docs:

1. ``scripts/agent/public_faq_seed.json``: hand-written entries, one English and one French row per
   ``group`` (question, aliases, short, long, sources). The French row is its own row, so the widget
   answers in the visitor's language. Review these like any FAQ entry: every claim must be in the cited
   doc; an entry may not name a host, an IP, a credential or a customer.
2. Every other ``### question`` section of ``docs/faq/README.md`` (English), unless a seed entry
   ``replaces_faq_heading`` it. This is what the widget's own in-process preload used to do.

Entries get ``tags = ['public', 'lang:<xx>', 'group:<slug>']``. Idempotent (upsert on the normalised
question); a row that already exists and is not public (an Atlas entry) is never touched. Atlas keeps working on the same rows: it only ignores the flag.

Usage:
    python3 scripts/agent/faq_load_public.py --dry-run     # print what would be loaded
    python3 scripts/agent/faq_load_public.py               # upsert (needs the server .env Supabase keys)
    python3 scripts/agent/faq_load_public.py --sql | <psql>  # same upsert as SQL, for a shell that has psql but no keys
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from shared.src.lib.database import agent_faq_db  # noqa: E402

SEED = REPO / "scripts" / "agent" / "public_faq_seed.json"
README = REPO / "docs" / "faq" / "README.md"
MAX_LONG = 1800


def _plain(markdown: str) -> str:
    """Docs markdown to the plain text the widget shows: no html wrappers, links, emphasis or tables."""
    out: List[str] = []
    for line in markdown.splitlines():
        if re.match(r"^\s*</?div\b", line) or re.match(r"^\s*-{3,}\s*$", line) or re.match(r"^\s*\|[-\s|:]+\|\s*$", line):
            continue
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            line = ": ".join(cells[:1]) + (" - " + "; ".join(cells[1:]) if len(cells) > 1 else "")
        out.append(line)
    text = "\n".join(out)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`]{1,3}", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def readme_entries(skip_headings: set) -> List[Dict]:
    parts = re.split(r"^###\s+(.+?)\s*$", README.read_text(encoding="utf-8"), flags=re.MULTILINE)
    entries = []
    for i in range(1, len(parts) - 1, 2):
        heading, body = parts[i].strip(), re.split(r"^##\s", parts[i + 1], flags=re.MULTILINE)[0]
        if heading in skip_headings:
            continue
        text = _plain(body)
        if not text:
            continue
        if len(text) > MAX_LONG:
            text = text[:MAX_LONG].rsplit(".", 1)[0] + "."
        first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
        entries.append({"group": "faq-" + re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-"), "lang": "en",
                        "question": heading, "aliases": [], "short": first[:280], "long": text,
                        "sources": ["faq/README.md"]})
    return entries


def all_entries() -> List[Dict]:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    skip = set()
    for e in seed:
        replaced = e.get("replaces_faq_heading") or []
        skip.update([replaced] if isinstance(replaced, str) else replaced)
    return seed + readme_entries(skip)


def _lit(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _arr(items: List[str]) -> str:
    return "ARRAY[" + ", ".join(_lit(i) for i in items) + "]::TEXT[]" if items else "'{}'::TEXT[]"


def to_sql(entries: List[Dict], normalize) -> str:
    rows = []
    for e in entries:
        tags = ["public", f"lang:{e['lang']}", f"group:{e['group']}"]
        rows.append(
            "INSERT INTO public.agent_faq (question_text, normalised_question, aliases, short, long, sources, tags, proposed, live, public) "
            f"VALUES ({_lit(e['question'])}, {_lit(normalize(e['question']))}, {_arr(e['aliases'])}, {_lit(e['short'])}, "
            f"{_lit(e['long'])}, {_arr(e['sources'])}, {_arr(tags)}, FALSE, TRUE, TRUE) "
            "ON CONFLICT (normalised_question) DO UPDATE SET question_text = EXCLUDED.question_text, aliases = EXCLUDED.aliases, "
            "short = EXCLUDED.short, long = EXCLUDED.long, sources = EXCLUDED.sources, tags = EXCLUDED.tags, "
            "proposed = FALSE, live = TRUE, public = TRUE, updated_at = NOW() WHERE agent_faq.public;")
    return "BEGIN;\n" + "\n".join(rows) + "\nCOMMIT;"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sql", action="store_true", help="print the upsert as SQL instead of calling the API")
    args = ap.parse_args()
    from backend_server.src.agent import faqs  # noqa: E402  (normalisation shared with Atlas)

    entries = all_entries()
    if args.sql:
        print(to_sql(entries, faqs.normalize))
        return 0
    failed = 0
    for e in entries:
        tags = ["public", f"lang:{e['lang']}", f"group:{e['group']}"]
        print(f"{'would load' if args.dry_run else 'load'} [{e['lang']}] {e['question']}  ({len(e['aliases'])} aliases)")
        if args.dry_run:
            continue
        existing = agent_faq_db.find_match(faqs.normalize(e["question"]))
        if existing and not existing.get("public"):
            print("  skipped: an Atlas entry owns this question (never overwrite a non-public row)")
            continue
        faq_id = agent_faq_db.upsert_seeded(
            question_text=e["question"], normalised=faqs.normalize(e["question"]), aliases=e["aliases"],
            short=e["short"], long=e["long"], sources=e["sources"], tags=tags, public=True)
        if not faq_id:
            failed += 1
    print(f"{len(entries)} entries, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
