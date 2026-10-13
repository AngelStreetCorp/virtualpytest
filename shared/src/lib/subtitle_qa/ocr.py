"""Subtitle OCR: same recipe as backend_host/scripts/subtitle_monitor.py (bottom-band ROI,
tesseract, per-word confidence filter), as a pure function over one image."""
from typing import Optional

import cv2
import numpy as np

from .judge import OcrResult
from .srt import normalize

MIN_WORD_CONF = 25   # per-word; has_text() separately requires mean_conf >= 60
ROI = (0.05, 0.62, 0.90, 0.36)   # x, y, w, h as fractions of the frame
TESS_LANG = {'en': 'eng', 'de': 'deu', 'fr': 'fra'}

try:
    import pytesseract
except ImportError:  # checked at call time
    pytesseract = None
try:
    from langdetect import DetectorFactory, detect_langs
    DetectorFactory.seed = 0
except ImportError:
    detect_langs = None


def _luminance(bgr: np.ndarray) -> np.ndarray:
    b, g, r = [bgr[..., i].astype(np.float32) / 255.0 for i in range(3)]
    lin = lambda c: np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def roi_crop(img: np.ndarray):
    h, w = img.shape[:2]
    x, y, rw, rh = ROI
    x0, y0 = int(w * x), int(h * y)
    return img[y0:y0 + int(h * rh), x0:x0 + int(w * rw)], (x0, y0)


def read_subtitle(img: np.ndarray, lang: str = 'en') -> OcrResult:
    """OCR the subtitle band of a BGR frame. White text on a dark outline is isolated by a
    brightness mask; tesseract reads the inverted mask (black text, white page)."""
    if pytesseract is None:
        raise RuntimeError('pytesseract is not installed')
    crop, _ = roi_crop(img)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # subtitle glyphs = small bright connected components; scene content (lamps, sky, rails) forms big
    # or very long blobs and is dropped by size, which keeps thin strokes intact
    h_img = gray.shape[0]
    bright = (gray >= 200).astype(np.uint8)
    dark_near = cv2.dilate((gray <= 70).astype(np.uint8), np.ones((5, 5), np.uint8))
    bright = bright & dark_near
    n, lab, st, _ = cv2.connectedComponentsWithStats(bright, connectivity=8)
    keep = np.zeros(n, np.uint8)
    for i in range(1, n):
        w, h, area = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT], st[i, cv2.CC_STAT_AREA]
        if h <= 0.30 * h_img and w <= 0.30 * h_img * 2 and area >= 2 and area <= 0.04 * bright.size:
            keep[i] = 1
    mask = cv2.morphologyEx(keep[lab], cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8)) * 255
    if mask.mean() < 0.15:     # < 0.06% text pixels: no subtitle
        return OcrResult()
    mask = _text_band(mask)
    if mask is None:
        return OcrResult()
    big = cv2.resize(mask, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    page = cv2.copyMakeBorder(255 - big, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    data = pytesseract.image_to_data(page, lang=TESS_LANG.get(lang, 'eng'), config='--psm 6',
                                     output_type=pytesseract.Output.DICT)
    words, confs = [], []
    for txt, conf in zip(data['text'], data['conf']):
        txt = txt.strip()
        try:
            conf = float(conf)
        except ValueError:
            continue
        if txt and conf >= MIN_WORD_CONF and any(ch.isalnum() for ch in txt):
            words.append(txt)
            confs.append(conf)
    text = ' '.join(words)
    if not words:
        return OcrResult()
    return OcrResult(text, len(words), float(np.mean(confs)), _contrast(crop, mask), _lang(text))


def _text_band(mask: np.ndarray) -> Optional[np.ndarray]:
    """Keep the rows that hold subtitle lines (dense rows of glyph pixels, up to two lines) and blank the rest."""
    rows = (mask > 0).sum(axis=1)
    dense = rows >= 12
    groups, start = [], None
    for y, d in enumerate(list(dense) + [False]):
        if d and start is None:
            start = y
        elif not d and start is not None:
            if y - start >= 8:
                groups.append((start, y, int(rows[start:y].sum())))
            start = None
    if not groups:
        return None
    top = max(groups, key=lambda g: g[2])
    keep = [g for g in groups if g is top or (abs(g[0] - top[1]) <= 40 or abs(top[0] - g[1]) <= 40) and g[2] >= 0.3 * top[2]]
    out = np.zeros_like(mask)
    for y0, y1, _ in keep:
        out[max(y0 - 4, 0):y1 + 4] = mask[max(y0 - 4, 0):y1 + 4]
    return out


def _contrast(crop: np.ndarray, mask: np.ndarray) -> Optional[float]:
    """WCAG ratio between the text pixels and the ring of pixels around them."""
    if mask.sum() == 0:
        return None
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    outer = cv2.dilate(mask, k, iterations=1)
    ring = (outer > 0) & (mask == 0)
    if ring.sum() < 20:
        return None
    lum = _luminance(crop)
    fg, bg = float(np.median(lum[mask > 0])), float(np.percentile(lum[ring], 20))
    hi, lo = max(fg, bg), min(fg, bg)
    return (hi + 0.05) / (lo + 0.05)


def _lang(text: str) -> Optional[str]:
    if detect_langs is None or len(normalize(text)) < 20:
        return None
    try:
        best = detect_langs(text)[0]
        return best.lang if best.prob >= 0.9 else None
    except Exception:
        return None


def ocr_info(lang: str = 'en') -> dict:
    """What read the subtitles, for the report: engine, version, language data and the preprocessing."""
    try:
        version = str(pytesseract.get_tesseract_version()) if pytesseract else 'not installed'
    except Exception:
        version = 'unknown'
    return {'engine': 'tesseract', 'version': version, 'lang_data': TESS_LANG.get(lang, 'eng'), 'page_mode': 'psm 6',
            'roi': f'x {ROI[0]:.0%}, y {ROI[1]:.0%}, w {ROI[2]:.0%}, h {ROI[3]:.0%} of the frame',
            'preprocess': 'glyph mask (bright pixels with a dark outline), text rows only, 2x upscale',
            'min_word_conf': MIN_WORD_CONF}
