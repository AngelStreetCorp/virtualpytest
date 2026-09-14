#!/usr/bin/env python3
"""No-reference focus detector — CLI wrapper.

The detection logic now lives in the verification package
(backend_host/src/controllers/verification/focus_detector.py) so production
(image_helpers._focus_crop_hex) and this dev tool share ONE implementation.
This file re-exports detect_focus/FocusCandidate and keeps the annotate + CLI.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

import cv2

# Import the single-source detector from the verification package.
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "src", "controllers", "verification")))
from focus_detector import FocusCandidate, detect_focus  # noqa: E402,F401


def annotate(img_bgr, candidates):
    out = img_bgr.copy()
    if not candidates:
        return out
    # best in green, others yellow
    for idx, c in enumerate(candidates):
        x, y, w, h = c.box
        color = (0, 255, 0) if idx == 0 else (0, 220, 255)
        cv2.rectangle(out, (x, y), (x+w, y+h), color, 3 if idx == 0 else 2)
        label = f"{idx+1}:{c.cue_type} {c.score:.2f} {c.color}"
        cv2.putText(out, label, (x, max(20, y-8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+", help="image paths")
    ap.add_argument("--out-dir", default="/mnt/data/focus_detection_out")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for p in args.images:
        path = Path(p)
        img = cv2.imread(str(path))
        if img is None:
            results[path.name] = {"error": "could not read"}
            continue
        cands = detect_focus(img)
        results[path.name] = [asdict(c) for c in cands]
        cv2.imwrite(str(out_dir / f"{path.stem}_focus.jpg"), annotate(img, cands))
        if cands:
            best = cands[0]
            print(f"{path.name:24s} -> {best.cue_type:18s} {best.color:6s} score={best.score:.3f} box={best.box}")
        else:
            print(f"{path.name:24s} -> no focus candidate")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
