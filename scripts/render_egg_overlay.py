#!/usr/bin/env python3
"""Draw the real egg_quality overlay on a clip: one box per egg, the votes badge, and the counter.

Runs the shipped profile's own analyzers (the blob detector and the OC-SORT tracker) frame by frame and paints what
ProfileOverlay would paint in the stream modal, so the result can be checked without the host.

    python3 scripts/render_egg_overlay.py --video clip.mp4 --model egg_good_bad.onnx --out overlay.mp4
"""
import argparse
import os
import sys
import tempfile

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path[:0] = [os.path.join(ROOT, 'backend_host', 'scripts'), ROOT]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--video', required=True)
    ap.add_argument('--model', help='MONITOR_EGG_MODEL: without it the good/bad verdict is skipped, the boxes still draw')
    ap.add_argument('--profile', default='egg_quality')
    ap.add_argument('--sample-hz', type=float, default=4.0)
    ap.add_argument('--out', required=True)
    ap.add_argument('--every-s', type=float, help='restart the counter every N seconds, as `img.reset_counters.every_s` does')
    args = ap.parse_args()

    if args.model:
        os.environ['MONITOR_EGG_MODEL'] = os.path.abspath(args.model)
    from monitor import profiles as P
    from monitor.analyzers.pipeline import PipelineAnalyzer
    from monitor.tracking import make_tracker

    prof = P.load_profile(args.profile)
    prof.img.analyzers[0].sample_hz = args.sample_hz
    analyzer = PipelineAnalyzer(core=None, profile=prof)
    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    out = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))

    tracker = make_tracker(analyzer._algo, **analyzer._track_cfg)
    tmp = tempfile.mkdtemp()
    frame_path = os.path.join(tmp, 'f.jpg')
    counts, seen, ts, every_at = {}, 0, 0.0, None
    step = 1.0 / args.sample_hz
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        ts += 1.0 / fps
        cv2.imwrite(frame_path, frame)
        if every_at is not None and ts >= every_at:            # the loop of a videofile device starts again
            every_at = ts + args.every_s
            tracker = make_tracker(analyzer._algo, **analyzer._track_cfg)
            counts.clear()
        dets = analyzer.detector.detect(frame)
        matched = tracker.update([(d.label, d.bbox) for d in dets], ts)
        for di, track, is_new in matched:
            if track.n_votes < analyzer.votes:
                analyzer._vote(track, frame, dets[di])
            if track.n_votes >= analyzer.votes and not track.finalized:
                key = track.attrs.get(analyzer.primary) or 'unverified'
                counts[key] = counts.get(key, 0) + 1
                track.finalized = True
        for di, track, is_new in matched:
            d = dets[di]
            shape = getattr(d, 'shape', None) or {}
            ellipse = shape.get('ellipse')
            (cx, cy, ax, ay, ang) = ellipse if ellipse else (d.bbox[0] + d.bbox[2] / 2, d.bbox[1] + d.bbox[3] / 2,
                                                            d.bbox[2], d.bbox[3], 0)
            colour = (0, 235, 90) if track.attrs.get(analyzer.primary) == 'good' else \
                     (60, 60, 245) if track.attrs.get(analyzer.primary) == 'bad' else (0, 200, 255)
            cv2.ellipse(frame, (int(cx), int(cy)), (max(2, int(ax / 2)), max(2, int(ay / 2))), ang, 0, 360, colour, 2)
            badge = f"{min(track.n_votes, analyzer.votes)}/{analyzer.votes}"
            cv2.putText(frame, badge, (int(cx - ax / 2), int(cy - ay / 2) - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, colour, 1)
        for track in tracker.pop_ended():
            track.finalized = True
        total = sum(counts.values())
        cv2.rectangle(frame, (0, 0), (430, 40 + 26 * len(counts)), (0, 0, 0), -1)
        cv2.putText(frame, prof.ui.title if prof.ui else 'Egg quality control', (16, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame, f"{total} eggs inspected", (300, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 235, 90), 2)
        for i, (k, v) in enumerate(sorted(counts.items())):
            cv2.putText(frame, f"{k}: {v}", (300, 28 + 26 * (i + 1)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        out.write(frame)
        idx += 1
    out.release()
    print(f"{args.out}: {idx} frames, {sum(counts.values())} eggs counted, verdicts {counts}")


if __name__ == '__main__':
    main()