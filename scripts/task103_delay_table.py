#!/usr/bin/env python3
"""TASK-103 goal 2: for delays D, how many minutes would have their captions ready in time?

Model (all numbers measured, none guessed):
  * the archiver log gives, per minute, C = "Created 1min MP4" and A = "Appended to 10min MP4" (ms);
  * content of that minute ended CONTENT_END_LAG s before C (task103_align_eval.py: video t=0 to wall time
    of the frames, stable to +-0.1 s over 10 slots), so the minute started at W0 = C - CONTENT_END_LAG - 60;
  * the transcript is ready at R = A + T, T = measured transcription time of a 1-minute file on the host
    (samples from task103_whisper_bench.py; every minute is combined with every sample);
  * a viewer D seconds behind live shows the first frame of that minute at W0 + D.
  strict   share of minutes with R <= W0 + D (the whole minute is captioned before it starts to play)
  seconds  share of the 60 s of caption time whose caption is ready when shown (a caption at offset s is
           needed at W0 + s + D; this is what a player gets if it shows what is ready)
  longest  max over minutes and samples of R - (W0 + D), clipped at 0: how long a "never play past a
           captioned minute" player would have to wait
  min_D    smallest D with strict = 100 % (max of R - W0)

  task103_delay_table.py --log archiver_capture3.log --bench pi_speed_eval.jsonl [--lag 5.05] [--delays 45 60 90 120]
"""
import argparse, datetime, json, re
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument('--log', required=True)
ap.add_argument('--bench', nargs='+', required=True, help='bench jsonl files (rows with wall_s, model, words)')
ap.add_argument('--lag', type=float, default=5.05)
ap.add_argument('--delays', nargs='+', type=float, default=[45, 60, 90, 120])
ap.add_argument('--out')
a = ap.parse_args()

TS = re.compile(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(\d{3})')


def ts(line):
    m = TS.search(line)
    return datetime.datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S').timestamp() + int(m.group(2)) / 1000


created, minutes = None, []
for ln in open(a.log):
    if 'Created 1min MP4' in ln:
        created = ts(ln)
    elif 'Appended to 10min MP4' in ln and created is not None:
        minutes.append((created, ts(ln))); created = None
cyc = np.diff([c for c, _ in minutes])
print(f'{len(minutes)} minutes; created-to-created: median {np.median(cyc):.1f} s, min {cyc.min():.1f}, max {cyc.max():.1f}; '
      f'created-to-appended: median {np.median([x - c for c, x in minutes]):.2f} s, max {max(x - c for c, x in minutes):.2f}')

samples = {}
for f in a.bench:
    for ln in open(f):
        if ln.startswith('{') and '"wall_s"' in ln:
            r = json.loads(ln)
            samples.setdefault((r['model'], r['words']), []).append(r['wall_s'])

result = {}
print('| model | words | n | T median s | T p95 s | ' + ' | '.join(f'D={int(d)}: strict / seconds / longest wait' for d in a.delays) + ' | min D |')
for (model, words), T in sorted(samples.items()):
    row, res = [], {}
    rs = np.array([(x + t) - (c - a.lag - 60) for c, x in minutes for t in T])  # R - W0
    for d in a.delays:
        late = rs - d
        strict = float(np.mean(late <= 0))
        sec = float(np.mean(np.clip(60 - np.maximum(late, 0), 0, 60) / 60))
        longest = float(max(0, late.max()))
        res[int(d)] = {'strict': strict, 'seconds': sec, 'longest_wait_s': longest}
        row.append(f'{strict:.0%} / {sec:.0%} / {longest:.0f} s')
    res['min_D'] = float(rs.max())
    result[f'{model}{"_words" if words else ""}'] = {'n': len(T), 'T_median': float(np.median(T)), 'T_p95': float(np.percentile(T, 95)), **res}
    print(f'| {model} | {words} | {len(T)} | {np.median(T):.1f} | {np.percentile(T, 95):.1f} | ' + ' | '.join(row) + f' | {rs.max():.0f} s |')
if a.out:
    json.dump(result, open(a.out, 'w'), indent=1)
