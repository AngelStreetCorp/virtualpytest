#!/usr/bin/env python3
"""
Geometry-based TV-UI navigation inference (offline prototype).

One screenshot -> nav/menu item boxes -> directional remote edges
(LEFT/RIGHT/UP/DOWN) + OK=ENTER / BACK=UNKNOWN -> a predicted navigation map
(printed + JSON) and an arrow-overlay PNG you can eyeball.

Scope: NAV/MENU bars only (top menu + sub-tabs). Content tiles/rows are out of
scope (an unfocused tile has no border, so it is not locatable from one frame).

Node = screen_id + focused_item. Edges are PREDICTED from geometry alone:
- LEFT/RIGHT = nearest item on that side with strong vertical overlap (same row)
- UP/DOWN    = nearest item above/below with strong horizontal overlap (other row)
- OK -> ENTER:<focused item>   (verified later by actually pressing OK)
- BACK -> UNKNOWN              (geometry cannot know it)

Usage:
    python3 backend_host/scripts/ui_infer_offline.py IMAGE [screen_id] [--out OUT.png]
"""
import os
import sys
import re
import json
import math
import tempfile
import subprocess

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'src', 'controllers', 'verification')))
from image_helpers import ImageHelpers  # noqa: E402

ih = ImageHelpers.__new__(ImageHelpers)

_FW = _FH = 1   # full-frame width/height in px; set in main() so OCR boxes normalize correctly

# --- tunables (normalized fractions of frame unless noted) ---
NAV_BAND = 0.20        # nav/menu bars live in the top fraction (tight: cuts hero/content)
ITEM_GAP = 0.012       # x-gap (frac width) above which two words = different items.
                       # Tab gaps == multi-word-item gaps, so gap ALONE can't tell them
                       # apart — an '&'/'+' connector bridges words into one item instead.
ROW_TOL = 0.04         # centers within this y-fraction = same row
NAV_MIN_ITEMS = 3      # a menu row has at least this many items (excludes 1-2-word titles)
V_OVERLAP_MIN = 0.30   # min vertical overlap to be LEFT/RIGHT neighbours
H_OVERLAP_MIN = 0.15   # min horizontal overlap to be UP/DOWN neighbours
MIN_CONF = 35          # grey unselected tabs read at lower confidence
OCR_SCALE = 2          # upscale the band — small grey nav text needs it
OCR_PSM = '6'          # uniform block: reads low-contrast tabs with less sparse-noise


def _slug(s):
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_') or 'item'


def _looks_like_word(tok):
    """Reject OCR garbage fragments (op, ak, Mi, DNS, FS…) while keeping real labels."""
    t = tok.replace('&', '').replace('+', '').replace('-', '')
    if t.lower() in ('tv', 'ok', 'pin'):       # legit short labels
        return True
    if len(t) < 3:
        return False
    return bool(re.search(r'[aeiouyàâäéèêëïîôöùûü]', t.lower()))   # a real word has a vowel


# The two tight y-bands a nav row sits in: top-level menu vs per-screen sub-nav.
# Tight = excludes the title above and the content row below (which feed OCR garbage).
NAV_CANDIDATE_BANDS = [(0.03, 0.10), (0.115, 0.175)]
PSM_MODES = ('6', '7', '11')   # different layout modes read different faint tabs
SLOT_TOL = 0.025               # words within this cx fraction = the same tab slot
MIN_VOTES = 2                  # a real tab is read by >= this many psm modes...
HIGH_CONF = 78                 # ...unless a single read is very confident


def _tess_raw(gray, psm, y0, scale=3):
    """Tesseract on a CLAHE'd crop -> words {t,conf,x,y,w,h,cx,cy} normalized to the
    full frame. Light filter only (conf/len/digits) — the multi-psm vote filters garbage."""
    g = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    tmp = tempfile.mktemp(suffix='.png')
    cv2.imwrite(tmp, g)
    try:
        out = subprocess.run(['tesseract', tmp, 'stdout', '--psm', psm, 'tsv'],
                             capture_output=True, text=True, timeout=20).stdout
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    sx, sy = scale * _FW, scale * _FH
    words = []
    for ln in out.splitlines()[1:]:
        c = ln.split('\t')
        if len(c) < 12:
            continue
        try:
            x, y, ww, hh, conf = int(c[6]), int(c[7]), int(c[8]), int(c[9]), float(c[10])
        except ValueError:
            continue
        tok = re.sub(r'[^0-9A-Za-zÀ-ÿ&+-]', '', c[11])
        # keep the '&'/'-' connectors (len 1; bridge multi-word items like "Sound & image"
        # or "On-demand") and don't drop a CORRECT low-confidence read ("Discover" @ conf 20)
        if conf < 12 or (len(tok) < 2 and tok not in ('&', '-')) or re.fullmatch(r'[0-9]+', tok):
            continue
        words.append({'t': tok, 'conf': conf, 'x': x / sx, 'y': y0 + y / sy,
                      'w': ww / sx, 'h': hh / sy,
                      'cx': (x + ww / 2) / sx, 'cy': y0 + (y + hh / 2) / sy})
    return words


def _multi_psm(img, y0, y1):
    """OCR one band and COMBINE psm modes (user's idea). psm 11 (sparse) is the most
    COMPLETE read — it splits adjacent faint tabs AND reads the '&' connector — so it is
    the primary; psm 6 only fills positions psm 11 missed. The '&' is kept so the later
    gap-split reassembles multi-word items ('Filme & Serien') while still separating real
    tabs. Junk (search/profile icons, fragments) is dropped by the word filter."""
    h = img.shape[0]
    y0 = max(0.0, y0)
    crop = cv2.createCLAHE(3.0, (8, 8)).apply(
        cv2.cvtColor(img[int(y0 * h):int(y1 * h), :], cv2.COLOR_BGR2GRAY))
    words = _tess_raw(crop, '11', y0)
    for w in _tess_raw(crop, '6', y0):          # fill any tab psm 11 dropped
        if not any(abs(w['cx'] - u['cx']) < SLOT_TOL for u in words):
            words.append(w)
    return [w for w in words if w['t'] in ('&', '-') or _looks_like_word(w['t'])]


def _underline_y(img):
    """Y (frac) of the nav-tab underline (red thin-wide bar) — the tabs sit just above
    it, giving a precise per-screen crop. None if no underline."""
    h, w = img.shape[:2]
    nb0, nb1 = int(0.04 * h), int(0.22 * h)
    red = ih._accent_mask(img)[nb0:nb1, :]
    band = cv2.morphologyEx(red, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3)))
    cnts, _ = cv2.findContours(band, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cnts:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw < 25 or bw > 0.25 * w or bh < 2 or bh > 12 or bw / max(bh, 1) < 6:
            continue
        if best is None or bw > best[0]:
            best = (bw, (nb0 + y + bh / 2) / h)
    return best[1] if best else None


def _ocr_words(img):
    """Read the nav row with the multi-psm combine over the two FIXED candidate bands
    (top-level menu vs per-screen sub-nav). Fixed bands are immune to the red CONTENT
    that fools an underline-based locator on content-heavy screens (e.g. home). Keep the
    band with the most items."""
    best = []
    for y0, y1 in NAV_CANDIDATE_BANDS:
        words = _multi_psm(img, y0, y1)
        if len(_row_items(words)) > len(_row_items(best)):
            best = words
    return best


def _row_items(words):
    """Count distinct items a word list would yield (for choosing the richest band)."""
    if not words:
        return []
    ws = sorted(words, key=lambda d: d['x'])
    items, group = [], [ws[0]]
    for prev, nxt in zip(ws, ws[1:]):
        if (nxt['x'] - (prev['x'] + prev['w'])) > ITEM_GAP:
            items.append(group)
            group = [nxt]
        else:
            group.append(nxt)
    items.append(group)
    return items


def extract_items(img):
    """Return nav/menu items as [{label,x,y,w,h,cx,cy}] (0-1). Rows are clustered by
    y; each row is split into items by x-gap; the NAV row(s) are those with >= a few
    items (a 1-2-word screen TITLE row is dropped)."""
    words = _ocr_words(img)
    if not words:
        return []
    # cluster into visual rows by y-center
    words.sort(key=lambda d: d['cy'])
    rows, cur = [], [words[0]]
    for d in words[1:]:
        if abs(d['cy'] - cur[-1]['cy']) <= ROW_TOL:
            cur.append(d)
        else:
            rows.append(cur)
            cur = [d]
    rows.append(cur)
    # split each row into items by x-gap
    row_items = []
    for row in rows:
        row.sort(key=lambda d: d['x'])
        items, group = [], [row[0]]
        for prev, nxt in zip(row, row[1:]):
            gap = nxt['x'] - (prev['x'] + prev['w'])
            # an '&'/'+' connector glues its neighbours into one item regardless of gap;
            # otherwise a gap above the threshold starts a new item.
            bridge = prev['t'] in ('&', '-') or nxt['t'] in ('&', '-')
            if gap > ITEM_GAP and not bridge:
                items.append(_mk_item(group))
                group = [nxt]
            else:
                group.append(nxt)
        items.append(_mk_item(group))
        row_items.append(items)
    # nav rows = those with enough items; else fall back to the richest row
    nav = [items for items in row_items if len(items) >= NAV_MIN_ITEMS]
    if not nav:
        nav = [max(row_items, key=len)]
    return [it for items in nav for it in items]


def _mk_item(words):
    x0 = min(d['x'] for d in words)
    y0 = min(d['y'] for d in words)
    x1 = max(d['x'] + d['w'] for d in words)
    y1 = max(d['y'] + d['h'] for d in words)
    # label cleanup: multi-psm leaves overlapping reads ("Filme Filme&Serien Serien").
    # Drop any token that is a substring of another token in the group, and exact repeats.
    toks = [d['t'] for d in sorted(words, key=lambda d: d['x'])]
    label_toks = []
    for t in toks:
        if any(t.lower() in u.lower() and len(t) < len(u) for u in toks):
            continue
        if label_toks and label_toks[-1].lower() == t.lower():
            continue
        label_toks.append(t)
    return {'label': ' '.join(label_toks) or toks[0],
            'x': x0, 'y': y0, 'w': x1 - x0, 'h': y1 - y0,
            'cx': (x0 + x1) / 2, 'cy': (y0 + y1) / 2}


def _ov_v(a, b):
    top, bot = max(a['y'], b['y']), min(a['y'] + a['h'], b['y'] + b['h'])
    return max(0.0, bot - top) / min(a['h'], b['h'])


def _ov_h(a, b):
    lft, rgt = max(a['x'], b['x']), min(a['x'] + a['w'], b['x'] + b['w'])
    return max(0.0, rgt - lft) / min(a['w'], b['w'])


def infer_edges(item, items):
    """LEFT/RIGHT/UP/DOWN nearest neighbour by the doc's cost function."""
    edges = {}
    pool = [b for b in items if b is not item]
    # cost = distance_in_direction + alignment_penalty (off-axis offset weighted)
    def best(cands, dist, align):
        return min(cands, key=lambda b: dist(b) + 2.0 * align(b)) if cands else None
    R = [b for b in pool if b['cx'] > item['cx'] and _ov_v(item, b) >= V_OVERLAP_MIN]
    L = [b for b in pool if b['cx'] < item['cx'] and _ov_v(item, b) >= V_OVERLAP_MIN]
    D = [b for b in pool if b['cy'] > item['cy'] and _ov_h(item, b) >= H_OVERLAP_MIN]
    U = [b for b in pool if b['cy'] < item['cy'] and _ov_h(item, b) >= H_OVERLAP_MIN]
    r = best(R, lambda b: b['cx'] - item['cx'], lambda b: abs(b['cy'] - item['cy']))
    l = best(L, lambda b: item['cx'] - b['cx'], lambda b: abs(b['cy'] - item['cy']))
    d = best(D, lambda b: b['cy'] - item['cy'], lambda b: abs(b['cx'] - item['cx']))
    u = best(U, lambda b: item['cy'] - b['cy'], lambda b: abs(b['cx'] - item['cx']))
    if r: edges['RIGHT'] = r['label']
    if l: edges['LEFT'] = l['label']
    if d: edges['DOWN'] = d['label']
    if u: edges['UP'] = u['label']
    return edges


def focused_item(items, img):
    """Which item is selected — the one under the focus underline x (or None)."""
    f = ih._focus_signature(img)
    if not items:
        return None, f
    if f.get('kind') == 'nav' and f.get('x') is not None:
        fx = f['x']
        in_x = [it for it in items if it['x'] <= fx <= it['x'] + it['w']]
        cand = in_x or items
        return min(cand, key=lambda it: abs(it['cx'] - fx)), f
    if f.get('kind') == 'box' and f.get('x') is not None:
        return min(items, key=lambda it: abs(it['cx'] - f['x']) + abs(it['cy'] - f.get('y', it['cy']))), f
    return None, f


def build_map(screen_id, items, focus_it):
    nodes = {}
    for it in items:
        nid = f"{screen_id}.{_slug(it['label'])}"
        e = {k: f"{screen_id}.{_slug(v)}" for k, v in infer_edges(it, items).items()}
        e['OK'] = f"ENTER:{it['label']}"
        e['BACK'] = 'UNKNOWN'
        nodes[nid] = {'label': it['label'], 'box': [round(it['x'], 3), round(it['y'], 3),
                      round(it['w'], 3), round(it['h'], 3)], 'edges': e,
                      'focused': bool(focus_it and it is focus_it)}
    return nodes


def render(img, items, focus_it, out):
    vis = img.copy()
    H, W = img.shape[:2]
    def c(it):
        return (int(it['cx'] * W), int(it['cy'] * H))
    # boxes
    for it in items:
        x, y = int(it['x'] * W), int(it['y'] * H)
        x2, y2 = int((it['x'] + it['w']) * W), int((it['y'] + it['h']) * H)
        col = (0, 0, 255) if it is focus_it else (0, 220, 0)
        cv2.rectangle(vis, (x, y), (x2, y2), col, 2)
        cv2.putText(vis, it['label'][:16], (x, max(12, y - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)
    # edges (arrows); color by direction
    dcol = {'RIGHT': (0, 255, 255), 'LEFT': (255, 255, 0),
            'DOWN': (255, 0, 255), 'UP': (200, 120, 0)}
    by_label = {it['label']: it for it in items}
    for it in items:
        for dirn, tgt in infer_edges(it, items).items():
            b = by_label.get(tgt)
            if b:
                cv2.arrowedLine(vis, c(it), c(b), dcol[dirn], 2, tipLength=0.04)
    cv2.imwrite(out, vis)


def extract(path):
    """Public API for the DOM exporter: screenshot path -> {screen_id, items}.
    Each item: {id, label, x, y, w, h, focused} with boxes normalized 0-1."""
    global _FW, _FH
    img = cv2.imread(path)
    if img is None:
        return {'screen_id': 'unknown', 'items': []}
    _FH, _FW = img.shape[:2]
    items = extract_items(img)
    focus_it, _ = focused_item(items, img)
    screen_id = os.path.splitext(os.path.basename(path))[0]
    out = []
    for i, it in enumerate(items):
        out.append({
            'id': f"{_slug(it['label'])}_{i}",
            'label': it['label'],
            'x': it['x'], 'y': it['y'], 'w': it['w'], 'h': it['h'],
            'focused': it is focus_it,
        })
    return {'screen_id': screen_id, 'items': out}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    screen_id = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') \
        else os.path.splitext(os.path.basename(path))[0]
    out = '/tmp/ui_infer_overlay.png'
    if '--out' in sys.argv:
        out = sys.argv[sys.argv.index('--out') + 1]
    img = cv2.imread(path)
    if img is None:
        print(f"cannot read {path}")
        sys.exit(1)
    global _FW, _FH
    _FH, _FW = img.shape[:2]
    items = extract_items(img)
    items.sort(key=lambda it: (round(it['cy'] / ROW_TOL), it['cx']))
    focus_it, focus = focused_item(items, img)
    nmap = build_map(screen_id, items, focus_it)

    print(f"screen = {screen_id}    focus = {focus}")
    print(f"items ({len(items)}): {[it['label'] for it in items]}")
    print(f"focused item = {focus_it['label'] if focus_it else None}\n")
    for nid, n in nmap.items():
        star = ' *FOCUS*' if n['focused'] else ''
        edges = '  '.join(f"{k}->{v}" for k, v in n['edges'].items())
        print(f"  {nid}{star}\n      {edges}")
    render(img, items, focus_it, out)
    json.dump({'screen': screen_id, 'nodes': nmap}, open('/tmp/ui_infer_map.json', 'w'), indent=1)
    print(f"\noverlay -> {out}\nmap json -> /tmp/ui_infer_map.json")


if __name__ == '__main__':
    main()
