"""Spectator HUD readers (1920x1200): game clock, scoreboard CS/KDA per row. Tesseract with colour masks."""
import re
import numpy as np
from PIL import Image
import pytesseract

CLOCK = (930, 86, 1000, 107)
# scoreboard rows (always-on scoreboard): row centres y; CS digits column per side
SB_ROWS = [970, 1014, 1058, 1102, 1146]
SB_CS_X = {"200": (1026, 1072), "100": (868, 914)}   # red side CS right of the portrait column, blue side left of it
SB_KDA_X = {"200": (1080, 1150), "100": (795, 870)}

def _prep(crop, mode, scale=6, thr=120):
    """Bright glyphs on a dark HUD: smooth upscale of the grey image, then threshold to black text on white."""
    g = crop.convert("L")
    g = g.resize((g.width * scale, g.height * scale), Image.LANCZOS)
    a = np.array(g)
    out = np.where(a > thr, 0, 255).astype(np.uint8)
    return Image.fromarray(np.pad(out, 20, constant_values=255))

def ocr(img, box, mode="white", allow="0123456789"):
    return pytesseract.image_to_string(_prep(img.crop(box), mode), config=f"--psm 7 -c tessedit_char_whitelist={allow}").strip()

def clock(img):
    s = ocr(img, CLOCK, "white", "0123456789:")
    m = re.match(r"(\d{1,2}):?(\d{2})$", s.replace(" ", ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None

def sb_cs(img, team, row=0):
    x0, x1 = SB_CS_X[team]; y = SB_ROWS[row]
    s = ocr(img, (x0, y - 12, x1, y + 12), "yellow")
    return int(s) if s.isdigit() else None

def sb_kda(img, team, row=0):
    x0, x1 = SB_KDA_X[team]; y = SB_ROWS[row]
    s = ocr(img, (x0, y - 12, x1, y + 12), "white", "0123456789/")
    m = re.match(r"(\d+)/(\d+)/(\d+)", s)
    return tuple(map(int, m.groups())) if m else None


import os as _os, cv2 as _cv2
GW, GH = 12, 16

def _cell_glyphs(cell):
    """Glyph grey crops (bright yellow digits; the dark shadow is excluded by the stricter mask)."""
    a = np.array(cell.convert("RGB")).astype(int)
    m = (a[..., 0] > 190) & (a[..., 1] > 160) & (a[..., 2] < 170)
    xs = np.nonzero(m.sum(axis=0) > 0)[0]
    if not len(xs): return []
    groups, s, p = [], xs[0], xs[0]
    for x in xs[1:]:
        if x - p > 1: groups.append((s, p)); s = x
        p = x
    groups.append((s, p)); out = []
    grey = a.mean(axis=2)
    for g0, g1 in groups:
        sub = m[:, g0:g1 + 1]; ys = np.nonzero(sub.sum(axis=1))[0]
        if len(ys) < 8 or g1 - g0 < 1: continue
        crop = grey[ys[0]:ys[-1] + 1, max(0, g0 - 1):g1 + 2]
        v = _cv2.resize(crop.astype(np.float32), (GW, GH), interpolation=_cv2.INTER_AREA).flatten()
        v = (v - v.mean()) / (v.std() + 1e-6)
        out.append(v)
    return out

_DP = _os.path.join(_os.path.dirname(__file__), "cs_digits_grey.npz")
_DG = np.load(_DP) if _os.path.exists(_DP) else None

def sb_cs_digits(img, team, row=0, min_corr=0.6):
    """Scoreboard CS by grey-level digit templates; None when a glyph matches no digit well."""
    if _DG is None: return None
    x0, x1 = SB_CS_X[team]; y = SB_ROWS[row]; ds = []
    for v in _cell_glyphs(img.crop((x0, y - 13, x1, y + 13))):
        c = _DG["T"] @ v / len(v); i = int(c.argmax())
        if c[i] < min_corr: return None
        ds.append(str(int(_DG["Y"][i])))
    return int("".join(ds)) if ds else None
