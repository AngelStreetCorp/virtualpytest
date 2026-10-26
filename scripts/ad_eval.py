#!/usr/bin/env python3
"""Score ad-break signals against hand labels, offline (TASK-90 ad-meter experiment).

    python3 scripts/ad_eval.py --data .local-data/ads --segments .local-data/ads/pi1_capture3/segments

Reads `signals.csv` (scripts/ad_signals.py) and `logo.csv` (scripts/ad_logo.py). Labels are by eye from 15 s / 30 s contact sheets
of two hours of one free-to-air channel: seconds into the hour folder, P = programme, S = self-promo / bumper / transition (not
scored), A = commercial break. Boundaries are good to about +-30 s, so windows near a boundary are not a verdict on the detector.
Prints, per signal, how well it separates A from P (AUC), then the break detector's agreement per 30 s window and per break.

    python3 scripts/ad_eval.py --segments ... --run .local-data/ads/ad_meter_run.json

scores a run of the real analyzer (scripts/ad_meter_offline.py) the same way: per 30 s window (a window is "ad" when most of its samples
are in a break; S windows and the 30 s next to a label change are not counted), per break (found / missed / invented) and boundary errors.
"""
import argparse
import csv
import os

import numpy as np

# hour folder -> [(start_s, end_s, class)]; anything not listed is P
LABELS = {
    20: [(195, 240, 'S'), (240, 600, 'A'), (600, 630, 'S'), (630, 660, 'A')],
    21: [(240, 300, 'S'), (300, 690, 'A'), (2550, 2640, 'S'), (2640, 2970, 'A'), (2970, 3000, 'S')],
    22: [(810, 870, 'S'), (1020, 1050, 'S'), (1050, 1410, 'A'), (1410, 1470, 'S')],     # used to choose the library settings (the sweep)
    23: [(30, 60, 'S'), (60, 390, 'A'), (390, 420, 'S'), (420, 450, 'A')],              # held out: labelled before any run on it, scored once
}
HELD_OUT = (23,)
WIN = 30
MARK_ABSENT = 0.25          # learned-mark score below this = mark not there
CUTS_HIGH = 6               # hard cuts per 30 s that a programme rarely reaches


def auc(pos, neg):
    pos, neg = np.array(pos), np.array(neg)
    return float(np.mean([(p > n) + 0.5 * (p == n) for p in pos for n in neg])) if len(pos) and len(neg) else float('nan')


def label_at(hour, s):
    for a, b, c in LABELS.get(hour, []):
        if a <= s < b:
            return c
    return 'P'


def load(data):
    sig = {int(r['t_epoch']): r for r in csv.DictReader(open(os.path.join(data, 'signals.csv')))}
    lg = {int(r['t_epoch']): r for r in csv.DictReader(open(os.path.join(data, 'logo.csv')))}
    return sig, lg


def window(sig, lg, t0):
    ts = [t0 + i for i in range(WIN)]
    if not all(t in sig and t in lg for t in ts):
        return None
    return {
        'cuts': sum(float(sig[t]['cuts']) for t in ts),
        'luma': float(np.mean([float(sig[t]['luma']) for t in ts])),
        'lufs': float(np.mean([float(sig[t]['lufs']) for t in ts])),
        'mark': float(np.median([float(lg[t]['top-right']) for t in ts])),
    }


def detect(wins):
    """wins: feature dicts per 30 s window (None = no data). Evidence = mark absent AND many cuts; a break opens on 1 window of
    evidence and closes after 2 windows without, and has to last at least 3 windows (90 s)."""
    ev = [bool(w) and w['mark'] < MARK_ABSENT and w['cuts'] >= CUTS_HIGH for w in wins]
    out = [False] * len(wins)
    i = 0
    while i < len(ev):
        if ev[i]:
            j = i
            quiet = 0
            while j < len(ev) and quiet < 2:
                quiet = 0 if ev[j] else quiet + 1
                j += 1
            end = j - quiet
            if end - i >= 3:
                for k in range(i, end):
                    out[k] = True
            i = j
        else:
            i += 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data')
    ap.add_argument('--segments', required=True)
    ap.add_argument('--run', help='score this ad_meter_offline.py output instead of the 30 s window detector')
    args = ap.parse_args()
    if args.run:
        return score_run(args.run, args.segments)
    if not args.data:
        ap.error('--data is required without --run')
    sig, lg = load(args.data)
    rows = []                                   # (hour, window index, class, features)
    for h in LABELS:
        t20 = int(os.path.getmtime(os.path.join(args.segments, str(h), 'chunk_10min_0.mp4'))) - 600
        wins = [window(sig, lg, t20 + k) for k in range(0, 3600, WIN)]
        det = detect(wins)
        for i, w in enumerate(wins):
            rows.append((h, i, label_at(h, i * WIN + WIN // 2), w, det[i]))
    scored = [r for r in rows if r[2] in 'AP' and r[3]]
    print(f'{len(scored)} windows of {WIN} s: {sum(r[2] == "A" for r in scored)} ad, {sum(r[2] == "P" for r in scored)} programme\n')
    for name, sign in [('cuts per 30 s', 1), ('mark score (low = ad)', -1), ('luma', 1), ('loudness (LUFS)', 1)]:
        key = {'cuts per 30 s': 'cuts', 'mark score (low = ad)': 'mark', 'luma': 'luma', 'loudness (LUFS)': 'lufs'}[name]
        a = [sign * r[3][key] for r in scored if r[2] == 'A']
        p = [sign * r[3][key] for r in scored if r[2] == 'P']
        print(f'  {name:24s} ad median {np.median([r[3][key] for r in scored if r[2] == "A"]):7.2f}   programme median '
              f'{np.median([r[3][key] for r in scored if r[2] == "P"]):7.2f}   AUC {auc(a, p):.2f}')
    for hours in [(20,), (21,), (20, 21)]:
        s = [r for r in scored if r[0] in hours]
        tp = sum(r[2] == 'A' and r[4] for r in s)
        fn = sum(r[2] == 'A' and not r[4] for r in s)
        fp = sum(r[2] == 'P' and r[4] for r in s)
        tn = sum(r[2] == 'P' and not r[4] for r in s)
        print(f'\ndetector (mark absent AND >= {CUTS_HIGH} cuts / 30 s), hour {hours}: ad windows found {tp}/{tp + fn}, '
              f'programme flagged {fp}/{fp + tn}   precision {tp / max(1, tp + fp):.0%}  recall {tp / max(1, tp + fn):.0%}')
    for h in LABELS:
        t0 = [(i * WIN, r) for i, r in enumerate(x for x in rows if x[0] == h)]
        runs, cur = [], None
        for i, r in t0:
            if r[4] and cur is None:
                cur = i
            if not r[4] and cur is not None:
                runs.append((cur, i))
                cur = None
        if cur is not None:
            runs.append((cur, 3600))
        print(f'\nhour {h}: detected breaks (s into the hour) {runs}')
        print(f'         hand-labelled breaks      {[(a, b) for a, b, c in LABELS[h] if c == "A"]}')


def score_run(path, segments):
    import json
    run = json.load(open(path))
    samples = run['samples']
    hours = sorted({int(os.path.basename(os.path.dirname(p))) for p in __import__('glob').glob(os.path.join(segments, '*', 'chunk_10min_0.mp4'))} & set(LABELS))
    tot = {'tp': 0, 'fn': 0, 'fp': 0, 'tn': 0}
    errs_ads, errs_blk = [], []
    breaks_found = breaks_missed = breaks_invented = 0
    for h in hours:
        t0 = int(os.path.getmtime(os.path.join(segments, str(h), 'chunk_10min_0.mp4'))) - 600
        in_hour = [x for x in samples if t0 <= x[0] < t0 + 3600]
        if not in_hour:
            continue
        counts = {'tp': 0, 'fn': 0, 'fp': 0, 'tn': 0}
        for k in range(0, 3600, WIN):
            win = [x for x in in_hour if t0 + k <= x[0] < t0 + k + WIN]
            if not win:
                continue
            lab = label_at(h, k + WIN // 2)
            edge = {label_at(h, k - 1), label_at(h, k + WIN)} - {lab}
            if lab == 'S' or edge:
                continue
            det = sum(1 for x in win if x[1] == 'ad') > len(win) / 2
            counts[('tp' if det else 'fn') if lab == 'A' else ('fp' if det else 'tn')] += 1
        for key in tot:
            tot[key] += counts[key]
        found = [b for b in run['breaks'] if t0 <= b['start'] < t0 + 3600]
        truth = []
        for a, b, c in LABELS[h]:
            if c == 'A':
                if truth and a - truth[-1][1] <= 90:
                    truth[-1] = (truth[-1][0], b)
                else:
                    truth.append((a, b))
        # the break as a block: its ads plus the promos and bumpers touching them (what a viewer sees as the interruption)
        blocks = []
        for a, b, c in LABELS[h]:
            if c not in 'AS':
                continue
            if blocks and a - blocks[-1][1] <= 30:
                blocks[-1] = (blocks[-1][0], b, blocks[-1][2] or c == 'A')
            else:
                blocks.append((a, b, c == 'A'))
        blocks = [(a, b) for a, b, has_ad in blocks if has_ad]
        hit = []
        for a, b in truth:
            m = [f for f in found if f['start'] - t0 < b and f['end'] - t0 > a]
            hit.append((a, b, m[0] if m else None))
        def overlap(f):
            return sum(max(0.0, min(f['end'] - t0, b) - max(f['start'] - t0, a)) for a, b in truth) / max(1.0, f['end'] - f['start'])
        invented = [f for f in found if overlap(f) < 0.5]         # under half of the piece is inside a labelled break
        tag = ' (held out)' if h in HELD_OUT else ''
        p_ = counts['tp'] / max(1, counts['tp'] + counts['fp'])
        r_ = counts['tp'] / max(1, counts['tp'] + counts['fn'])
        print(f'hour {h}{tag}: windows tp {counts["tp"]} fn {counts["fn"]} fp {counts["fp"]} tn {counts["tn"]}   precision {p_:.0%} recall {r_:.0%}')
        for a, b, m in hit:
            if m:
                blk = next(((x, y) for x, y in blocks if x <= a and y >= b), (a, b))
                print(f'   break {a}-{b}s  found {m["start"] - t0:.0f}-{m["end"] - t0:.0f}s ({m["kind"]}, {m.get("opened_by", "")})  '
                      f'vs ads: start {m["start"] - t0 - a:+.0f}s end {m["end"] - t0 - b:+.0f}s   vs block {blk[0]}-{blk[1]}s: start '
                      f'{m["start"] - t0 - blk[0]:+.0f}s end {m["end"] - t0 - blk[1]:+.0f}s')
                errs_ads.extend([abs(m['start'] - t0 - a), abs(m['end'] - t0 - b)])
                errs_blk.extend([abs(m['start'] - t0 - blk[0]), abs(m['end'] - t0 - blk[1])])
            else:
                print(f'   break {a}-{b}s  MISSED')
        for f in invented:
            print(f'   INVENTED break {f["start"] - t0:.0f}-{f["end"] - t0:.0f}s')
        breaks_found += sum(1 for _a, _b, m in hit if m)
        breaks_missed += sum(1 for _a, _b, m in hit if not m)
        breaks_invented += len(invented)
    p_ = tot['tp'] / max(1, tot['tp'] + tot['fp'])
    r_ = tot['tp'] / max(1, tot['tp'] + tot['fn'])
    print(f'all hours: windows tp {tot["tp"]} fn {tot["fn"]} fp {tot["fp"]} tn {tot["tn"]}   precision {p_:.0%} recall {r_:.0%}')
    if errs_ads:
        print(f'breaks: found {breaks_found}, missed {breaks_missed}, invented {breaks_invented}; mean boundary error {sum(errs_ads) / len(errs_ads):.0f} s '
              f'against the ads, {sum(errs_blk) / len(errs_blk):.0f} s against the break block (ads plus touching promos and bumpers)')


if __name__ == '__main__':
    main()
