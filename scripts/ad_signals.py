#!/usr/bin/env python3
"""Per-second ad-break signals from a host's 24h review buffer (cold `segments/<hour>/chunk_10min_N.mp4`), offline.

    python3 scripts/ad_signals.py --segments .local-data/ads/pi1_capture3/segments --out .local-data/ads/signals.csv

For every 10-minute chunk, in order of the file's modification time, one ffmpeg pass reads the video (scene-change score and mean
luma per frame) and one the audio (momentary loudness, LUFS). Both are reduced to one row per second:
    t_epoch, cuts, luma, black_frac, lufs
`cuts` is how many frames of that second scored above --cut (a hard cut); `black_frac` the share of frames with luma < 20.
Chunks that are a frozen picture (a constant ~2.3 MB file: the box was off or idle) are skipped. Nothing is written to a host or the repo.
"""
import argparse
import csv
import glob
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

FROZEN_MAX_BYTES = 4_000_000       # a live 10-min chunk of this capture is ~17 MB; a frozen/black one ~2.3 MB


def video_rows(path, cut):
    """[(second, cuts, luma_sum, black, frames)] from the scene score and the luma of every frame."""
    out = subprocess.run(
        ['ffmpeg', '-v', 'error', '-i', path, '-an', '-vf', "select='gte(scene,0)',signalstats,metadata=print:key=lavfi.scene_score:file=-",
         '-f', 'null', '-'], capture_output=True, text=True).stdout
    sec = {}
    t = None
    for line in out.splitlines():
        m = re.search(r'pts_time:([0-9.]+)', line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r'lavfi\.scene_score=([0-9.]+)', line)
        if m and t is not None:
            s = sec.setdefault(int(t), [0, 0.0, 0, 0])
            s[0] += 1 if float(m.group(1)) >= cut else 0
            s[3] += 1
    return sec


def luma_rows(path):
    out = subprocess.run(
        ['ffmpeg', '-v', 'error', '-i', path, '-an', '-vf', 'signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-', '-f', 'null', '-'],
        capture_output=True, text=True).stdout
    sec = {}
    t = None
    for line in out.splitlines():
        m = re.search(r'pts_time:([0-9.]+)', line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r'YAVG=([0-9.]+)', line)
        if m and t is not None:
            s = sec.setdefault(int(t), [0.0, 0, 0])
            y = float(m.group(1))
            s[0] += y
            s[1] += 1
            s[2] += 1 if y < 20 else 0
    return sec


def audio_rows(path):
    out = subprocess.run(
        ['ffmpeg', '-v', 'error', '-i', path, '-vn', '-af', 'ebur128=metadata=1,ametadata=print:key=lavfi.r128.M:file=-', '-f', 'null', '-'],
        capture_output=True, text=True).stdout
    sec = {}
    t = None
    for line in out.splitlines():
        m = re.search(r'pts_time:([0-9.]+)', line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r'lavfi\.r128\.M=(-?[0-9.]+)', line)
        if m and t is not None:
            sec.setdefault(int(t), []).append(float(m.group(1)))
    return {k: sum(v) / len(v) for k, v in sec.items()}


def one(path, cut):
    sc = video_rows(path, cut)
    lu = luma_rows(path)
    au = audio_rows(path)
    start = os.path.getmtime(path) - 600          # the file is closed when its 10 minutes are over
    rows = []
    for s in range(600):
        if s not in lu:
            continue
        luma_sum, n, black = lu[s]
        rows.append((round(start + s), sc.get(s, [0])[0], round(luma_sum / n, 1), round(black / n, 2), round(au.get(s, -70.0), 1)))
    return path, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--segments', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--cut', type=float, default=0.30, help='scene score that counts as a hard cut')
    ap.add_argument('--jobs', type=int, default=4)
    args = ap.parse_args()
    paths = []
    for p in glob.glob(os.path.join(args.segments, '*', 'chunk_10min_*.mp4')):
        try:                                       # a file may be replaced while the buffer is still being copied
            if os.path.getsize(p) > FROZEN_MAX_BYTES:
                paths.append((os.path.getmtime(p), p))
        except OSError:
            pass
    paths = [p for _, p in sorted(paths)]
    print(f'{len(paths)} live chunks', file=sys.stderr)
    with ThreadPoolExecutor(args.jobs) as ex, open(args.out, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['t_epoch', 'cuts', 'luma', 'black_frac', 'lufs'])
        for i, (path, rows) in enumerate(ex.map(lambda p: one(p, args.cut), paths)):
            w.writerows(rows)
            f.flush()
            print(f'[{i + 1}/{len(paths)}] {os.path.relpath(path, args.segments)} {len(rows)} s', file=sys.stderr)


if __name__ == '__main__':
    main()
