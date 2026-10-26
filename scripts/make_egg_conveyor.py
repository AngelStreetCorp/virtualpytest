#!/usr/bin/env python3
"""Build a synthetic egg conveyor sequence from HELD-OUT dataset images, with exact ground truth (TASK-90 goal 9).

    python3 scripts/make_egg_conveyor.py --split .local-data/eggs/models/egg_good_bad.onnx.split.json \
        --out .local-data/eggs/conveyor [--eggs 40] [--fps 5] [--seed 3]

Each egg is cut out of a test-split image (the dataset photographs eggs on a black background, so the cut-out drops straight
onto a black belt) and moves left to right at a constant speed across a 1280x720 frame, one egg every `--gap` seconds, in a
seeded random order of good and bad. The first and last eggs are cut by the frame edge on purpose (they give the voting a
partial view). Writes `frames/f_%05d.jpg` and `truth.json` ({fps, frames, eggs: [{id, class, enters_t, leaves_t, source}]}).
No data from the training or validation split is used, so the classifier has never seen these eggs.
"""
import argparse
import glob
import json
import os
import random
import sys

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path[:0] = [os.path.join(ROOT, 'backend_host', 'scripts'), ROOT]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--split', required=True, help='the .split.json written by train_egg_classifier.py')
    ap.add_argument('--out', required=True)
    ap.add_argument('--eggs', type=int, default=40)
    ap.add_argument('--fps', type=float, default=5.0)
    ap.add_argument('--speed', type=float, default=160.0, help='belt speed in px/s')
    ap.add_argument('--gap', type=float, default=2.5, help='seconds between eggs entering')
    ap.add_argument('--seed', type=int, default=3)
    args = ap.parse_args()

    from monitor.analyzers.egg_detect import EggDetect
    rnd = random.Random(args.seed)
    split = json.load(open(args.split))
    # the dataset IS candling shots (a bright egg on black), so the crops are cut with the `brightness` detector
    # even when the profile runs `blob` on live footage: the detector only proposes the box, `crop_for_model` (shared
    # with the monitor) decides the pixels the model sees. With `blob` here it misses 91-97 %% of these images.
    det = EggDetect()
    pool = {cls: list(files['test']) for cls, files in split.items()}
    per = args.eggs // len(pool)
    order = [cls for cls in pool for _ in range(per)]
    rnd.shuffle(order)

    cutouts = []
    for cls in order:
        for _ in range(20):
            path = rnd.choice(pool[cls])
            img = cv2.imread(path)
            ds = det.detect(img)
            if ds:
                break
        d = max(ds, key=lambda d: d.bbox[2] * d.bbox[3])
        x, y, w, h = [int(v) for v in d.bbox]
        m = int(0.15 * max(w, h))
        crop = img[max(0, y - m):y + h + m, max(0, x - m):x + w + m]
        r = 0.7                                                    # dataset eggs are large in their photo; a belt camera sees them smaller
        crop = cv2.resize(crop, (int(crop.shape[1] * r), int(crop.shape[0] * r)), interpolation=cv2.INTER_AREA)
        cutouts.append((cls, crop, os.path.relpath(path, os.path.dirname(args.split))))

    W, H = 1280, 720
    frames_dir = os.path.join(args.out, 'frames')
    os.makedirs(frames_dir, exist_ok=True)
    for old in glob.glob(os.path.join(frames_dir, '*.jpg')):
        os.remove(old)
    total_s = (len(cutouts) - 1) * args.gap + (W + 400) / args.speed + 2
    n_frames = int(total_s * args.fps)
    truth = []
    for i, (cls, crop, src) in enumerate(cutouts):
        t0 = i * args.gap                                          # the egg's left edge is at x = -width at t0
        truth.append({'id': i + 1, 'class': cls, 'enters_t': round(t0, 2),
                      'leaves_t': round(t0 + (W + crop.shape[1]) / args.speed, 2), 'source': src})
    for f in range(n_frames):
        t = f / args.fps
        canvas = np.zeros((H, W, 3), np.uint8)
        for i, (cls, crop, _) in enumerate(cutouts):
            ch, cw = crop.shape[:2]
            x = int(-cw + (t - i * args.gap) * args.speed)
            if x >= W or x + cw <= 0:
                continue
            y = 260 + (i * 37) % 120                               # the lane wobbles a little from egg to egg
            sx0, sx1 = max(0, -x), min(cw, W - x)
            region = canvas[y:y + ch, x + sx0:x + sx1]
            region[:] = np.maximum(region, crop[:region.shape[0], sx0:sx1])
        cv2.imwrite(os.path.join(frames_dir, f'f_{f + 1:05d}.jpg'), canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])
    with open(os.path.join(args.out, 'truth.json'), 'w') as f:
        json.dump({'fps': args.fps, 'frames': n_frames, 'eggs': truth}, f, indent=1)
    print(f'{n_frames} frames, {len(cutouts)} eggs ({sum(1 for e in truth if e["class"] == list(pool)[0])} {list(pool)[0]}), {total_s:.0f} s')


if __name__ == '__main__':
    main()
