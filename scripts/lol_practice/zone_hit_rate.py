#!/usr/bin/env python3
"""Do the danger zones predict the damage Garen took? usage: zone_hit_rate.py <run folder> [--reach PX ...]

Reads turns.jsonl + zones.jsonl of a run folder. For each turn Garen lost health, finds the zones of that game second and reports the
share of the damage (and of the turns) that happened with Garen inside a danger/caution zone, and for several enemy-minion reach radii
(distance from Garen to the nearest enemy minion zone centre), so the radii in danger_zones.py can be tuned from recorded games.
"""
import bisect
import json
import math
import sys

PLAYER = (868, 545)


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def main(argv):
    d = argv[0]
    reaches = [int(x) for x in argv[argv.index("--reach") + 1:]] if "--reach" in argv else [223, 350, 450, 550, 663]
    turns, zones = load(f"{d}/turns.jsonl"), load(f"{d}/zones.jsonl")
    zt = [z["t"] for z in zones]
    rows = []
    for a, b in zip(turns, turns[1:]):
        lost = max(0, a["state"]["hp"] - b["state"]["hp"])
        zs = zones[max(0, bisect.bisect_right(zt, a["t"]) - 1)]["zones"]
        dm = [math.hypot(z["x"] * 1920 - PLAYER[0], z["y"] * 1200 - PLAYER[1]) for z in zs if z["kind"] == "enemy_minion_threat"]
        rows.append((lost, a["decision"]["zones"]["standing_in"], min(dm) if dm else None))
    total = sum(r[0] for r in rows) or 1
    inz = [r for r in rows if r[1]]
    print(f"{len(rows)} turns, {total} hp lost; inside a logged zone: {len(inz)} turns ({len(inz) / len(rows):.0%}), "
          f"{sum(r[0] for r in inz) / total:.0%} of the damage")
    for R in reaches:
        sel = [r for r in rows if r[2] is not None and r[2] <= R]
        dmg = sum(r[0] for r in sel)
        print(f"nearest enemy minion within {R:4d} px: {len(sel):4d} turns ({len(sel) / len(rows):.0%}), {dmg / total:.0%} of the damage, "
              f"{dmg / max(1, len(sel)):.2f} hp/turn")


if __name__ == "__main__":
    main(sys.argv[1:])
