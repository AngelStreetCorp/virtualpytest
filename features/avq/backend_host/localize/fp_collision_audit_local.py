#!/usr/bin/env python3
"""Per-node fingerprint audit over the LOCAL example_tv fixture screenshots — adds an EDGE
(Sobel) preprocessing variant alongside the v4 (full-frame) and v5 (multi-region) signatures.

Mirrors fp_collision_audit.py's metric exactly (nearest OTHER node vs the T=14 self-drift floor)
but reads the bundled fixtures (no DB / R2), so it covers the screenshots present locally.

Four signatures per node (all via the real ImageHelpers._dhash_hex / ._dhash_hamming):
  v4  full       = plain-gray full-frame dHash            -> nearest-other Hamming  (lower = confusable)
  v5  regions    = plain-gray {full,top,center,left,bottom}-> best-region separation to nearest other
  edgeF full     = Sobel-edge full-frame dHash            -> nearest-other Hamming
  edgeR regions  = Sobel-edge {regions} dHash             -> best-region separation to nearest other
A pair is a FALSE POSITIVE (collision) when a DIFFERENT node sits within T=14 bits.

  python3 features/avq/backend_host/localize/fp_collision_audit_local.py [IMAGE_DIR]
Writes /tmp/localize_fp_audit_table.md (full table, markdown) + prints a summary.
"""
import os, sys, glob
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..', 'backend_host', 'src', 'controllers', 'verification')))
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from image_helpers import ImageHelpers  # noqa: E402

FIXTURE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), 'fixtures', 'example_tv', 'screenshots'))
OUT_MD = '/tmp/localize_fp_audit_table.md'

T = 14                                    # FP_SELF_DRIFT_FLOOR — a different node within this = false positive
REGIONS = ['full', 'top', 'center', 'left', 'bottom']
H = ImageHelpers.__new__(ImageHelpers)    # bypass __init__ — only pure helpers used
ham = ImageHelpers._dhash_hamming


def region_crops(gray):
    """Same crops as fp_collision_audit.py / FP_V5_REGIONS."""
    h, w = gray.shape
    return {
        'full': gray,
        'top': gray[0:int(0.20 * h), :],
        'center': gray[int(0.22 * h):int(0.78 * h), int(0.20 * w):int(0.80 * w)],
        'left': gray[:, 0:int(0.20 * w)],
        'bottom': gray[int(0.80 * h):, :],
    }


def edge(gray):
    """Sobel gradient magnitude, globally normalized to uint8 (preprocess the FRAME, then crop)."""
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.normalize(cv2.magnitude(gx, gy), None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def load(img_dir):
    nodes = []
    for p in sorted(glob.glob(os.path.join(img_dir, '*.jpg')) + glob.glob(os.path.join(img_dir, '*.png'))):
        img = cv2.imread(p)
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        eg = edge(gray)                                          # edge whole frame, then crop (shared scale)
        nodes.append({
            'label': os.path.splitext(os.path.basename(p))[0],
            'v4': {r: H._dhash_hex(c) for r, c in region_crops(gray).items()},
            'edge': {r: H._dhash_hex(c) for r, c in region_crops(eg).items()},
        })
    return nodes


def full_near(nodes, i, sig):
    """Nearest OTHER node by full-frame dHash of signature `sig` -> (dist, label)."""
    a = nodes[i][sig]['full']
    best = min(((ham(a, nodes[j][sig]['full']), nodes[j]['label'])
                for j in range(len(nodes)) if j != i), key=lambda t: t[0])
    return best


def region_near(nodes, i, sig):
    """Nearest OTHER node by v5 metric (best separator = max region dist) -> (sep, label, region)."""
    a = nodes[i][sig]
    def sep(j):
        return max(ham(a[r], nodes[j][sig][r]) for r in REGIONS)
    j = min((j for j in range(len(nodes)) if j != i), key=sep)
    s = sep(j)
    br = min(REGIONS, key=lambda r: ham(a[r], nodes[j][sig][r]))   # the region that almost matched
    return s, nodes[j]['label'], br


def collisions(nodes, kind):
    """Count DIFFERENT-node pairs within T for a given method."""
    n = len(nodes)
    c = 0
    for i in range(n):
        for j in range(i + 1, n):
            if kind == 'v4':
                d = ham(nodes[i]['v4']['full'], nodes[j]['v4']['full'])
            elif kind == 'edgeF':
                d = ham(nodes[i]['edge']['full'], nodes[j]['edge']['full'])
            elif kind == 'v5':
                d = max(ham(nodes[i]['v4'][r], nodes[j]['v4'][r]) for r in REGIONS)
            else:  # edgeR
                d = max(ham(nodes[i]['edge'][r], nodes[j]['edge'][r]) for r in REGIONS)
            if d < T:
                c += 1
    return c


def main():
    img_dir = sys.argv[1] if len(sys.argv) > 1 else FIXTURE_DIR
    nodes = load(img_dir)
    if len(nodes) < 2:
        print('Not enough images.'); return
    print(f'=== local fixture audit: {len(nodes)} nodes | floor T={T} bits ===\n')

    counts = {k: collisions(nodes, k) for k in ('v4', 'edgeF', 'v5', 'edgeR')}
    print('Colliding DIFFERENT-node pairs within T (lower = more discriminative):')
    print(f'  v4    full-frame        : {counts["v4"]:4d}')
    print(f'  edgeF full-frame (Sobel): {counts["edgeF"]:4d}')
    print(f'  v5    multi-region      : {counts["v5"]:4d}')
    print(f'  edgeR multi-region(Sobel): {counts["edgeR"]:4d}\n')

    # full per-node table
    rows = []
    for i in range(len(nodes)):
        v4d, v4l = full_near(nodes, i, 'v4')
        ed, el = full_near(nodes, i, 'edge')
        v5s, v5l, v5r = region_near(nodes, i, 'v4')
        ers, erl, err = region_near(nodes, i, 'edge')
        rows.append((nodes[i]['label'], v4d, v4l, ed, el, v5s, v5l, v5r, ers, erl, err))
    rows.sort(key=lambda r: r[1])   # tightest v4 first

    md = [f'# example_tv fingerprint audit — v4 / edge / v5 / edge-region ({len(nodes)} local nodes, T={T})',
          '',
          'Per node: distance to the **nearest OTHER** node. `_d` = full-frame Hamming, '
          '`_sep` = v5 best-region separation. **Lower = more confusable**; `< 14` = false-positive (⚠️).',
          '',
          'Collision pairs within T — v4: **{}**, edgeF: **{}**, v5: **{}**, edgeR: **{}**.'.format(
              counts['v4'], counts['edgeF'], counts['v5'], counts['edgeR']),
          '',
          '| node | v4_d | edgeF_d | v5_sep | edgeR_sep | v4 nearest | v5 via |',
          '|------|-----:|--------:|-------:|----------:|------------|--------|']
    def f(v): return f'{v}⚠️' if v < T else f'{v}'
    for (lbl, v4d, v4l, ed, el, v5s, v5l, v5r, ers, erl, err) in rows:
        md.append(f'| {lbl} | {f(v4d)} | {f(ed)} | {f(v5s)} | {f(ers)} | {v4l} | {v5r} |')
    open(OUT_MD, 'w').write('\n'.join(md) + '\n')

    # console preview: tightest 20
    print(f'{"node":24}{"v4_d":>6}{"edgeF_d":>9}{"v5_sep":>8}{"edgeR_sep":>11}  nearest(v4)')
    print('-' * 86)
    for (lbl, v4d, v4l, ed, el, v5s, v5l, v5r, ers, erl, err) in rows[:20]:
        flag = ' FP!' if v4d < T else '    '
        print(f'{lbl:24}{v4d:>6}{ed:>9}{v5s:>8}{ers:>11}  {v4l[:22]}{flag}')
    print(f'\n... full {len(rows)}-row table written to {OUT_MD}')


if __name__ == '__main__':
    main()
