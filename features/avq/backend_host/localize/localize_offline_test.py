#!/usr/bin/env python3
"""
Offline Localize validator — runs the REAL v4 pipeline (dHash family + underline +
TITLE text) against a folder of local screenshots, no device / no DB. Drives the
production functions in image_helpers.py and mirrors navigation_executor.localize()
(match_fingerprint -> title disambiguation -> dHash fallback) so it tests exactly
what the host does.

For each image it:
  1) classifies the focus layer (nav underline / box / none) and shows the title,
  2) inclusive identify (each frame as live vs all) through the FULL pipeline,
     reporting any genuine false positive (resolved to a wrong screen),
  3) optional cross-language demo (a German live frame vs English refs),
  4) a DOM mosaic (one schematic thumbnail per screen: text boxes + title + focus,
     content stripped) written to a PNG so collisions are visible at a glance.

Usage:
    python3 features/avq/backend_host/localize/localize_offline_test.py [IMAGE_DIR] [LIVE_IMAGE]
    # default IMAGE_DIR = ~/virtualpytest/screenshot/example_tv
Filenames (sans extension) are treated as node labels.
"""
import os
import sys
import glob
import re
import math
import tempfile
import subprocess

# Import image_helpers DIRECTLY (not via the backend_host package) so this stays a
# standalone, dependency-light tester — the package __init__ pulls in appium/selenium.
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..', 'backend_host', 'src', 'controllers', 'verification')))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from image_helpers import ImageHelpers  # noqa: E402

DEFAULT_DIR = os.path.expanduser('~/virtualpytest/screenshot/example_tv')

# Title translation to the English pivot. On the host this is translation_utils;
# offline (googletrans often broken) we fall back to a tiny demo map so the
# cross-language case is still demonstrable. Same-language matching needs no map.
# NB: 'filme'->'films' mirrors what real MT returns (the EN UI says "Movies"), so the
# offline test exercises the synonym gap that char-level title_score must bridge.
_DEMO = {'filme': 'films', 'serien': 'series', 'entdecken': 'discover',
         'aufnahmen': 'recordings', 'startseite': 'home'}


def to_pivot(s):
    try:
        from backend_host.src.lib.utils.translation_utils import translate_text
        r = translate_text(s, 'auto', 'en', method='auto')
        if r.get('success') and r.get('translated_text'):
            return ImageHelpers._normalize_text(r['translated_text'])
    except Exception:
        pass
    return ' '.join(_DEMO.get(w, w) for w in (s or '').split())


# --- DOM mosaic: one schematic thumbnail per screen (text boxes + title + focus) ---
_KIND_BORDER = {'nav': (255, 160, 0), 'box': (0, 165, 255), 'none': (90, 90, 90), 'dark': (45, 45, 45)}


def _is_dark(ih, img):
    return float(cv2.Canny(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 50, 150).mean()) < ih.FP_DARK_EDGE_MIN


def _full_tokens(img):
    """Sizeable full-frame UI text boxes (drops tiny poster-caption noise) for the DOM."""
    h, w = img.shape[:2]
    g = cv2.createCLAHE(2.0, (8, 8)).apply(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    tmp = tempfile.mktemp(suffix='.png')
    cv2.imwrite(tmp, g)
    try:
        out = subprocess.run(['tesseract', tmp, 'stdout', 'tsv'], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        out = ''
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    lines = {}
    for ln in out.splitlines()[1:]:
        c = ln.split('\t')
        if len(c) < 12:
            continue
        try:
            x, y, bw, bh, conf = int(c[6]), int(c[7]), int(c[8]), int(c[9]), float(c[10])
        except ValueError:
            continue
        if conf > 45 and len(re.sub(r'[^0-9A-Za-zÀ-ÿ]', '', c[11])) >= 2 and bh >= 0.018 * h:
            lines.setdefault((c[2], c[3], c[4]), []).append((x, y, bw, bh))
    return [{'x': 100 * x / w, 'y': 100 * y / h, 'w': 100 * bw / w, 'size': bh, 'H': h}
            for ws in lines.values() if len(ws) <= 3 for x, y, bw, bh in ws]


def _render_cell(img, name, fp, dark, tw=300, th=170, state=None):
    cell = np.full((th + 22, tw, 3), 24, np.uint8)
    h, w = img.shape[:2]
    focus = fp['focus']
    cv2.rectangle(cell, (0, 0), (tw - 1, th + 21), _KIND_BORDER['dark' if (dark or state) else focus.get('kind', 'none')], 2)
    if dark or state:
        label = {'no_signal': 'NO SIGNAL', 'blackscreen': 'BLACK'}.get(state, 'UNKNOWN')
        cv2.putText(cell, label, (tw // 2 - 9 * len(label), th // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (70, 70, 70), 2, cv2.LINE_AA)
    else:
        for t in _full_tokens(img):
            x = int(t['x'] / 100 * tw); y = int(t['y'] / 100 * th)
            bw = max(2, int(t['w'] / 100 * tw)); bh = max(2, int(t['size'] / t['H'] * th * 1.3))
            b = int(min(230, 70 + t['size'] * 5))
            cv2.rectangle(cell, (x, y), (x + bw, y + bh), (b, b, b), -1)
        if focus.get('kind') == 'nav' and focus.get('x') is not None:
            x = int(focus['x'] * tw); hw = int(focus.get('width', 0.05) * tw / 2)
            cv2.line(cell, (x - hw, int(0.14 * th)), (x + hw, int(0.14 * th)), (0, 0, 255), 4)
        elif focus.get('kind') == 'box' and focus.get('x') is not None:
            x = int(focus['x'] * tw); y = int(focus.get('y', 0.4) * th)
            cv2.rectangle(cell, (x - 18, y - 12), (x + 18, y + 12), (0, 255, 255), 2)
        cv2.putText(cell, (fp.get('title') or '?')[:20], (4, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (60, 230, 230), 1, cv2.LINE_AA)
    cv2.putText(cell, name[:26], (4, th + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (255, 255, 255), 1, cv2.LINE_AA)
    return cell


def build_mosaic(ih, names, imgs, fps, cols=6):
    """Schematic thumbnails (sorted by name) tiled into one PNG for collision-spotting."""
    tw, th = 300, 192
    cells = [_render_cell(imgs[n], n, fps[n], _is_dark(ih, imgs[n]),
                          state=ih.classify_special_state(imgs[n])) for n in sorted(names)]
    rows = math.ceil(len(cells) / cols)
    mosaic = np.full((rows * th, cols * tw, 3), 12, np.uint8)
    for i, c in enumerate(cells):
        r, cc = divmod(i, cols)
        mosaic[r * th:r * th + c.shape[0], cc * tw:cc * tw + tw] = c
    out = os.path.join(tempfile.gettempdir(), 'localize_dom_mosaic.png')
    cv2.imwrite(out, mosaic)
    return out, cols, rows


def main():
    img_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
    ih = ImageHelpers.__new__(ImageHelpers)
    M = ImageHelpers.FP_CANDIDATE_MARGIN

    paths = sorted(glob.glob(os.path.join(img_dir, '*.jpg')) +
                   glob.glob(os.path.join(img_dir, '*.png')))
    imgs = {os.path.splitext(os.path.basename(p))[0]: cv2.imread(p) for p in paths}
    imgs = {n: im for n, im in imgs.items() if im is not None}
    names = list(imgs)
    if not names:
        print(f"No images found in {img_dir}")
        sys.exit(1)
    print(f"Computing fingerprints for {len(names)} screens in {img_dir} ...")
    fps = {n: ih.compute_fingerprint(imgs[n]) for n in names}
    node_fps = [{'node_id': n, 'label': n, 'fingerprint': fps[n]} for n in names]
    fp_by_id = {n: fps[n] for n in names}

    def localize(img):
        """Drive the SAME production matcher the app uses end-to-end
        (image_helpers.identify_screen: v6 match -> title -> dHash -> state)."""
        res = ih.identify_screen(img, node_fps)
        cands = res.get('candidates') or []
        if not cands and res.get('state'):              # unknown -> named capture-side state
            return [f"<{res['state']}>"]
        return [c['label'] for c in cands]

    # 1) focus + title per screen
    print("\n### 1) FOCUS + TITLE")
    for n in names:
        f = fps[n]
        print(f"   {n:26s} focus={f['focus'].get('kind'):4s} title={f['title']!r}")

    # 2) inclusive identify through the full pipeline
    print("\n### 2) INCLUSIVE IDENTIFY (full pipeline)")
    uniq = 0
    false_pos = []
    ambiguous = []
    states = []
    for q in names:
        post = localize(imgs[q])
        if len(post) == 1 and post[0].startswith('<'):
            states.append((q, post[0]))            # named capture-side state, not a node
        elif post == [q]:
            uniq += 1
        elif not post:
            ambiguous.append((q, 'EMPTY (dark guard)'))
        elif q not in post:
            false_pos.append((q, post))            # resolved WITHOUT self -> real false positive
        else:
            ambiguous.append((q, post))            # group still contains self -> fail-safe
    print(f"   uniquely-correct: {uniq}/{len(names)}")
    print(f"   FALSE POSITIVES (resolved to a wrong screen): {false_pos if false_pos else 'NONE'}")
    print(f"   named special states: {states if states else 'NONE'}")
    print(f"   ambiguous/fail-safe groups: {len(ambiguous)}")
    for q, g in ambiguous:
        print(f"       {q:26s} -> {g}")

    # 3) optional explicit live image (e.g. a cross-language capture)
    if len(sys.argv) > 2 and os.path.exists(sys.argv[2]):
        live = cv2.imread(sys.argv[2])
        print(f"\n### 3) LIVE {sys.argv[2]}")
        print(f"   title={to_pivot(ih._title_text(live))!r}  -> {localize(live)}")

    # 4) DOM mosaic — auto-generated every run (text boxes + title + focus per screen)
    print("\n### 4) DOM MOSAIC")
    out, cols, rows = build_mosaic(ih, names, imgs, fps)
    print(f"   {cols}x{rows} schematic thumbnails -> {out}")


if __name__ == '__main__':
    main()
