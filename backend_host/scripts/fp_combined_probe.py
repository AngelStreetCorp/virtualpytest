#!/usr/bin/env python3
"""Combined-scorer probe: fuse v5 multi-region + focused-element crop into ONE separation
score and compare collision counts vs each method alone, over the 67 local fixtures.

Fusion principle (the user's point — combine, don't choose): two screens are the SAME only
if confusable under EVERY method. So per pair the separation = MAX(v5_region_sep, crop_dist):
a pair collides (false positive, < T=14) only if NEITHER v5 NOR the focused crop separates it.
Max-fusion can only REMOVE collisions vs the best single method, never add them.

  python3 backend_host/scripts/fp_combined_probe.py
"""
import os, sys, glob
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'src', 'controllers', 'verification')))
sys.path.insert(0, os.path.dirname(__file__))
import cv2  # noqa: E402
from image_helpers import ImageHelpers  # noqa: E402
from no_reference_focus_detector import detect_focus  # noqa: E402

FIXTURE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), 'fixtures', 'example_tv', 'screenshots'))
T = 14
REGIONS = ['full', 'top', 'center', 'left', 'bottom']
H = ImageHelpers.__new__(ImageHelpers)
ham = ImageHelpers._dhash_hamming


def region_crops(gray):
    h, w = gray.shape
    return {'full': gray, 'top': gray[0:int(0.20 * h), :],
            'center': gray[int(0.22 * h):int(0.78 * h), int(0.20 * w):int(0.80 * w)],
            'left': gray[:, 0:int(0.20 * w)], 'bottom': gray[int(0.80 * h):, :]}


def load():
    nodes = []
    for p in sorted(glob.glob(os.path.join(FIXTURE_DIR, '*.jpg'))):
        img = cv2.imread(p)
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cands = detect_focus(img)
        if cands:
            x, y, w, h = cands[0].box
            crop = img[y:y + h, x:x + w]
        else:
            crop = img
        if crop.size == 0:
            crop = img
        nodes.append({
            'label': os.path.splitext(os.path.basename(p))[0],
            'reg': {r: H._dhash_hex(c) for r, c in region_crops(gray).items()},
            'crop': H._dhash_hex(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)),
        })
    return nodes


def sep(a, b, method):
    if method == 'v5':
        return max(ham(a['reg'][r], b['reg'][r]) for r in REGIONS)
    if method == 'crop':
        return ham(a['crop'], b['crop'])
    return max(max(ham(a['reg'][r], b['reg'][r]) for r in REGIONS), ham(a['crop'], b['crop']))


def main():
    nodes = load()
    n = len(nodes)
    print(f'=== combined-scorer probe: {n} nodes | T={T} ===\n')
    methods = ['v5', 'crop', 'combined']
    coll = {m: [] for m in methods}
    for i in range(n):
        for j in range(i + 1, n):
            for m in methods:
                if sep(nodes[i], nodes[j], m) < T:
                    coll[m].append((nodes[i]['label'], nodes[j]['label'], sep(nodes[i], nodes[j], m)))
    print('Colliding DIFFERENT-node pairs within T (lower = better):')
    for m in methods:
        print(f'  {m:9}: {len(coll[m]):3d}')
    print('\nResidual COMBINED collisions (confusable under BOTH v5 and focus-crop):')
    for a, b, s in sorted(coll['combined'], key=lambda x: x[2]):
        print(f'  [{s:2d}] {a}  <->  {b}')
    fixed = [(a, b, s) for a, b, s in coll['v5'] if (a, b) not in {(x[0], x[1]) for x in coll['combined']}]
    print(f'\nv5 collisions the focus-crop now resolves: {len(fixed)}')
    for a, b, s in sorted(fixed, key=lambda x: x[2]):
        print(f'  v5_sep={s:2d}  {a}  vs  {b}')


if __name__ == '__main__':
    main()
