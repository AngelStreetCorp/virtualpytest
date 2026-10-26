#!/usr/bin/env python3
"""Reward layer over run folders: ``reward_report.py <run folder>... [--priors docs/agent/game/lol/action_priors.json]``.

Annotates each folder's turns.jsonl (rewards, outcomes), writes decisions.jsonl / reward_summary.json, prints the per-action table, and
with ``--priors`` writes the empirical priors per (situation bucket, action) over all the folders given.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from shared.src.lib.game.leagueoflegends import outcomes  # noqa: E402
from shared.src.lib.game.leagueoflegends.turn_log import read_turns  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--priors")
    a = ap.parse_args()
    all_runs = []
    for d in a.runs:
        s = outcomes.finalize(d)
        if not s:
            print(f"{d}: no turns")
            continue
        all_runs.append(read_turns(os.path.join(d, "turns.jsonl")))
        print(f"{d}: total {s['total_reward']} over {s['turns']} turns, useless action rate {s['useless_action_rate']}")
        for act, r in sorted(s["actions"].items()):
            print(f"  {act:8} n={r['n']:5} reward={r['reward']:8} mean={r['mean_reward']:8} useless={r['useless_rate']}")
        print("  events:", json.dumps(s["events"]))
    if a.priors and all_runs:
        pr = outcomes.priors(all_runs)
        with open(a.priors, "w", encoding="utf-8") as f:
            json.dump({"runs": len(all_runs), "rewards": outcomes.REWARDS, "buckets": pr}, f, indent=1)
        print(f"priors: {len(pr)} buckets -> {a.priors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
