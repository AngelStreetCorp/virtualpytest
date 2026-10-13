#!/usr/bin/env python3
"""Partition v5 `no qualifying screen` abstains into VIDEO vs STATIC UI.

Two histogram runs showed ~89% of content abstains exit at v5 `no qualifying
screen`. Rolling archives turned out to be dominated by live broadcast video, which
by construction never dHash-matches a menu library. So that 89% may be mostly a
TIER 2 question ("is content playing?" - deterministic frame difference) rather than
a TIER 3 question ("what screen is this?" - needs a model).

This measures exactly that split, read-only:

    of the frames that abstain at `no qualifying screen`,
      VIDEO  = at least one ADJACENT frame differs by >= detector.FREEZE_THRESHOLD
      STATIC = every adjacent frame differs by less than that (production "frozen")
      UNKNOWN= no adjacent frame available (window edge)

Method notes that matter:
  * The diff is detector.py's EXACT measure - grayscale, absdiff, `diff > 10`,
    as a percentage - not freeze_facts.compare(), which blurs, masks a label
    corner and uses level 25. Mixing them would compare against the wrong floor.
  * Frames are read in CONTIGUOUS windows, never an even stride, so "adjacent"
    means what it means in production. detect_*_freeze() compares frame N to
    frame N-1 only.
  * --dump-static copies sample STATIC abstains out so the claim "these are real,
    unnamed UI" can be looked at rather than assumed.

Writes only under --out and --dump (default /tmp). Touches nothing else.
"""
import argparse
import glob
import json
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# VIRTUALPYTEST_REPO lets this run from /tmp on a host, where the checkout lives
# elsewhere and must not be written to; unset, it is the repo this file sits in.
_REPO = os.environ.get('VIRTUALPYTEST_REPO') or os.path.abspath(
    os.path.join(_HERE, '..', '..', '..', '..'))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_REPO, '.env'), encoding='utf-8-sig')
except Exception:
    pass

import cv2
import numpy as np

# detector.py:59  -- "0.8% pixel difference = frozen". Percentage, not a fraction.
VIDEO_FLOOR_PCT = 0.8
# detector.py:275 early-exits at 5%; anything past this is unmistakably moving.
MOVING_CLEAR_PCT = 5.0

NAMED_STATES = ('no_signal', 'blackscreen')


def diff_pct(a_gray, b_gray):
    """detector.py's per-pair difference, as a percentage. Same threshold, same units."""
    if a_gray is None or b_gray is None or a_gray.shape != b_gray.shape:
        return None
    d = cv2.absdiff(a_gray, b_gray)
    return float((np.sum(d > 10) / float(d.size)) * 100.0)


def windows(paths, n_windows, per_window):
    """Contiguous runs of real adjacent frames, spread across the whole archive.

    An even stride would compare frames minutes apart, which answers a different
    question than the one production asks. Grouping by directory keeps every
    pair inside a window genuinely consecutive.
    """
    by_dir = {}
    order = []
    for p in paths:
        # Two non-frame artefact classes sit beside the captures and must not be
        # counted as captured screens:
        #   motion_crop*      -- AVQ analysis TILES, not 16:9 frames;
        #   text_source_image*-- UI screenshots ingested as text sources.
        # Both are real UI pixels, so they land in the static bucket and make it look
        # like unidentified screens. Motion on a tile also answers a different question.
        base = os.path.basename(p)
        if "motion_crop" in base or "text_source_image" in base:
            continue
        d = os.path.dirname(p)
        if d not in by_dir:
            by_dir[d] = []
            order.append(d)
        by_dir[d].append(p)
    if not order:
        return []
    picks = []
    stride = max(1, len(order) // max(1, n_windows))
    chosen = order[::stride][:n_windows]
    for d in chosen:
        picks.append(by_dir[d][:per_window])
    return [w for w in picks if len(w) >= 2]


def is_no_qualifying(result):
    return "no qualifying screen" in (result.get("reason") or "").lower()


def load_histogram(path):
    """abstain_histogram, from the repo if it is importable, else from --histogram.

    On a host this file may be newer than the deployed tree, so `--histogram`
    points at a copy in /tmp; loading by path means the host's own checkout is
    never written to, and `VIRTUALPYTEST_REPO` still points abstain_histogram at
    the DEPLOYED image_helpers -- so the matcher measured here is production's.
    """
    import importlib.util
    if path:
        spec = importlib.util.spec_from_file_location("abstain_histogram", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["abstain_histogram"] = mod
        spec.loader.exec_module(mod)
        return mod
    from features.avq.backend_host.localize import abstain_histogram as mod
    return mod


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ui", action="append", default=[], help="userinterface (repeatable)")
    ap.add_argument("--capture", action="append", default=[], help="capture base dir")
    ap.add_argument("--source", choices=("cold", "hot", "both"), default="cold")
    ap.add_argument("--windows", type=int, default=60, help="contiguous windows to read")
    ap.add_argument("--per-window", type=int, default=20, help="adjacent frames per window")
    ap.add_argument("--dump-static", type=int, default=0,
                    help="copy up to N static-abstain frames out for inspection")
    ap.add_argument("--dump-dir", default="/tmp/vvu_static",
                    help="where --dump-static frames go")
    ap.add_argument("--histogram", default="",
                    help="path to abstain_histogram.py; empty = import from the repo "
                         "(set it when running from /tmp on a host)")
    ap.add_argument("--out", default="/tmp/video_vs_ui.json")
    args = ap.parse_args()

    H = load_histogram(args.histogram)
    ImageHelpers, origin = H.load_image_helpers()
    print("matcher:", origin, flush=True)

    if args.dump_static:
        if os.path.isdir(args.dump_dir):
            shutil.rmtree(args.dump_dir)
        os.makedirs(args.dump_dir, exist_ok=True)

    report = {"_floor_pct": VIDEO_FLOOR_PCT, "_windows": args.windows,
              "_per_window": args.per_window, "ui": {}}
    dumps = 0

    for ui in args.ui:
        node_fps = H.load_node_fps_from_db(ui)
        helpers = ImageHelpers(None, None)
        t = {"matched": 0, "matched_static": 0, "matched_video": 0,
             "named_state": 0, "abstain_other": 0, "nq_total": 0,
             "nq_video": 0, "nq_static": 0, "nq_unknown": 0,
             "matched_frames": 0}
        nq_diffs, matched_diffs = [], []

        for cap in args.capture:
            # find_frames() already resolves `captures/`, `cold/captures/` and
            # `hot/captures/` relative to the capture base dir, so pass the base.
            allf = H.find_frames(cap, args.source)
            print("\n[%s] %d frames under %s" % (ui, len(allf), cap), flush=True)
            for win in windows(allf, args.windows, args.per_window):
                prev_gray = None
                pairs = []          # (index, diff_pct) for the pair ENDING at index
                imgs = []
                for p in win:
                    img = cv2.imread(p)
                    if img is None:
                        imgs.append(None)
                        pairs.append(None)
                        prev_gray = None
                        continue
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    imgs.append(img)
                    pairs.append(diff_pct(prev_gray, gray))
                    prev_gray = gray

                for i, img in enumerate(imgs):
                    if img is None:
                        continue
                    try:
                        res = helpers.identify_screen(img, node_fps)
                    except Exception as exc:                 # never die on one bad frame
                        print("  ! %s: %s" % (os.path.basename(win[i]), exc), flush=True)
                        continue
                    bucket, door, reason, state = H.classify(res)
                    # the pair ending here, and the pair starting here
                    near = [d for d in (pairs[i], pairs[i + 1] if i + 1 < len(pairs) else None)
                            if d is not None]
                    peak = max(near) if near else None

                    if state in NAMED_STATES:
                        t["named_state"] += 1
                        continue
                    if bucket == "matched":
                        t["matched"] += 1
                        if peak is None:
                            pass
                        elif peak >= VIDEO_FLOOR_PCT:
                            t["matched_video"] += 1
                        else:
                            t["matched_static"] += 1
                        if peak is not None:
                            matched_diffs.append(peak)
                        continue
                    if not is_no_qualifying(res):
                        t["abstain_other"] += 1
                        continue

                    t["nq_total"] += 1
                    if peak is None:
                        t["nq_unknown"] += 1
                    else:
                        nq_diffs.append(peak)
                        if peak >= VIDEO_FLOOR_PCT:
                            t["nq_video"] += 1
                        else:
                            t["nq_static"] += 1
                            if dumps < args.dump_static:
                                # The archiver rotates cold captures out from under a
                                # replay, so the frame can vanish between identify_screen
                                # and here. A missing dump must not abort the run -- the
                                # tally above is already correct without it.
                                try:
                                    shutil.copyfile(win[i], os.path.join(
                                        args.dump_dir, "%s_static_%03d_%s"
                                        % (ui, dumps, os.path.basename(win[i]))))
                                    dumps += 1
                                except OSError as exc:
                                    print("  ~ dump skipped %s: %s"
                                          % (os.path.basename(win[i]), exc), flush=True)

        tot = t["nq_total"] or 1
        report["ui"][ui] = {
            "tally": t,
            "pct_video": round(100.0 * t["nq_video"] / tot, 1),
            "pct_static": round(100.0 * t["nq_static"] / tot, 1),
            "pct_unknown": round(100.0 * t["nq_unknown"] / tot, 1),
            "nq_diff_percentiles": pct(nq_diffs),
            "matched_diff_percentiles": pct(matched_diffs),
        }
        r = report["ui"][ui]
        print("\n=== %s ===" % ui, flush=True)
        print("  named capture state   %d" % t["named_state"], flush=True)
        print("  matched               %d  (static %d / video %d)"
              % (t["matched"], t["matched_static"], t["matched_video"]), flush=True)
        print("  other abstain         %d" % t["abstain_other"], flush=True)
        print("  no qualifying screen  %d" % t["nq_total"], flush=True)
        print("    VIDEO  (peak diff >= %.1f%%)  %5d   %5.1f%%"
              % (VIDEO_FLOOR_PCT, t["nq_video"], r["pct_video"]), flush=True)
        print("    STATIC (frozen)               %5d   %5.1f%%"
              % (t["nq_static"], r["pct_static"]), flush=True)
        print("    UNKNOWN (no adjacent frame)   %5d   %5.1f%%"
              % (t["nq_unknown"], r["pct_unknown"]), flush=True)
        print("  nq peak-diff  %s" % r["nq_diff_percentiles"], flush=True)
        print("  match peak-diff %s" % r["matched_diff_percentiles"], flush=True)

    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=1)
    if args.dump_static:
        print("\ndumped %d static-abstain frames to %s" % (dumps, args.dump_dir), flush=True)
    print("wrote", args.out, flush=True)


def pct(values):
    if not values:
        return {}
    s = sorted(values)
    return {k: round(s[min(len(s) - 1, int(len(s) * q))], 3)
            for k, q in (("p10", .10), ("p25", .25), ("p50", .50),
                         ("p75", .75), ("p90", .90), ("max", .999))}


if __name__ == "__main__":
    main()