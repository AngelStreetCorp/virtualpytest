#!/usr/bin/env python3
"""Turn an older recorded Garen run (timeline.json, no turn log) into turns.jsonl / zones.jsonl for /lol-replay.

  lol_overlay_from_timeline.py RUN_DIR [OUT_DIR]

Runs recorded after TASK-135 already have both files (shape: docs/agent/game/lol/OVERLAY_CONTRACT.md); this is only for
older runs. What it can show: health, gold, level, CS, items per sample (about every 2 s) and the bot's own events as the
"decision". It has no zones and no inputs to draw (the timeline only keeps click counts), so zones.jsonl has empty lines.
"""
import bisect
import json
import os
import sys

FRAME = {"w": 1920, "h": 1200}


def convert(run_dir, out_dir):
    tl = json.load(open(os.path.join(run_dir, "timeline.json"), encoding="utf-8"))
    events = sorted(tl.get("bot_events", []), key=lambda e: e["t"])
    ev_t = [e["t"] for e in events]
    samples = tl.get("samples", [])
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "turns.jsonl"), "w", encoding="utf-8") as f:
        for n, s in enumerate(samples):
            i = bisect.bisect_right(ev_t, s["t"]) - 1
            ev = events[i] if i >= 0 else None
            line = {"t": s["t"], "turn": n,
                    "state": {"hp": s.get("hp"), "hp_max": s.get("hp_max"), "mana": None, "mana_max": None, "level": s.get("level"),
                              "gold": s.get("gold"), "cs": (s.get("scores") or {}).get("cs"), "items": s.get("items", []),
                              "mode": "DEAD" if s.get("dead") else None},
                    "decision": {"choice": ev["kind"], "reason": ev["detail"]} if ev else {},
                    "inputs": []}
            f.write(json.dumps(line) + "\n")
    end = int(samples[-1]["t"]) + 1 if samples else 0
    with open(os.path.join(out_dir, "zones.jsonl"), "w", encoding="utf-8") as f:
        for t in range(end):
            f.write(json.dumps({"t": float(t), "frame": FRAME, "zones": []}) + "\n")


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else sys.argv[1])
