#!/usr/bin/env python3
"""Probe: does cropping the FOCUSED element (via no_reference_focus_detector) and hashing
THAT crop separate the app-grid tiles — the one cluster that v4/v5/edge all collapse to ~0?

For the apps_* cluster it:
  - runs detect_focus() to find the focused tile box,
  - crops it, computes a dHash of the crop + a coarse color histogram + ORB keypoint count,
  - reports the nearest-OTHER-app distance under (a) the focus-crop dHash and (b) color hist,
    next to the v4 full-frame baseline, so we can see if the focused logo is separable,
  - writes /tmp/focus_crop_annot.png (focus boxes) and /tmp/focus_crop_tiles.png (the crops).

  python3 backend_host/scripts/focus_crop_probe.py
"""
import os, sys, glob
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'src', 'controllers', 'verification')))
sys.path.insert(0, os.path.dirname(__file__))   # for no_reference_focus_detector
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from image_helpers import ImageHelpers  # noqa: E402
from no_reference_focus_detector import detect_focus, annotate  # noqa: E402

FIXTURE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), 'fixtures', 'example_tv', 'screenshots'))
H = ImageHelpers.__new__(ImageHelpers)
ham = ImageHelpers._dhash_hamming


def color_hist(bgr):
    """Coarse normalized HS histogram (8x8) -> flat vector for cosine distance."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1], None, [8, 8], [0, 180, 0, 256])
    return cv2.normalize(h, h).flatten()


def main():
    paths = sorted(glob.glob(os.path.join(FIXTURE_DIR, 'apps*.jpg')))
    nodes = []
    annots, tiles = [], []
    for p in paths:
        label = os.path.splitext(os.path.basename(p))[0]
        img = cv2.imread(p)
        if img is None:
            continue
        cands = detect_focus(img)
        annots.append((label, annotate(img, cands)))
        if cands:
            x, y, w, h = cands[0].box
            crop = img[y:y + h, x:x + w]
            cue = cands[0].cue_type
        else:
            crop = img
            cue = 'NONE'
        if crop.size == 0:
            crop = img
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        orb = cv2.ORB_create(nfeatures=200)
        kp = orb.detect(gray, None)
        nodes.append({
            'label': label, 'cue': cue,
            'cdhash': H._dhash_hex(gray),
            'chist': color_hist(crop),
            'orb': len(kp),
            'fullhash': H._dhash_hex(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)),
        })
        tiles.append((label, cv2.resize(crop, (120, 120))))

    print(f'app-grid cluster: {len(nodes)} nodes\n')
    print(f'{"node":20}{"cue":16}{"orb":>4}{"v4_full_near":>14}{"focusCrop_near":>16}{"colorHist_near":>16}')
    print('-' * 86)
    for i, a in enumerate(nodes):
        others = [b for j, b in enumerate(nodes) if j != i]
        v4 = min(ham(a['fullhash'], b['fullhash']) for b in others)
        fc = min((ham(a['cdhash'], b['cdhash']), b['label']) for b in others)
        ch = min((float(cv2.compareHist(
            a['chist'].reshape(8, 8), b['chist'].reshape(8, 8), cv2.HISTCMP_BHATTACHARYYA)), b['label'])
            for b in others)
        print(f'{a["label"]:20}{a["cue"]:16}{a["orb"]:>4}{v4:>14}'
              f'{fc[0]:>11} {fc[1][:10]:>4}{ch[0]:>11.2f} {ch[1][:10]:>4}')

    print('\nv4_full_near = bits to nearest other app (now ~0-3 = all collide)')
    print('focusCrop_near = dHash bits between focused-tile crops (HIGHER = separable)')
    print('colorHist_near = Bhattacharyya dist of focused-tile color hist (0=identical,1=disjoint)')

    # visuals
    def grid(items, cell, cols=4):
        rows = (len(items) + cols - 1) // cols
        pad, lab = 6, 16
        canvas = np.full((rows * (cell + lab + pad), cols * (cell + pad), 3), 30, np.uint8)
        for k, (lbl, im) in enumerate(items):
            r, c = divmod(k, cols)
            y, x = r * (cell + lab + pad), c * (cell + pad)
            ih2 = cv2.resize(im, (cell, cell))
            canvas[y + lab:y + lab + cell, x:x + cell] = ih2
            cv2.putText(canvas, lbl[:16], (x + 2, y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                        (230, 230, 230), 1, cv2.LINE_AA)
        return canvas
    cv2.imwrite('/tmp/focus_crop_annot.png', grid(annots, 240, 4))
    cv2.imwrite('/tmp/focus_crop_tiles.png', grid(tiles, 120, 6))
    print('\nWrote /tmp/focus_crop_annot.png (focus boxes) + /tmp/focus_crop_tiles.png (crops)')


if __name__ == '__main__':
    main()
