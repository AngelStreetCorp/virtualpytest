#!/usr/bin/env python3
"""TASK-103 goal 3 reference: read the broadcaster's (burnt-in) subtitles from collected 1280x720 frames.

Subtitle = white text in a black box at the bottom centre. For every frame (frame time = file mtime, ns) we
threshold the bottom region to white, OCR it (tesseract, German) when the crop changed, and merge runs of
frames with the same text into events {start, end, text}. Start = midpoint between the last frame without and
the first frame with the text (so the error of the reference is at most half a frame interval, about 0.11 s).

  task103_subtitle_ref.py --frames <run>/frames --out <run>/subtitle_events.json [--lang deu]
"""
import argparse, difflib, glob, json, os, re
import cv2, numpy as np, pytesseract

Y0, Y1, X0, X1 = 540, 705, 160, 1120  # subtitle band of a 1280x720 frame


def find_box(img):
    """White text line on a black box (also in dark scenes, where the box merges with the picture).

    White connected components of glyph size are grouped by row; the biggest row with >= 4 glyphs whose
    surroundings are dark is the subtitle. Returns the white-text mask of that row or None.
    """
    gray = cv2.cvtColor(img[Y0:Y1, X0:X1], cv2.COLOR_BGR2GRAY)
    white = (gray > 205).astype(np.uint8) * 255
    n, lab, st, _ = cv2.connectedComponentsWithStats(white, connectivity=8)
    glyphs = [(st[i, 1] + st[i, 3] / 2, i) for i in range(1, n)
              if 12 <= st[i, 3] <= 50 and 2 <= st[i, 2] <= 48 and 0.12 <= st[i, 4] / (st[i, 2] * st[i, 3]) <= 0.95]
    best = None
    for cy, _ in glyphs:
        row = [i for c, i in glyphs if abs(c - cy) <= 9]
        if len(row) < 4:
            continue
        x0 = min(st[i, 0] for i in row); x1 = max(st[i, 0] + st[i, 2] for i in row)
        y0 = min(st[i, 1] for i in row); y1 = max(st[i, 1] + st[i, 3] for i in row)
        if x1 - x0 < 50 or (best and len(row) <= best[0]):
            continue
        around = gray[max(0, y0 - 6):y1 + 6, max(0, x0 - 6):x1 + 6]
        if np.percentile(around, 60) > 45:  # not on a dark box
            continue
        best = (len(row), (x0, y0, x1, y1))
    if best is None:
        return None
    x0, y0, x1, y1 = best[1]
    return white[max(0, y0 - 6):y1 + 6, max(0, x0 - 6):x1 + 6]


def read_text(img):
    white = find_box(img)
    return ('', None) if white is None else (None, white)


def ocr(white, lang):
    inv = cv2.copyMakeBorder(cv2.bitwise_not(white), 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    inv = cv2.resize(inv, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    d = pytesseract.image_to_data(inv, lang=lang, config='--psm 6', output_type=pytesseract.Output.DICT)
    words = [(w, float(c)) for w, c in zip(d['text'], d['conf']) if w.strip() and float(c) >= 50]
    txt = ' '.join(w for w, _ in words)
    letters = re.sub(r'[^A-Za-zÄÖÜäöüß]', '', txt)
    return txt if len(letters) >= 3 else ''


def norm(t):
    return re.sub(r'[^a-zäöüß ]', '', t.lower()).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--frames', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--lang', default='deu')
    ap.add_argument('--t-min', type=float, default=0, help='only frames with mtime >= this epoch')
    ap.add_argument('--t-max', type=float, default=1e18)
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.frames, 'capture_*.jpg')))
    frames = [(os.stat(f).st_mtime, f) for f in files]
    frames = [x for x in frames if a.t_min <= x[0] <= a.t_max]
    events, cur, prev_white, prev_txt, prev_t, n_ocr = [], None, None, '', None, 0
    for t, f in frames:
        img = cv2.imread(f)
        if img is None:
            continue
        txt, white = read_text(img)
        if txt is None:
            if prev_white is not None and prev_txt and prev_white.shape == white.shape and np.mean(white != prev_white) < 0.01:
                txt = prev_txt
            else:
                txt = ocr(white, a.lang); n_ocr += 1
        prev_white, prev_txt = white, txt
        if txt and cur and difflib.SequenceMatcher(None, norm(txt), norm(cur['text'])).ratio() >= 0.8:
            cur['end'] = t
        else:
            if cur:
                events.append(cur); cur = None
            if txt:
                cur = {'start': (t + (prev_t if prev_t else t)) / 2, 'end': t, 'text': txt, 'first_frame_t': t}
        prev_t = t
    if cur:
        events.append(cur)
    json.dump({'n_frames': len(frames), 'n_ocr': n_ocr, 'events': events}, open(a.out, 'w'), indent=1, ensure_ascii=False)
    print(f'{len(frames)} frames, {n_ocr} OCR calls, {len(events)} subtitle events')


if __name__ == '__main__':
    main()
