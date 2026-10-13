#!/usr/bin/env python3
"""
Live check of Jev decisions (TASK-38 §5): one sub-cent call to the Decisions API through
the AI router, logged to ai_decisions.

Run ON THE SERVER (it reads the routing tables and the OpenRouter key from the secrets
store), after applying setup/db/migrations/20261002a_ai_decisions.sql:

    python3 scripts/jev_check.py --team-id <TEAM_ID>
    python3 scripts/jev_check.py --team-id <TEAM_ID> --profile jev   # pinned, no fallback

It asks three typed questions (noul, choice, score) about a made-up support ticket whose
facts point clearly one way, prints answers, latency, tokens and cost, and exits 0 only if
every answer came back typed, the obvious ones went the expected way and the call was logged.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

STATE = {
    "ticket": "After the 4.2 update the set-top box reboots every time I open the EPG. Tried a factory reset, same.",
    "customer_tier": "premium",
}

QUESTIONS = {
    "defect": {"type": "noul", "instructions": "Is the customer reporting a software defect?",
               "criteria": {"true": "the product misbehaves because of its software",
                            "false": "a question, a request or a user mistake"}},
    "team": {"type": "choice", "instructions": "Which team should own this ticket?",
             "criteria": {"firmware": "crashes, reboots, update regressions on the device",
                          "billing": "payments, invoices, subscriptions",
                          "content": "missing channels or programmes"}},
    "urgency": {"type": "score", "instructions": "How urgent is this ticket?",
                "criteria": ["low", "normal", "high"]},
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--team-id", required=True, help="team the decision is logged under")
    parser.add_argument("--profile", help="pin this profile (no fallback) instead of the text.decision route")
    args = parser.parse_args()

    from shared.src.lib.ai import decisions, gateway, router

    gateway.use_local_routing()
    resolution = (router.resolve_profile(args.profile, "text.decision", args.team_id) if args.profile
                  else router.resolve("text.decision", args.team_id))
    out = decisions.decide(resolution, STATE, QUESTIONS, refs={"check": "jev_check"})
    print(json.dumps(out, indent=2, default=str))
    if not out["success"]:
        print(f"FAIL: {out['error']}")
        return 1
    answers = out["answers"]
    problems = []
    if float(answers["defect"].get("noul") or 0) < 0.5:
        problems.append("noul 'defect' < 0.5 for a reboot after an update")
    if answers["team"].get("choice") != "firmware":
        problems.append(f"choice 'team' = {answers['team'].get('choice')}, expected firmware")
    if not out.get("decision_id"):
        problems.append("not logged to ai_decisions (migration applied? team id valid?)")
    for p in problems:
        print(f"WARN: {p}")
    print("OK" if not problems else "DONE WITH WARNINGS")
    return 0 if not problems else 2


if __name__ == "__main__":
    sys.exit(main())
