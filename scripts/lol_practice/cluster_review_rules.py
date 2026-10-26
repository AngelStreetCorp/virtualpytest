#!/usr/bin/env python3
"""Cluster the RULE lines of docs/agent/game/lol/REVIEW_LOG.md into recurring problems, counted and ranked (TASK-131).

    python3 scripts/lol_practice/cluster_review_rules.py [--md]

A rule line can belong to several clusters (a last-hit rule that also names allied damage counts in both). Keyword rules are
the cluster definitions below: change them here, not in the output. Examples are the two lowest-scoring games of each
cluster when ``~/vpt-deliverables/lol-progress/cache.json`` knows their overall score, else the first two.
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = os.path.join(ROOT, "docs", "agent", "game", "lol", "REVIEW_LOG.md")
CLUSTERS = [  # key, title, regex on the rule line (case-insensitive)
    ("lasthit_priority", "Last-hit decision loses to positioning: the bot holds or retreats while a low minion dies",
     r"(overrid\w+|priority over|top priority|instead of).*(hold|position|brush|movement|retreat|idle|wave)|(hold|brush).*overrid"),
    ("lasthit_predict", "Last-hit timing ignores incoming allied-minion damage: attack when predicted health at impact is below our damage",
     r"(allied|ally)[^.]*(damage|hits)|predicted|windup|travel"),
    ("lasthit_reach", "Last-hit reach and threshold: act on any minion near AD within a wider range / margin (0.9-1.3 x AD, 300-700 units)",
     r"(1\.\d+|0\.9\d?|95 ?%|90 ?%).{0,25}(auto|AD|damage)|within (attack range|\d{3})"),
    ("turret", "Turret damage: the bot walks into enemy tower range",
     r"turret|tower"),
    ("recall", "Recall discipline: recalls at the wrong gold, health or wave state",
     r"recall"),
    ("opening", "Opening buy: leaves the fountain before buying the starter items",
     r"fountain|doran|starter"),
    ("safety", "Aggression ignores health or champion presence",
     r"hp (>|<|above|below)|enemy champion|% hp|health"),
]


def rows():
    out = []
    for ln in open(LOG, encoding="utf-8"):
        if ln.startswith("| garen-run") or ln.startswith("| bench-run"):
            c = [x.strip() for x in ln.strip().strip("|").split("|")]
            out.append({"game": c[0], "rule": c[2]})
    return out


def scores():
    p = os.path.expanduser("~/vpt-deliverables/lol-progress/cache.json")
    try:
        return {v["run"]: v["overall"] for v in json.load(open(p)).values() if v.get("overall") is not None}
    except (OSError, ValueError):
        return {}


def main() -> int:
    rs, sc = rows(), scores()
    res = []
    other = r"turret|tower|recall|fountain|doran|starter"  # those rules belong to their own cluster only
    for key, title, rx in CLUSTERS:
        lasthit = key.startswith("lasthit") or key == "safety"
        hit = [r for r in rs if re.search(rx, r["rule"], re.I)
               and (not lasthit or (re.search(r"minion", r["rule"], re.I) and not re.search(other, r["rule"], re.I)))]
        hit.sort(key=lambda r: sc.get(r["game"], 999))
        res.append({"key": key, "title": title, "n": len(hit), "examples": [(h["game"], h["rule"]) for h in hit[:2]]})
    res.sort(key=lambda c: -c["n"])
    if "--md" in sys.argv:
        print(f"Clustered from {len(rs)} reviewed games (REVIEW_LOG.md, Opus reviewer where present). One rule line can count in several clusters.\n")
        print("| # | Recurring problem | Games | Two examples |\n|---|---|---|---|")
        for i, c in enumerate(res[:5], 1):
            ex = "; ".join(f"`{g}`: {r[:110]}" for g, r in c["examples"])
            print(f"| {i} | {c['title']} | {c['n']} of {len(rs)} | {ex} |")
    else:
        print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
