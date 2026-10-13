#!/usr/bin/env python3
"""
Backfill the Sherlock Jev shadow over past analyses (TASK-38 §5 step 4).

Live, Sherlock produces about one verdict an hour. This asks Jev the same question for every
past script result that Sherlock's LLM already classified (``check_type = ai_auto_openrouter``,
verdict parsed from ``discard_comment``), with the same state the live shadow builds, and logs
each answer to ``ai_decisions`` with ``refs = {script_result_id, sherlock, source: backfill}``.
``scripts/jev_agreement.py`` then reads them with the live rows.

Results that already have a Sherlock decision are skipped, so a rerun only adds new ones.
A result whose verification review can no longer be fetched is skipped too: Jev would not
see what the LLM saw.

Run ON THE SERVER:

    python3 scripts/jev_sherlock_backfill.py --team-id <TEAM_ID> --dry-run
    python3 scripts/jev_sherlock_backfill.py --team-id <TEAM_ID> [--limit 50]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend_server", "src"))

VERDICT = re.compile(r"^\[([A-Z_]+)\]")
COLUMNS = "id, team_id, script_name, success, error_msg, execution_time_ms, metadata, discard_comment"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--limit", type=int, default=1000, help="max script results to read")
    parser.add_argument("--dry-run", action="store_true", help="list what would be asked, call nothing")
    args = parser.parse_args()

    from agent.core.sherlock_handler import CLASSIFICATIONS, SherlockHandler
    from agent.core.sherlock_jev import INSTRUCTIONS, OPTIONS, TIMEOUT_S, USAGE, build_state
    from shared.src.lib.ai import decisions, gateway, router
    from shared.src.lib.database import ai_decisions_db
    from shared.src.lib.utils.supabase_utils import get_supabase_client

    gateway.use_local_routing()
    handler = SherlockHandler()

    done = {(r.get("refs") or {}).get("script_result_id")
            for r in ai_decisions_db.list_decisions(args.team_id, USAGE, 5000)}
    records = (get_supabase_client().table("script_results").select(COLUMNS)
               .eq("team_id", args.team_id).eq("check_type", "ai_auto_openrouter")
               .order("created_at").limit(args.limit).execute().data or [])

    counts, resolution = Counter(), None
    for record in records:
        match = VERDICT.match(record.get("discard_comment") or "")
        llm_class = match.group(1) if match else None
        if llm_class not in CLASSIFICATIONS:
            counts["no verdict"] += 1
            continue
        if record["id"] in done:
            counts["already decided"] += 1
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        has_review = bool(metadata.get("verification_review_r2_path") or metadata.get("verification_review_r2_url"))
        if args.dry_run:
            counts["would ask"] += 1
            continue
        review = handler._fetch_markdown(record)
        if has_review and not review:
            counts["review unavailable"] += 1
            continue
        resolution = resolution or router.resolve(USAGE, args.team_id)
        out = decisions.choose(resolution, build_state(record, review), OPTIONS, instructions=INSTRUCTIONS,
                               timeout_s=TIMEOUT_S, refs={"script_result_id": record["id"],
                                                          "sherlock": llm_class, "source": "backfill"})
        if not out.get("success"):
            counts["failed"] += 1
            print(f"{record['id']}: FAILED {out.get('error')}")
            continue
        counts["agree" if out["choice"] == llm_class else "disagree"] += 1
        print(f"{record['id']}: {out['choice']} conf={out.get('confidence'):.2f} llm={llm_class}")

    print(f"{len(records)} script results: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
