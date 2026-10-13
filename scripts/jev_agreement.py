#!/usr/bin/env python3
"""
Agreement report for a Jev shadow decision (TASK-38 §5): how often the decision model
picked the same option as today's path, per confidence level. Use it to set the
threshold above which Jev may decide alone.

Run ON THE SERVER:

    python3 scripts/jev_agreement.py --team-id <TEAM_ID>                       # Sherlock verdicts
    python3 scripts/jev_agreement.py --team-id <TEAM_ID> --usage text.decision.sherlock --ref sherlock

Reads ai_decisions rows of ``--usage``; the reference answer is ``refs[--ref]`` (the
LLM's verdict for Sherlock), overridden by ``outcome.label`` when a human set one.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# (label, low, high): confidence buckets, high exclusive.
BUCKETS = ((">=0.9", 0.9, 1.01), ("0.8-0.9", 0.8, 0.9), ("0.7-0.8", 0.7, 0.8), ("0.6-0.7", 0.6, 0.7),
           ("<0.6", 0.0, 0.6))


def summarize(rows: list[dict], ref_key: str) -> dict:
    """Pure: ai_decisions rows -> agreement overall and per confidence bucket."""
    pairs = []
    for row in rows:
        answer = (row.get("answers") or {}).get("choice") or {}
        reference = (row.get("outcome") or {}).get("label") or (row.get("refs") or {}).get(ref_key)
        if row.get("ok") and answer.get("choice") and reference:
            pairs.append((answer["choice"], reference, float(answer.get("confidence") or 0)))
    buckets = {}
    for label, low, high in BUCKETS:
        sel = [p for p in pairs if low <= p[2] < high]
        buckets[label] = {"n": len(sel), "agree": sum(1 for p in sel if p[0] == p[1])}
    return {
        "n": len(pairs),
        "agree": sum(1 for p in pairs if p[0] == p[1]),
        "buckets": buckets,
        "confusion": Counter((p[1], p[0]) for p in pairs if p[0] != p[1]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--usage", default="text.decision.sherlock")
    parser.add_argument("--ref", default="sherlock", help="refs key holding today's answer")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    from shared.src.lib.database import ai_decisions_db
    rows = ai_decisions_db.list_decisions(args.team_id, args.usage, args.limit)
    s = summarize(rows, args.ref)
    print(f"{args.usage}: {len(rows)} decisions, {s['n']} with a reference")
    if s["n"]:
        print(f"agreement {s['agree']}/{s['n']} = {s['agree'] / s['n']:.0%}")
    for label, b in s["buckets"].items():
        rate = f"{b['agree'] / b['n']:.0%}" if b["n"] else "-"
        print(f"  confidence {label:>8}: {b['agree']}/{b['n']} {rate}")
    for (ref, jev), n in s["confusion"].most_common(10):
        print(f"  reference {ref} -> Jev {jev}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
