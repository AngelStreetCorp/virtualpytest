#!/usr/bin/env python3
"""Flag ai_calls rows that claim a billed model answered with 0 tokens (BUG-0721).

Run on the server (service-role DB access):

    python3 scripts/ai_calls_audit.py            # last 24 h
    python3 scripts/ai_calls_audit.py --hours 72

Prints one line per (usage, endpoint, model) with the count and exits 1 when any row is found: a call site reads
its usage block wrong (or not at all), so the provider bills calls the AI usage page shows as free.
Rules: shared/src/lib/ai/call_audit.py, docs/agent/ai/AI_ROUTING.md "The logging contract".
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.src.lib.ai import call_audit  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()
    suspects = call_audit.fetch_suspects(args.hours)
    if not suspects:
        print(f"OK: no zero-token billed calls in the last {args.hours} h")
        return 0
    groups = Counter((r["usage_key"], r["endpoint"], r.get("model") or "?") for r in suspects)
    print(f"FAIL: {len(suspects)} ok calls with 0 tokens on billed endpoints in the last {args.hours} h")
    for (usage, endpoint, model), n in groups.most_common():
        print(f"  {n:5d}  {usage}  {endpoint}/{model}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
