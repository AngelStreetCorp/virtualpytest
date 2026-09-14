#!/usr/bin/env python3
"""
LOCALIZE dHash transform experiment — does preprocessing the grayscale frame before
the family-layer dHash (CLAHE / edges / binarization) make it more discriminating
than the current plain-grayscale hash?

It reuses the REAL production bit-mechanics: ImageHelpers._dhash_hex (resize 17x16,
horizontal diffs, 256-bit hex) and ._dhash_hamming (XOR popcount). The ONLY thing
varied is a gray->gray transform applied before _dhash_hex. No production code is
touched — this only measures.

For a curated 10-image set it:
  0) sanity-checks the baseline against graph.json stored fingerprints (expect ~0),
  1) for each transform builds the NxN Hamming matrix,
  2) reports intra-class drift (en vs ge), inter-class min/mean, the confusable
     menu-cluster min/mean, and the headline GAP = inter_min - intra_drift,
  3) ranks the transforms,
  4) writes two PNGs: a transform mosaic (what each hash "sees") and per-transform
     Hamming heatmaps.

Usage:
    python3 features/avq/backend_host/localize/localize_transform_compare.py [IMAGE_DIR]
    # default IMAGE_DIR = the bundled example_tv fixture set
Filenames (sans extension) are node labels.
"""
import os
import sys
import glob
import json

# Import image_helpers DIRECTLY (not via the backend_host package) so this stays a
# standalone, dependency-light tester — the package __init__ pulls in appium/selenium.
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..', 'backend_host', 'src', 'controllers', 'verification')))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from image_helpers import ImageHelpers  # noqa: E402

FIXTURE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), 'fixtures', 'example_tv', 'screenshots'))
GRAPH_JSON = os.path.abspath(os.path.join(
    os.path.dirname(__file__), 'fixtures', 'example_tv', 'graph.json'))

# Curated 10-image set that stresses discrimination:
#   en/ge        -> same screen, two languages = intra-class drift probe
#   the 6 menus  -> look-alike cluster the title layer currently has to rescue
#   home/settings-> distinct anchors
CURATED = ['en', 'ge', 'home', 'settings',
           'home_movies', 'home_replay', 'home_tvshop',
           'movies', 'replay', 'tvshop']
INTRA_PAIR = ('en', 'ge')                     # same screen -> should stay CLOSE
CONFUSABLE = ['home_movies', 'home_replay', 'home_tvshop', 'movies', 'replay', 'tvshop']

# __new__ bypasses __init__ (captures_path / av_controller) — we only call pure helpers.
ih = ImageHelpers.__new__(ImageHelpers)


# ---- the 4 transforms (gray -> gray uint8); _dhash_hex is then applied unchanged ----
def t_gray(gray):
    """BASELINE = current production: no transform."""
    return gray


def t_clahe(gray):
    """Local contrast / text emphasis (same CLAHE production uses for title OCR)."""
    return cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)


def t_edge(gray):
    """Sobel gradient magnitude -> structural element/text boundaries, flat color suppressed."""
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    return cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def t_binar(gray):
    """Adaptive threshold -> pure text/element silhouette, luminance discarded."""
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                 cv2.THRESH_BINARY, 15, 5)


TRANSFORMS = [('gray*', t_gray), ('clahe', t_clahe), ('edge', t_edge), ('binar', t_binar)]


def load_set(img_dir):
    """Return ordered [(label, bgr)] for the curated labels present in img_dir, else first 10."""
    avail = {}
    for p in sorted(glob.glob(os.path.join(img_dir, '*.jpg')) + glob.glob(os.path.join(img_dir, '*.png'))):
        avail[os.path.splitext(os.path.basename(p))[0]] = p
    labels = [l for l in CURATED if l in avail] or list(avail.keys())[:10]
    out = []
    for l in labels:
        img = cv2.imread(avail[l])
        if img is not None:
            out.append((l, img))
    return out


def dhash_of(bgr, transform):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return ih._dhash_hex(transform(gray))


def hamming_matrix(hexes):
    n = len(hexes)
    m = np.zeros((n, n), dtype=int)
    for i in range(n):
        for j in range(i + 1, n):
            d = ImageHelpers._dhash_hamming(hexes[i], hexes[j])
            m[i, j] = m[j, i] = d
    return m


def sanity_check(samples):
    """Recompute the baseline gray dHash and diff vs graph.json stored fingerprints."""
    if not os.path.exists(GRAPH_JSON):
        print('  (graph.json not found — skipping sanity check)')
        return
    stored = {}
    for node in json.load(open(GRAPH_JSON)).get('nodes', []):
        fp = (node.get('data') or {}).get('fingerprint') or {}
        if fp.get('dhash'):
            stored[node.get('label')] = fp['dhash']
    diffs = []
    for label, bgr in samples:
        if label in stored:
            diffs.append(ImageHelpers._dhash_hamming(dhash_of(bgr, t_gray), stored[label]))
    if diffs:
        print(f'  baseline vs graph.json: {len(diffs)} matched, '
              f'mean Hamming={np.mean(diffs):.1f}, max={max(diffs)} (expect ~0)')
    else:
        print('  (no curated labels found in graph.json)')


def metrics(labels, mat):
    idx = {l: i for i, l in enumerate(labels)}
    intra = None
    if INTRA_PAIR[0] in idx and INTRA_PAIR[1] in idx:
        intra = int(mat[idx[INTRA_PAIR[0]], idx[INTRA_PAIR[1]]])
    # inter = all distinct-screen pairs (exclude the intra pair)
    inter = [int(mat[i, j]) for i in range(len(labels)) for j in range(i + 1, len(labels))
             if not (labels[i] in INTRA_PAIR and labels[j] in INTRA_PAIR)]
    conf_i = [idx[l] for l in CONFUSABLE if l in idx]
    conf = [int(mat[a, b]) for ai, a in enumerate(conf_i) for b in conf_i[ai + 1:]]
    return {
        'intra': intra,
        'inter_min': min(inter) if inter else None,
        'inter_mean': float(np.mean(inter)) if inter else None,
        'conf_min': min(conf) if conf else None,
        'conf_mean': float(np.mean(conf)) if conf else None,
        'gap': (min(inter) - intra) if (inter and intra is not None) else None,
        'conf_gap': (min(conf) - intra) if (conf and intra is not None) else None,
    }


# ---------------------------- visualization (cv2 only) ----------------------------
def put(img, text, org, scale=0.4, color=(230, 230, 230), thick=1):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def render_mosaic(samples, path):
    """Rows = images, cols = transforms; each cell = the 17x16 hash input, upscaled."""
    cell, pad, lblw, hdr = 96, 6, 92, 22
    rows, cols = len(samples), len(TRANSFORMS)
    W = lblw + cols * (cell + pad) + pad
    H = hdr + rows * (cell + pad) + pad
    canvas = np.full((H, W, 3), 30, np.uint8)
    for c, (name, _) in enumerate(TRANSFORMS):
        put(canvas, name, (lblw + c * (cell + pad) + 8, 15))
    for r, (label, bgr) in enumerate(samples):
        y = hdr + r * (cell + pad)
        put(canvas, label[:13], (4, y + cell // 2), scale=0.35)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        for c, (_, fn) in enumerate(TRANSFORMS):
            small = cv2.resize(fn(gray), (ih.FP_DHASH_GRID + 1, ih.FP_DHASH_GRID),
                               interpolation=cv2.INTER_AREA)
            up = cv2.resize(small, (cell, cell), interpolation=cv2.INTER_NEAREST)
            x = lblw + c * (cell + pad)
            canvas[y:y + cell, x:x + cell] = cv2.cvtColor(up, cv2.COLOR_GRAY2BGR)
    cv2.imwrite(path, canvas)


def render_heatmaps(labels, mats, path):
    """One NxN colorized Hamming matrix per transform, tiled horizontally. Common scale."""
    n = len(labels)
    cell, pad, top, left, gap = 26, 8, 60, 70, 30
    vmax = max(int(m.max()) for m in mats.values()) or 1
    sub_w = left + n * cell + pad
    sub_h = top + n * cell + pad
    canvas = np.full((sub_h, sub_w * len(TRANSFORMS) + gap * len(TRANSFORMS), 3), 25, np.uint8)
    for ti, (name, _) in enumerate(TRANSFORMS):
        ox = ti * (sub_w + gap)
        mat = mats[name]
        put(canvas, f'{name} (0..{vmax})', (ox + left, 20))
        for i in range(n):
            put(canvas, labels[i][:9], (ox + 2, top + i * cell + cell - 8), scale=0.3)
        for i in range(n):
            for j in range(n):
                v = int(mat[i, j])
                col = cv2.applyColorMap(np.uint8([[int(255 * v / vmax)]]), cv2.COLORMAP_JET)[0, 0]
                x, y = ox + left + j * cell, top + i * cell
                canvas[y:y + cell - 1, x:x + cell - 1] = col
                if i != j:
                    tc = (0, 0, 0) if v < vmax * 0.55 else (255, 255, 255)
                    put(canvas, str(v), (x + 2, y + cell - 9), scale=0.28, color=tc)
    cv2.imwrite(path, canvas)


def main():
    img_dir = sys.argv[1] if len(sys.argv) > 1 else FIXTURE_DIR
    print(f'Image dir: {img_dir}')
    samples = load_set(img_dir)
    if len(samples) < 2:
        print('Not enough images found.')
        return
    labels = [l for l, _ in samples]
    print(f'Set ({len(samples)}): {", ".join(labels)}\n')

    print('Sanity check (baseline reproduces production):')
    sanity_check(samples)
    print()

    mats, rows = {}, {}
    for name, fn in TRANSFORMS:
        hexes = [dhash_of(bgr, fn) for _, bgr in samples]
        mat = hamming_matrix(hexes)
        mats[name] = mat
        rows[name] = metrics(labels, mat)

    # ---- summary table ----
    hdr = f'{"transform":<9} {"intra(en~ge)":>13} {"inter_min":>10} {"inter_mean":>11} ' \
          f'{"conf_min":>9} {"conf_mean":>10} {"GAP":>6} {"conf_GAP":>9}'
    print(hdr)
    print('-' * len(hdr))
    for name, _ in TRANSFORMS:
        m = rows[name]
        print(f'{name:<9} {str(m["intra"]):>13} {str(m["inter_min"]):>10} '
              f'{m["inter_mean"]:>11.1f} {str(m["conf_min"]):>9} {m["conf_mean"]:>10.1f} '
              f'{str(m["gap"]):>6} {str(m["conf_gap"]):>9}')
    print('\nintra = en vs ge (lower better) | inter/conf = pairwise across distinct screens '
          '(higher better)\nGAP = inter_min - intra | conf_GAP = confusable_min - intra '
          '(headline: bigger = more discriminating)')

    # ---- ranking (by conf_GAP, then GAP) ----
    rank = sorted(TRANSFORMS, key=lambda t: (
        rows[t[0]]['conf_gap'] if rows[t[0]]['conf_gap'] is not None else -999,
        rows[t[0]]['gap'] if rows[t[0]]['gap'] is not None else -999), reverse=True)
    print('\nRanking (best confusable separation per unit of intra drift):')
    for i, (name, _) in enumerate(rank, 1):
        m = rows[name]
        print(f'  {i}. {name:<7} conf_GAP={m["conf_gap"]}  GAP={m["gap"]}  intra={m["intra"]}')
    best = rank[0][0]
    base = rows['gray*']
    bm = rows[best]
    if best == 'gray*':
        print('\n=> Baseline grayscale already wins — no transform beats it on this set.')
    else:
        print(f'\n=> Winner: "{best}" (conf_GAP {bm["conf_gap"]} vs baseline {base["conf_gap"]}; '
              f'intra {bm["intra"]} vs {base["intra"]}). Inspect the mosaic/heatmaps before wiring in.')

    mosaic = '/tmp/localize_transform_mosaic.png'
    heat = '/tmp/localize_transform_heatmaps.png'
    render_mosaic(samples, mosaic)
    render_heatmaps(labels, mats, heat)
    print(f'\nWrote {mosaic}\nWrote {heat}')


if __name__ == '__main__':
    main()
