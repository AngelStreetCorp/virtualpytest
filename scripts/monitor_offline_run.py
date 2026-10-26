#!/usr/bin/env python3
"""Run a monitor profile (counting_cars, ...) offline over a folder of frames, the way vpt-monitor-img would at its sample rate.

    python3 scripts/monitor_offline_run.py --profile counting_cars --frames /tmp/clip_frames --fps 5 \
        --model /path/to/yolox_nano.onnx --out /tmp/run.json [--algo ocsort] [--votes 3 --min-votes 2]

Frames are `*.jpg` sorted by name, `--fps` apart (the capture rate, 5 on a host). The detector runs every 1/sample_hz seconds
of that clock, like the host. Nothing is written to a host or the repo. Prints a summary and writes the per-sample observations
and the final KPIs to --out (JSON) so a run can be compared with a hand count (TASK-90 §6).
"""
import argparse
import glob
import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path[:0] = [os.path.join(ROOT, 'backend_host', 'scripts'), ROOT]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--profile', default='counting_cars')
    ap.add_argument('--frames', required=True)
    ap.add_argument('--fps', type=float, default=5.0)
    ap.add_argument('--model', help='sets MONITOR_COCO_MODEL')
    ap.add_argument('--env', action='append', default=[], metavar='KEY=VALUE', help='more environment, e.g. MONITOR_EGG_MODEL=...')
    ap.add_argument('--focus-dir', help='where the "last checked" crops go (default: none written)')
    ap.add_argument('--out')
    ap.add_argument('--algo', choices=['iou', 'ocsort'])
    ap.add_argument('--min-iou', type=float)
    ap.add_argument('--votes', type=int)
    ap.add_argument('--min-votes', type=int)
    ap.add_argument('--start', type=float, default=0.0, help='seconds into the frame list to start at')
    ap.add_argument('--seconds', type=float, help='only this many seconds')
    args = ap.parse_args()
    if args.model:
        os.environ['MONITOR_COCO_MODEL'] = args.model
    for kv in args.env:
        k, _, v = kv.partition('=')
        os.environ[k] = v

    import psutil
    from monitor.analyzers.pipeline import PipelineAnalyzer
    from monitor.profiles import load_profile

    proc = psutil.Process()
    rss_before = proc.memory_info().rss / 1e6
    profile = load_profile(args.profile)
    if profile.img.track is None:
        raise SystemExit('this profile has no img.track')
    if args.algo:
        profile.img.track.algo = args.algo
    if args.min_iou:
        profile.img.track.min_iou = args.min_iou
    if args.votes:
        profile.img.track.votes = args.votes
        profile.img.track.min_votes = args.min_votes or args.votes
    elif args.min_votes:
        profile.img.track.min_votes = args.min_votes
    a = PipelineAnalyzer(core=None, profile=profile)
    a.register_device('offline')
    if args.focus_dir:
        a.focus_dir_fn = lambda folder: args.focus_dir
    verdicts = []                      # one per track: the verdicts the events are made from
    _orig_finalize = a._finalize

    def _logged(track, left=False):
        v = _orig_finalize(track, left)
        verdicts.append(dict(v, first=track.first_seen, last=track.last_seen, samples=track.hits, votes=track.n_votes))
        return v
    a._finalize = _logged

    frames = sorted(glob.glob(os.path.join(args.frames, '*.jpg')))
    first = int(args.start * args.fps)
    last = len(frames) if args.seconds is None else min(len(frames), first + int(args.seconds * args.fps))
    frames = frames[first:last]
    period = 1.0 / a.sample_hz
    next_t = 0.0
    samples, tracks, ms = [], {}, []
    rss_peak = rss_before
    for i, path in enumerate(frames):
        t = i / args.fps
        if t + 1e-9 < next_t:
            continue
        next_t = t + period
        t0 = time.perf_counter()
        r = a.process('offline', path, t)
        ms.append((time.perf_counter() - t0) * 1000)
        rss_peak = max(rss_peak, proc.memory_info().rss / 1e6)
        # the whole result of the sample (observations, events, kpis, incidents, ui, focus): what the monitor writes into the frame JSON
        samples.append({'t': round(t, 2), 'frame': os.path.basename(path), 'observations': r['observations'], 'kpis': r['kpis'], 'result': r})
        for o in r['observations']:
            tr = tracks.setdefault(o['track_id'], {'id': o['track_id'], 'first': t, 'last': t, 'label': o['label'], 'samples': 0})
            tr['last'], tr['samples'], tr['attrs'], tr['votes'] = t, tr['samples'] + 1, o['attrs'], o.get('votes')
    # settle tracks still open at the end of the clip: one more update far in the future ends them (like the track leaving)
    tail = a.settle('offline', (len(frames) / args.fps) + 3600)
    final_kpis = tail['kpis']
    from collections import Counter
    dist = Counter(str(v['attrs'].get(next(iter(v['attrs']), ''), '')) for v in verdicts) if verdicts else Counter()
    one_sample = sum(1 for v in verdicts if v['samples'] <= 1)
    span_s = len(frames) / args.fps
    st = a._state['offline']['tracker']
    summary = {
        'profile': args.profile, 'algo': st.algo, 'votes': a.votes, 'min_votes': a.min_votes, 'sample_hz': a.sample_hz,
        'frames': len(frames), 'clip_seconds': round(span_s, 1), 'samples': len(samples),
        'tracks_opened': st._next_id - 1, 'tracks_per_min': round((st._next_id - 1) / (span_s / 60), 2),
        'tracks_counted': len(verdicts), 'counted_per_min': round(len(verdicts) / (span_s / 60), 2),
        'colour_distribution': dict(dist), 'counted_with_one_sample_only': one_sample,
        'verdicts_unverified': sum(1 for v in verdicts if 'unverified' in v['attrs'].values()), 'ms_per_sample_mean': round(sum(ms) / max(1, len(ms)), 1),
        'rss_before_mb': round(rss_before, 1), 'rss_peak_mb': round(rss_peak, 1), 'rss_added_mb': round(rss_peak - rss_before, 1),
    }
    print(json.dumps(summary, indent=1))
    if args.out:
        with open(args.out, 'w') as f:
            json.dump({'summary': summary, 'verdicts': verdicts, 'tracks': sorted(tracks.values(), key=lambda x: x['id']), 'samples': samples}, f)


if __name__ == '__main__':
    main()
