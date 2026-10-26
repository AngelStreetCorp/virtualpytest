#!/usr/bin/env python3
"""Learn a channel's on-screen mark (logo bug) from its own 24h review buffer, then score every frame by "is the mark there".

    python3 scripts/ad_logo.py --segments .local-data/ads/pi1_capture3/segments --out .local-data/ads/logo.csv

The mark is whatever stays put in a corner while the picture changes: the per-pixel MEDIAN over many frames keeps it and
averages the content away, so no template is drawn by hand and it works for any channel. Per corner the median patch is
high-passed (the mark is small and sharp) and the frame's own high-passed patch is correlated with it (zero-mean NCC);
the score per corner is written, one row per second: t_epoch, top-left, top-right, bottom-left, bottom-right (-1..1, high = mark present).
Chunks that are a frozen picture (a constant ~2.3 MB file) are skipped, like in ad_signals.py. Writes nothing to a host or the repo.
"""
import argparse
import csv
import glob
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

FROZEN_MAX_BYTES = 4_000_000
W, H = 320, 180
PW, PH = 64, 32                      # corner patch
CORNERS = {'top-left': (0, 0), 'top-right': (W - PW, 0), 'bottom-left': (0, H - PH), 'bottom-right': (W - PW, H - PH)}
FPS = 2


def decode(path):
    """(n, 4, PH, PW) uint8: the four corner patches of every frame at FPS."""
    out = []
    for name, (x, y) in CORNERS.items():
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-an', '-vf', f'fps={FPS},crop={PW}:{PH}:{x}:{y},format=gray',
                              '-f', 'rawvideo', '-'], capture_output=True).stdout
        out.append(np.frombuffer(raw, np.uint8).reshape(-1, PH, PW))
    n = min(len(o) for o in out)
    return np.stack([o[:n] for o in out], axis=1)


def highpass(a):
    """a - 5x5 box blur, over the last two axes."""
    k = 5
    p = np.pad(a.astype(np.float32), [(0, 0)] * (a.ndim - 2) + [(k // 2, k // 2)] * 2, mode='edge')
    blur = sum(p[..., i:i + a.shape[-2], j:j + a.shape[-1]] for i in range(k) for j in range(k)) / (k * k)
    return a - blur


def ncc(frames_hp, tmpl_hp):
    """zero-mean normalised correlation of every frame patch with the template patch."""
    f = frames_hp.reshape(len(frames_hp), -1)
    f = f - f.mean(1, keepdims=True)
    t = tmpl_hp.reshape(-1)
    t = t - t.mean()
    return (f @ t) / (np.linalg.norm(f, axis=1) * np.linalg.norm(t) + 1e-6)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--segments', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--jobs', type=int, default=4)
    args = ap.parse_args()
    paths = []
    for p in glob.glob(os.path.join(args.segments, '*', 'chunk_10min_*.mp4')):
        try:
            if os.path.getsize(p) > FROZEN_MAX_BYTES:
                paths.append((os.path.getmtime(p), p))
        except OSError:
            pass
    paths = [p for _, p in sorted(paths)]
    print(f'{len(paths)} live chunks', file=sys.stderr)
    with ThreadPoolExecutor(args.jobs) as ex:
        chunks = list(ex.map(decode, paths))
    frames = np.concatenate(chunks)                                  # (N, 4, PH, PW)
    starts = np.concatenate([np.full(len(c), os.path.getmtime(p) - 600) + np.arange(len(c)) / FPS for c, p in zip(chunks, paths)])
    print(f'{len(frames)} frames', file=sys.stderr)
    scores, shares = [], []
    for ci, name in enumerate(CORNERS):
        sub = frames[::7, ci]                                        # a spread of frames is enough for the median
        tmpl = highpass(np.median(sub, axis=0)[None])[0]
        scores.append(ncc(highpass(frames[:, ci]), tmpl))
        print(f'{name:13s} template contrast {np.std(tmpl):5.2f}   frames matching {(scores[-1] > 0.5).mean():5.1%}', file=sys.stderr)
        np.save(os.path.splitext(args.out)[0] + f'_{name}.npy', tmpl)
    with open(args.out, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['t_epoch'] + list(CORNERS))
        t0 = np.floor(starts).astype(int)
        for sec in np.unique(t0):
            m = t0 == sec
            w.writerow([int(sec)] + [round(float(np.mean(sc[m])), 3) for sc in scores])


if __name__ == '__main__':
    main()
