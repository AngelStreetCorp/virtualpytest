#!/usr/bin/env python3
"""TASK-103 goal 3: score caption-start methods against the broadcaster subtitles read from the frames.

Inputs (all under --run, produced by task103_collect.py / task103_subtitle_ref.py / task103_whisper_bench.py):
  video/<mtime>_1min_N.mp4        1-minute video+audio, the timebase of the audio the transcriber hears
  frames/capture_*.jpg            1280x720 frames, wall time = file mtime (ns)
  subtitle_events.json            subtitle events {start,end,text} in frame wall time
  --dump DIR                      whisper dumps per slot: <model>[_w]_<mtime>_1min_N.mp3.json

Steps
 1. Wall -> video time. Per slot, the luminance series of the video (10 fps) is cross-correlated with the
    luminance series of the frames, giving W0 = wall time of video t=0 (peak sharpness reported).
 2. Each subtitle event gets a video-time start. Events within 2 s of a slot edge are dropped.
 3. For every method the predicted start of the words of the subtitle is looked up (fuzzy text match inside
    +-6 s) and compared with the subtitle start: signed error = predicted - subtitle.
Methods: prop (sentence timestamps, characters split proportionally: what the accumulator gives today),
words (faster-whisper word_timestamps), fa (CTC forced alignment, only if --fa-dump given: JSON per slot
produced by task103_forced_align.py).
Output: a table (n, median |err|, p90 |err|, median signed err) per method and model, JSON to --out.
"""
import argparse, difflib, glob, json, os, re, sys
import cv2, numpy as np


def norm_tok(w):
    return re.sub(r'[^a-zäöüß0-9]', '', w.lower())


def luminance_frames(files):
    out = []
    for f in files:
        g = cv2.imread(f, cv2.IMREAD_REDUCED_GRAYSCALE_8)
        out.append(float(g.mean()) if g is not None else np.nan)
    return np.array(out)


def video_luminance(path):
    cap = cv2.VideoCapture(path); lum = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        lum.append(float(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).mean()))
    return np.array(lum), cap.get(cv2.CAP_PROP_FPS) or 10.0


def hp(x):  # high-pass: the change of luminance (cuts, flashes)
    d = np.abs(np.diff(x, prepend=x[0]))
    return (d - d.mean()) / (d.std() + 1e-9)


def map_slot(vpath, ft, fl, fps_grid=20.0, max_lag=12.0):
    """Return (W0, sharpness): wall time of video t=0."""
    vl, fps = video_luminance(vpath)
    dur = len(vl) / fps
    mt = float(os.path.basename(vpath).split('_')[0])
    best = None
    grid_v = np.arange(0, dur, 1 / fps_grid)
    vs = hp(np.interp(grid_v, np.arange(len(vl)) / fps, vl))
    scores = []
    lags = np.arange(-max_lag, max_lag, 1 / fps_grid)
    for lag in lags:  # W0 = mt - dur + lag
        w0 = mt - dur + lag
        tq = w0 + grid_v
        if tq[0] < ft[0] or tq[-1] > ft[-1]:
            scores.append(-9); continue
        fs = hp(np.interp(tq, ft, fl))
        scores.append(float(np.mean(vs * fs)))
    scores = np.array(scores)
    i = int(np.argmax(scores))
    second = np.max(np.r_[scores[:max(0, i - 4)], scores[i + 5:]]) if len(scores) > 10 else 0
    return mt - dur + lags[i], float(scores[i]), float(second)


def tokens_prop(segs):
    """Today: sentence segment [start,end], tokens placed by character position."""
    out = []
    for s in segs:
        words = s['text'].split()
        tot = max(1, len(s['text']))
        pos = 0
        for w in words:
            out.append((norm_tok(w), s['start'] + (pos / tot) * (s['end'] - s['start'])))
            pos += len(w) + 1
    return [(w, t) for w, t in out if w]


def tokens_words(segs):
    return [(norm_tok(w['word']), w['start']) for s in segs for w in s['words'] if norm_tok(w['word'])]


def match(ev_tokens, toks, t_sub, win=6.0):
    """Best window of toks (list of (word, time)) for the subtitle tokens; returns (time of first word, ratio)."""
    n = len(ev_tokens); best = (0, None)
    target = ' '.join(ev_tokens)
    for i in range(len(toks)):
        if abs(toks[i][1] - t_sub) > win:
            continue
        for L in (n - 1, n, n + 1):
            if L < 1 or i + L > len(toks):
                continue
            r = difflib.SequenceMatcher(None, target, ' '.join(w for w, _ in toks[i:i + L])).ratio()
            if r > best[0]:
                best = (r, toks[i][1])
    return best[1], best[0]


def pct(x, q):
    return float(np.percentile(x, q)) if len(x) else float('nan')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--events', required=True)
    ap.add_argument('--dump', required=True)
    ap.add_argument('--fa-dump')
    ap.add_argument('--t-min', type=float, default=0)
    ap.add_argument('--t-max', type=float, default=1e18)
    ap.add_argument('--min-ratio', type=float, default=0.75)
    ap.add_argument('--min-tokens', type=int, default=3, help='subtitles with fewer words are too ambiguous to match')
    ap.add_argument('--min-peak', type=float, default=0.5, help='drop slots whose time mapping correlation is weaker')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    frames = sorted(glob.glob(f'{a.run}/frames/capture_*.jpg'))
    ft = np.array([os.stat(f).st_mtime for f in frames])
    cache = f'{a.run}/frame_lum.npy'
    if os.path.exists(cache) and np.load(cache).shape[0] == len(frames):
        fl = np.load(cache)
    else:
        fl = luminance_frames(frames); np.save(cache, fl)
    ev = [e for e in json.load(open(a.events))['events'] if a.t_min <= e['start'] <= a.t_max]

    slots = []
    for v in sorted(glob.glob(f'{a.run}/video/*_1min_*.mp4')):
        mt = float(os.path.basename(v).split('_')[0])
        if not (a.t_min - 70 <= mt <= a.t_max + 70):
            continue
        w0, sc, sc2 = map_slot(v, ft, fl)
        slots.append({'video': v, 'mt': mt, 'w0': w0, 'score': sc, 'second': sc2, 'name': os.path.basename(v)})
        print(f"slot {os.path.basename(v)} W0-(mt-60)={w0 - (mt - 60):+.2f}s peak={sc:.2f} second={sc2:.2f}", file=sys.stderr)

    rows = {}  # method -> list of dicts
    for s in slots:
        if s['score'] < a.min_peak:
            continue
        n = s['name'].split('_1min_')[1].split('.')[0]  # slot number
        # pair with the mp3 slot of the same number written within 8 s
        cands = [p for p in glob.glob(f'{a.run}/audio/*_1min_{n}.mp3') if abs(float(os.path.basename(p).split('_')[0]) - s['mt']) < 8]
        if not cands:
            continue
        mp3name = os.path.basename(cands[0])
        for ev_ in ev:
            tv = ev_['start'] - s['w0']
            if not (2 <= tv <= 58):
                continue
            etoks = [norm_tok(w) for w in ev_['text'].split()]
            etoks = [w for w in etoks if len(w) >= 2]
            if len(etoks) < a.min_tokens:
                continue
            for model in ('tiny', 'base'):
                for kind in ('prop', 'words', 'fa'):
                    if kind == 'prop':
                        f = f'{a.dump}/{model}_{mp3name}.json'
                    elif kind == 'words':
                        f = f'{a.dump}/{model}_w_{mp3name}.json'
                    else:
                        if not a.fa_dump:
                            continue
                        f = f'{a.fa_dump}/{model}_{mp3name}.json'
                    if not os.path.exists(f):
                        continue
                    d = json.load(open(f))
                    toks = tokens_prop(d['segments']) if kind == 'prop' else (tokens_words(d['segments']) if kind == 'words'
                           else [(norm_tok(w['word']), w['start']) for w in d['words'] if norm_tok(w['word'])])
                    t, r = match(etoks, toks, tv)
                    if t is not None and r >= a.min_ratio:
                        rows.setdefault(f'{kind}_{model}', []).append({'slot': s['name'], 'sub_t': tv, 'pred': t, 'err': t - tv, 'ratio': r, 'text': ev_['text']})
    # fair comparison: per model only subtitles matched by every method of that model
    summary = {}
    for model in ('tiny', 'base'):
        keys = [k for k in rows if k.endswith('_' + model)]
        if not keys:
            continue
        common = set.intersection(*[{(r['slot'], round(r['sub_t'], 2)) for r in rows[k]} for k in keys])
        for k in sorted(keys):
            errs = np.array([r['err'] for r in rows[k] if (r['slot'], round(r['sub_t'], 2)) in common])
            allerr = np.array([r['err'] for r in rows[k]])
            summary[k] = {'n_common': len(errs), 'n_all': len(allerr),
                          'median_abs': float(np.median(np.abs(errs))) if len(errs) else None,
                          'p90_abs': pct(np.abs(errs), 90), 'median_signed': float(np.median(errs)) if len(errs) else None,
                          'median_abs_debiased': float(np.median(np.abs(errs - np.median(errs)))) if len(errs) else None,
                          'p90_abs_debiased': pct(np.abs(errs - np.median(errs)), 90) if len(errs) else None,
                          'median_abs_all': float(np.median(np.abs(allerr))) if len(allerr) else None,
                          'p90_abs_all': pct(np.abs(allerr), 90)}
    json.dump({'slots': slots, 'summary': summary, 'rows': rows}, open(a.out, 'w'), indent=1, ensure_ascii=False)
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
