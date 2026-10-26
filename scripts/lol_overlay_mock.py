#!/usr/bin/env python3
"""Mock LoL overlay data in the exact format of docs/agent/game/lol/OVERLAY_CONTRACT.md.

  lol_overlay_mock.py OUT_DIR [--seconds 120] [--live]

Writes OUT_DIR/zones.jsonl and turns.jsonl (replay). With --live it also rewrites
OUT_DIR/lol-overlay-live.json every 0.5 s until stopped (point LOL_OVERLAY_LIVE_PATH at it).
"""
import argparse
import json
import math
import os
import time

FRAME = {"w": 1920, "h": 1200}


def zones_at(t):
    swing = 0.04 * math.sin(t / 6)
    return [
        {"id": "tur1", "kind": "enemy_turret", "level": "danger", "shape": "circle",
         "x": 0.62 + swing, "y": 0.22, "r": 0.17, "reason": "enemy turret range, 1 of 3 allied minions inside"},
        {"id": "min1", "kind": "enemy_minion_threat", "level": "caution", "shape": "circle",
         "x": 0.55, "y": 0.5 + swing, "r": 0.08, "reason": "3 enemy minions focus Garen"},
        {"id": "safe1", "kind": "safe", "level": "safe", "shape": "polygon",
         "points": [[0.2, 0.55], [0.42, 0.55], [0.42, 0.85], [0.2, 0.85]], "reason": "behind allied minions"},
    ]


def turn_at(t, n):
    kinds = [
        {"kind": "right_click", "x": 0.52, "y": 0.51},
        {"kind": "left_click", "x": 0.58, "y": 0.45},
        {"kind": "key", "key": "Q"},
        {"kind": "minimap", "x": 0.88, "y": 0.9},
        {"kind": "key", "key": "E"},
    ]
    return {
        "t": round(t, 1), "turn": n,
        "state": {"hp": 810 - (n * 7) % 400, "hp_max": 810, "mana": 0, "mana_max": 0, "level": 1 + n // 40, "gold": 500 + n * 3,
                  "cs": n // 4, "ad": 78, "armor": 38, "mr": 32, "attack_speed": 0.7, "move_speed": 340,
                  "items": ["Doran's Shield"], "pos_minimap": [0.12, 0.08], "mode": "LANE"},
        "decision": {"choice": "last_hit", "options": [{"id": "last_hit", "p": 0.9}, {"id": "back", "p": 0.1}],
                     "reason": "minion m2 killable (hp 61 <= 78)"},
        "inputs": [kinds[n % len(kinds)]],
    }


def write_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    with open(os.path.join(a.out_dir, "zones.jsonl"), "w") as f:
        for s in range(a.seconds):
            f.write(json.dumps({"t": float(s), "frame": FRAME, "zones": zones_at(s)}) + "\n")
    with open(os.path.join(a.out_dir, "turns.jsonl"), "w") as f:
        for n in range(int(a.seconds / 0.7)):
            f.write(json.dumps(turn_at(n * 0.7, n)) + "\n")
    if a.live:
        n, t0 = 0, time.time()
        while True:
            t = time.time() - t0
            turn = turn_at(t, n)
            recent = [dict(i, age_s=round(0.7 * k, 2)) for k, i in enumerate(
                [turn_at(t - 0.7 * k, n - k)["inputs"][0] for k in range(4)])]
            write_atomic(os.path.join(a.out_dir, "lol-overlay-live.json"),
                         {"t": round(t, 1), "frame": FRAME, "zones": zones_at(t), "recent_inputs": recent,
                          "state": turn["state"], "decision": turn["decision"]})
            n += 1
            time.sleep(0.5)


if __name__ == "__main__":
    main()
