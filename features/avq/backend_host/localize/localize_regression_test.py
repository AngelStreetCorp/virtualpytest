#!/usr/bin/env python3
"""
LOCALIZE LIVE-FRAME REGRESSION TEST — catches what self-match cannot.

The collision/self-match test (localize_offline_test.py) matches each stored
screenshot against itself: ZERO drift, so a content-heavy nav screen (rotating
hero) scores region distance 0 and can never trip a region floor. That blind spot
shipped a real regression (FP_NAV_REGION_FLOOR=60 rejected live `home`/`home_tvguide`
at 68/71 bits of legitimate hero drift).

This test fixes that: it runs the REAL production matcher (image_helpers.identify_screen)
over a folder of LIVE frames captured off the device — which DO drift from the stored
reference — and asserts the expected verdict. Fixtures live in
`localize_fixtures/<ui>/` named `<description>__<expected>.jpg`, where <expected> is a
node label the top candidate must equal, or `abstain` (must localize to nothing — the
guard against false positives on live video / non-menu content).

Node fingerprints come from the same stored corpus the offline tester uses
(~/virtualpytest/screenshot/<ui>), so this exercises live-frame-vs-stored, the real
runtime condition. Exits non-zero on any failure so it can gate a commit.

Usage:
  python3 features/avq/backend_host/localize/localize_regression_test.py [example_tv]
  python3 features/avq/backend_host/localize/localize_regression_test.py example_tv /path/to/corpus
"""
import os
import sys
import glob

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..', 'backend_host', 'src', 'controllers', 'verification')))

import cv2  # noqa: E402
from image_helpers import ImageHelpers  # noqa: E402

UI = sys.argv[1] if len(sys.argv) > 1 else 'example_tv'
CORPUS = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser(f'~/virtualpytest/screenshot/{UI}')
FIXTURES = os.path.join(os.path.dirname(__file__), 'localize_fixtures', UI)


def load_node_fps(ih, corpus_dir):
    paths = sorted(glob.glob(os.path.join(corpus_dir, '*.jpg')) +
                   glob.glob(os.path.join(corpus_dir, '*.png')))
    node_fps = []
    for p in paths:
        name = os.path.splitext(os.path.basename(p))[0]
        img = cv2.imread(p)
        if img is None:
            continue
        fp = ih.compute_fingerprint(img)
        if fp and fp.get('dhash'):
            node_fps.append({'node_id': name, 'label': name, 'fingerprint': fp})
    return node_fps


def expected_of(filename):
    stem = os.path.splitext(os.path.basename(filename))[0]
    return stem.split('__', 1)[1] if '__' in stem else stem


def main():
    if not os.path.isdir(CORPUS):
        print(f"ERROR: corpus dir not found: {CORPUS}")
        sys.exit(2)
    if not os.path.isdir(FIXTURES):
        print(f"ERROR: fixtures dir not found: {FIXTURES}")
        sys.exit(2)

    ih = ImageHelpers.__new__(ImageHelpers)
    node_fps = load_node_fps(ih, CORPUS)
    if not node_fps:
        print(f"ERROR: no fingerprints in corpus {CORPUS}")
        sys.exit(2)

    fixtures = sorted(glob.glob(os.path.join(FIXTURES, '*.jpg')) +
                      glob.glob(os.path.join(FIXTURES, '*.png')))
    if not fixtures:
        print(f"ERROR: no fixtures in {FIXTURES}")
        sys.exit(2)

    print(f"Corpus: {len(node_fps)} nodes from {CORPUS}")
    print(f"Fixtures: {len(fixtures)} live frames from {FIXTURES}\n")

    failures = 0
    for fx in fixtures:
        expected = expected_of(fx)
        img = cv2.imread(fx)
        res = ih.identify_screen(img, node_fps)
        cands = res.get('candidates') or []
        top = cands[0]['label'] if cands else None
        conf = cands[0].get('confidence') if cands else None

        if expected == 'abstain':
            ok = (top is None)
            got = (top or 'abstain')
        else:
            ok = (top == expected)
            got = top or 'abstain'

        status = 'PASS' if ok else 'FAIL'
        if not ok:
            failures += 1
        confs = f" conf={conf:.2f}" if conf is not None else ""
        reason = f" reason={res.get('reason')}" if not cands else ""
        print(f"  [{status}] {os.path.basename(fx):42s} expect={expected:16s} "
              f"got={got}{confs}{reason}")

    print(f"\n{len(fixtures) - failures}/{len(fixtures)} passed.")
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
