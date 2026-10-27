#!/usr/bin/env python3
"""How much of the abstain population can we classify with the code we ALREADY have?

The question is not "should we build a model" but "what do we answer today, and what
is left over". This runs the EXISTING detectors -- no new logic -- over the real frames
that abstained, and reports which now get an answer.

It imports production code rather than reimplementing it:
  classify_special_state()  image_helpers   -> blackscreen | no_signal
  screen_state_cv.screen_state()            -> loaded / overlay / playback / error
  freeze_facts.compare()                    -> the temporal signal loaded/playback need
  freeze_facts.ocr()                        -> the token stream error() consumes

Frames are read in CONTIGUOUS windows so `changed_pct` is a real adjacent-frame
series, which is what `loaded()` and `playback()` are specified against. Passing a
single synthetic value (or none) makes both return 'unknown' and understates
coverage -- so it is computed, not faked.

For each frame, in order:
  1. does the capture hardware explain it?          classify_special_state
  2. is content moving / is this a media screen?    playback
  3. is a dialog / keyboard / toast raised over it? overlay
  4. is there a word meaning "something failed"?   error, via real OCR
  5. only then RESIDUE -- the part needing a node capture or something unbuilt.

Read-only. Writes one JSON report.
"""
import argparse
import collections
import glob
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.environ.get('VIRTUALPYTEST_REPO') or os.path.abspath(
    os.path.join(_HERE, '..', '..', '..', '..'))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import cv2
import numpy as np

from backend_host.src.controllers.verification.image_helpers import ImageHelpers
from shared.src.lib.ai import freeze_facts
from shared.src.lib.ai import screen_state_cv as ssc

# 'none' / 'unknown' / 'not_applicable' are the detectors' own abstentions. Only a
# POSITIVE name counts as "answered".
ABSTAIN_WORDS = ('none', 'unknown', 'no', 'not_applicable', 'still', '')
POSITIVE = {
    'special': lambda v: v not in ('none',) and v,
    'playback': lambda v: v in ('playing', 'paused'),
    'overlay': lambda v: v in ('dialog', 'keyboard', 'notification', 'tooltip', 'popup'),
    'error': lambda v: v == 'visible',
    'loaded': lambda v: v == 'loaded',
}
ORDER = ('special', 'playback', 'overlay', 'error', 'loaded')

# A frame this plain is CONTENT, not UI: the broadcast bugelogo corner is a dead
# giveaway and it is what tells a held promo slate from a static screen.
BUGELOG_BOX = (0.00, 0.60, 0.30, 1.00)          # x0, y0, x1, y1 as fractions


def windowed_pairs(imgs):
    """Real adjacent-frame changed_pct per frame (freeze_facts.compare, detector's units).

    `compare()` does its own blur + BGR->grey + label-corner mask, so it takes the
    colour frames as-is. Handing it a pre-converted grey frame is a channel-count error.
    """
    out = []
    prev = None
    for im in imgs:
        if im is None:
            out.append(None)
            prev = None
            continue
        try:
            out.append(None if prev is None else freeze_facts.compare(prev, im)['changed_pct'])
        except Exception:
            out.append(None)
        prev = im
    return out


def ocr_tokens(path):
    try:
        text = freeze_facts.ocr(cv2.imread(path))
    except Exception:
        return None
    return [w for w in text.split() if w] if text else None


def classify_one(helpers, path, img, hist, fut):
    special = helpers.classify_special_state(img)
    st = ssc.screen_state(
        frame_bgr=img,
        is_media=None,
        changed_pct=(hist + [None] + fut) if (hist or fut) else None,
        tokens=ocr_tokens(path),
    )
    answers = {'special': special or 'none', 'loaded': st['loaded'],
               'overlay': st['overlay'], 'playback': st['playback'],
               'error': st['error']}
    c = freeze_facts.content(img)
    answers['edge_pct'] = round(c['edge_pct'], 1)
    answers['brightness'] = c['brightness']
    h, w = img.shape[:2]
    corner = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[int(h * BUGELOG_BOX[1]):int(h * BUGELOG_BOX[3]),
                                                  int(w * BUGELOG_BOX[0]):int(w * BUGELOG_BOX[2])]
    answers['corner_sat'] = round(float(corner[:, :, 1].mean()), 1)
    answers['bugelogo_like'] = bool(answers['corner_sat'] > 60.0)
    return answers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--capture', action='append', default=[])
    ap.add_argument('--windows', type=int, default=12)
    ap.add_argument('--per-window', type=int, default=20)
    ap.add_argument('--ui', default=os.environ.get('VPT_LOCALIZE_UI'), required='VPT_LOCALIZE_UI' not in os.environ)
    ap.add_argument('--out', default='/tmp/coverage.json')
    args = ap.parse_args()

    def load_h():
        import importlib.util
        p = os.environ.get('ABSTAIN_HISTOGRAM', '/tmp/abstain_histogram.py')
        spec = importlib.util.spec_from_file_location('abstain_histogram', p)
        m = importlib.util.module_from_spec(spec)
        sys.modules['abstain_histogram'] = m
        spec.loader.exec_module(m)
        return m

    H = load_h()
    ImageHelpers, origin = H.load_image_helpers()
    node_fps = H.load_node_fps_from_db(args.ui)
    helpers = ImageHelpers(None, None)
    print('matcher:', origin, flush=True)

    def windows(paths, n, per):
        by, order = {}, []
        for p in paths:
            d = os.path.dirname(p)
            if 'motion_crop' in os.path.basename(p) or 'text_source_image' in os.path.basename(p):
                continue
            by.setdefault(d, []).append(p)
            if d not in order:
                order.append(d)
        stride = max(1, len(order) // max(1, n))
        return [by[d][:per] for d in order[::stride][:n] if len(by[d]) >= 2]

    rows, abstain_rows = [], []
    for cap in args.capture:
        allf = H.find_frames(cap, 'cold')
        for win in windows(allf, args.windows, args.per_window):
            imgs = [cv2.imread(p) for p in win]
            pairs = windowed_pairs(imgs)
            for i, img in enumerate(imgs):
                if img is None:
                    continue
                try:
                    res = helpers.identify_screen(img, node_fps)
                except Exception:
                    continue
                bucket, _door, _reason, state = H.classify(res)
                a = classify_one(helpers, win[i], img,
                                 [p for p in pairs[max(0, i - 2):i] if p is not None],
                                 [p for p in pairs[i + 1:i + 3] if p is not None])
                a['file'] = os.path.basename(win[i])
                a['match'] = bucket
                a['named_state'] = state
                a['changed_pct'] = pairs[i]
                a['abstained'] = bucket != 'matched'
                rows.append(a)
                if a['abstained']:
                    abstain_rows.append(a)

    def report(pop, label):
        n = len(pop)
        if not n:
            print('\n%s: n = 0' % label)
            return {}
        tally = {k: sum(1 for r in pop if POSITIVE[k](r['answers'][k])) for k in ORDER}
        answered = sum(1 for r in pop if any(POSITIVE[k](r['answers'][k]) for k in ORDER))
        # The honest overlay number: a content frame judged 'dialog' is a FALSE positive.
        ovl = collections.Counter(r['answers']['overlay'] for r in pop)
        bug = sum(1 for r in pop if r['answers']['bugelogo_like'])
        print('\n=== %s — n = %d ===' % (label, n))
        for k in ORDER:
            print('  %-9s %4d  (%5.1f%%)' % (k, tally[k], 100.0 * tally[k] / n))
        print('  %-9s %4d  (%5.1f%%)' % ('ANSWERED', answered, 100.0 * answered / n))
        print('  %-9s %4d  (%5.1f%%)  <- nothing fired'
              % ('RESIDUE', n - answered, 100.0 * (n - answered) / n))
        print('  overlay verdicts: %s' % dict(ovl))
        print('  channel-bugelogo-like corner: %d (%.1f%%)'
              % (bug, 100.0 * bug / n))
        return {'n': n, 'tally': tally, 'answered': answered,
                'residue': n - answered,
                'overlay_verdicts': dict(ovl), 'bugelogo_like': bug}

    print()
    rep = {'all': report(rows, 'ALL frames'),
           'abstains': report(abstain_rows, 'ABSTAINS ONLY (the question)')}
    print('\n--- abstains split by capture-side state ---')
    rep['abstains_named'] = report([r for r in abstain_rows if r['named_state']], 'named capture state')
    rep['abstains_content'] = report([r for r in abstain_rows if not r['named_state']], 'content abstains')

    with open(args.out, 'w') as fh:
        json.dump({'report': rep, 'rows': rows}, fh, indent=1)
    print('\nwrote', args.out)


if __name__ == '__main__':
    main()