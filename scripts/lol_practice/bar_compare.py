"""Compare two bar detectors on saved full-resolution frames: what the second one finds that the first one misses, by fill, and the time per frame.

A detector is ``fn(rgb_uint8_array, team) -> list of Bar`` (kind, x, y, frac, team, ...). Usage:
  PYTHONPATH=. python3 scripts/lol_practice/bar_compare.py <run_dir/cap> [--b module:function] [--every 12] [--roi]
The first detector is ``perception.find_bars``; ``--b`` names the candidate (default: the same, as a self-check). Bars are matched on position
(<= 12 px in x, <= 6 px in y). Reported: bars found by A, by B, only by B (the misses of A) split by fill bin and by distance to Garen, only by A
(candidate false bars), and the per-frame time p50 / p95 of each. Bars with fill <= 15 % are the minions one auto from dying."""
import argparse
import glob
import importlib
import math
import os
import time

import cv2

from shared.src.lib.game.leagueoflegends.perception import HUD_Y, PLAYER_XY, find_bars

ROI = (360, 120, 1560, 900)
# the exclusion zones find_bars hard-codes, as rectangles for detectors that take them from the caller (bar_frames.find_bar_frames)
EXCLUDE = [(0, 0, 100, 1200), (0, 0, 1920, 60), (0, int(HUD_Y), 1920, 1200), (1590, 680, 1920, 1200), (1500, 0, 1920, 340), (0, 430, 540, 890),
           (0, 930, 780, 1200), (1880, 340, 1920, 1200)]


def load(spec):
    if not spec:
        return find_bars
    mod, fn = spec.split(":")
    return getattr(importlib.import_module(mod), fn)


def match(a, b):
    return abs(a.x - b.x) <= 12 and abs(a.y - b.y) <= 6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cap")
    ap.add_argument("--b", default=None)
    ap.add_argument("--every", type=int, default=12)
    ap.add_argument("--roi", action="store_true")
    a = ap.parse_args()
    fa, fb = find_bars, load(a.b)
    frames_style = bool(a.b and a.b.endswith("find_bar_frames"))
    frames = sorted(glob.glob(os.path.join(a.cap, "t*.jpg")))[::a.every]
    ta, tb = [], []
    only_b, only_a, nA, nB = [], [], 0, 0
    for f in frames:
        rgb = cv2.imread(f)[..., ::-1].copy()
        for team in ("enemy", "ally"):
            t0 = time.perf_counter()
            A = [x for x in (fa(rgb, team, ROI) if a.roi else fa(rgb, team)) if x.kind == "minion"]
            t1 = time.perf_counter()
            if frames_style:  # one pass finds both teams: filter by team ("unknown" empty bars count for the enemy pass)
                allb = fb(rgb, EXCLUDE, ROI) if a.roi else fb(rgb, EXCLUDE)
                B = [x for x in allb if x.kind == "minion" and (x.team == team or (team == "enemy" and x.team == "unknown"))]
            else:
                B = [x for x in (fb(rgb, team, ROI) if a.roi else fb(rgb, team)) if x.kind == "minion"]
            t2 = time.perf_counter()
            ta.append((t1 - t0) * 1000)
            tb.append((t2 - t1) * 1000)
            nA += len(A)
            nB += len(B)
            only_b += [(x, team) for x in B if not any(match(x, y) for y in A)]
            only_a += [(x, team) for x in A if not any(match(x, y) for y in B)]
    n = len(frames)

    def pct(v, p):
        v = sorted(v)
        return v[min(int(len(v) * p), len(v) - 1)]

    print(f"frames {n}  bars A {nA}  bars B {nB}  only B {len(only_b)}  only A {len(only_a)}")
    for name, lst in (("only B (missed by A)", only_b), ("only A (not confirmed by B)", only_a)):
        low = [x for x, _ in lst if x.frac <= 0.15]
        near = [x for x, _ in lst if math.hypot(x.x - PLAYER_XY[0], x.y - PLAYER_XY[1]) <= 380]
        print(f"  {name}: {len(lst)}  fill<=15%: {len(low)}  within 380 px of Garen: {len(near)}")
    print(f"  time per team pass, ms: A p50 {pct(ta, .5):.1f} p95 {pct(ta, .95):.1f}   B p50 {pct(tb, .5):.1f} p95 {pct(tb, .95):.1f}")


if __name__ == "__main__":
    main()
