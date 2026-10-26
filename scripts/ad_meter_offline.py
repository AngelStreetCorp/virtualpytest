#!/usr/bin/env python3
"""Run the ad_meter analyzer over a host's 24h review buffer offline, at the sample rate a host would use (TASK-90 goal 10).

    python3 scripts/ad_meter_offline.py --segments .local-data/ads/pi1_capture3/segments --out .local-data/ads/ad_meter_run.json \
        [--hours 20,21,22] [--library-dir .local-data/ads/lib] [--set cuts_per_30s=8]

Chunks are read in the order of their file times (cold chunks of 10 minutes, 320x180 here), decoded at the profile's sample_hz, and every
sample is handed to AdMeterAnalyzer.process_frame with the stream's own timestamp. Frozen-picture chunks (a constant ~2.3 MB) are skipped
and the learner is told the channel was lost. Writes the closed breaks, the per-sample state and the final KPIs (JSON). Nothing goes to a host.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path[:0] = [os.path.join(ROOT, 'backend_host', 'scripts'), ROOT]

FROZEN_MAX_BYTES = 4_000_000


def chunks(segments, hours):
    out = []
    for p in glob.glob(os.path.join(segments, '*', 'chunk_10min_*.mp4')):
        try:
            if os.path.getsize(p) <= FROZEN_MAX_BYTES:
                continue
            if hours and int(os.path.basename(os.path.dirname(p))) not in hours:
                continue
            out.append((os.path.getmtime(p) - 600, p))
        except OSError:
            pass
    return sorted(out)


def decode(path, fps):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-an', '-vf', f'fps={fps:g}', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                         capture_output=True).stdout
    shape = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0:s=x', path],
                           capture_output=True, text=True).stdout.strip().split('x')
    w, h = int(shape[0]), int(shape[1])
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--segments', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--profile', default='ad_meter')
    ap.add_argument('--hours', help='comma list of hour folders to run (default: all live chunks)')
    ap.add_argument('--library-dir', help='where ad_library.json lives (default: none, the library stays in memory)')
    ap.add_argument('--snapshot-at', help='comma list of epoch seconds: save the analyzer result and the frame at the first sample at or after each')
    ap.add_argument('--snapshot-dir', help='where the snapshots go (snap_<epoch>.json and .jpg)')
    ap.add_argument('--not-ad', action='append', default=[], metavar='BREAK_ID', help='after the run, mark this break (id in ad_breaks.jsonl) as not an ad')
    ap.add_argument('--set', action='append', default=[], metavar='KEY=VALUE', help='override an analyzer setting')
    args = ap.parse_args()

    from monitor.analyzers.ad_meter import AdMeterAnalyzer
    from monitor.profiles import load_profile
    profile = load_profile(args.profile)
    for kv in args.set:
        k, _, v = kv.partition('=')
        profile.img.analyzers[0].__pydantic_extra__[k] = json.loads(v)
    if args.library_dir:
        os.makedirs(args.library_dir, exist_ok=True)
    a = AdMeterAnalyzer(None, profile, library_dir_fn=(lambda f: args.library_dir) if args.library_dir else None)
    if not args.library_dir:
        a.p['library'] = True
    a.register_device('offline')
    hours = {int(x) for x in args.hours.split(',')} if args.hours else None
    breaks, samples, ms = [], [], []
    last_end = None
    orig_close = a._close

    def logged_close(dev, end):
        fin = orig_close(dev, end)
        for f in fin:
            breaks.append({'start': f['span'][0], 'end': f['span'][1], 'kind': f['attrs']['kind']})
        return fin
    a._close = logged_close
    snaps = sorted(float(x) for x in args.snapshot_at.split(',')) if args.snapshot_at else []
    if snaps:
        import cv2
        os.makedirs(args.snapshot_dir, exist_ok=True)
    for start, path in chunks(args.segments, hours):
        if last_end is not None and start - last_end > 120:          # a gap: the box was idle, the channel may have changed
            a.reset_mark('offline')
        frames = decode(path, a.sample_hz)
        for i, f in enumerate(frames):
            ts = start + i / a.sample_hz
            t0 = time.perf_counter()
            r = a.process_frame('offline', f, ts)
            ms.append((time.perf_counter() - t0) * 1000)
            if snaps and ts >= snaps[0]:
                name = os.path.join(args.snapshot_dir, f'snap_{int(snaps.pop(0))}')
                json.dump(r, open(name + '.json', 'w'))
                cv2.imwrite(name + '.jpg', f)
            samples.append([round(ts, 1), r['ad']['state'], r['ad']['mark'], r['ad']['cuts_30s'], r['ad']['corner']])
        last_end = start + 600
    tail = a.settle('offline', last_end + 1)
    for bid in args.not_ad:
        print('mark_not_ad', bid, a.mark_not_ad('offline', bid))
    summary = {'samples': len(samples), 'breaks': len(breaks), 'ms_per_sample_mean': round(float(np.mean(ms)), 1),
               'ms_per_sample_p99': round(float(np.percentile(ms, 99)), 1), 'kpis_end': tail['kpis'], 'sample_hz': a.sample_hz}
    print(json.dumps(summary, indent=1))
    with open(args.out, 'w') as f:
        json.dump({'summary': summary, 'breaks': breaks, 'samples': samples}, f)


if __name__ == '__main__':
    main()
