"""Spectator stats panel (bottom left, 1920x1200) of the followed champion: HP, stats, level, ability ranks/readiness."""
import re
import numpy as np
from PIL import Image
import pytesseract
R = {  # x0, y0, x1, y1 at 1920x1200 (measured on game 8018174981)
    "hp_text": (98, 947, 190, 967), "ad": (225, 945, 248, 960), "armor": (225, 968, 248, 983), "as": (225, 990, 256, 1005),
    "mr": (283, 968, 304, 983), "ms": (283, 990, 310, 1005), "level": (64, 995, 79, 1010),
    "rank_Q": (70, 1049, 86, 1066), "rank_W": (113, 1049, 128, 1066), "rank_E": (156, 1049, 171, 1066), "rank_R": (199, 1049, 214, 1066)}
ICON = {"Q": (60, 1022, 97, 1056), "W": (103, 1022, 140, 1056), "E": (147, 1022, 183, 1056), "R": (188, 1022, 225, 1056)}
HP_BAR = (84, 949, 196, 963)

def _ocr(img, box, allow="0123456789./", scale=5, white=False):
    crop = img.crop(box).convert("RGB")
    if white:  # white text on the green HP bar: the min channel separates it from the green
        crop = Image.fromarray(np.array(crop).min(axis=2).astype(np.uint8))
    c = crop.convert("L").resize(((box[2] - box[0]) * scale, (box[3] - box[1]) * scale), Image.LANCZOS)
    a = np.array(c); a = np.where(a > (165 if white else 125), 0, 255).astype(np.uint8)  # light glyphs -> black on white
    a = np.pad(a, 20, constant_values=255)
    return pytesseract.image_to_string(Image.fromarray(a), config=f"--psm 7 -c tessedit_char_whitelist={allow}").strip()

def _num(s, f=int):
    m = re.search(r"\d+(\.\d+)?", s or ""); 
    try: return f(m.group(0)) if m else None
    except ValueError: return None

def hp_bar_frac(img):
    a = np.array(img.crop(HP_BAR).convert("RGB")).astype(int)
    row = a[a.shape[0] // 2]
    green = (row[:, 1] > 140) & (row[:, 0] < 120) & (row[:, 1] - row[:, 0] > 60)
    xs = np.nonzero(green)[0]
    return round((xs.max() + 1) / len(row), 3) if len(xs) else 0.0

def icon_ready(img, k):
    """Ready icons are in colour; on cooldown or rank 0 they are greyed (low saturation)."""
    a = np.array(img.crop(ICON[k]).convert("HSV")).astype(int)
    return bool((a[..., 1] > 90).mean() > 0.25)

def read_panel(img):
    out = {}
    t = _ocr(img, R["hp_text"], white=True)
    m = re.match(r"(\d+)\s*/\s*(\d+)", t.replace(" ", ""))
    out["hp"], out["hp_max"] = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    out["hp_bar"] = hp_bar_frac(img)
    for k in ("ad", "armor", "ms"):  # MR unused; level comes from Live Client Data
        out[k] = _num(_ocr(img, R[k], "0123456789"))
    out["as"] = _num(_ocr(img, R["as"], "0123456789."), float)
    for k in "QWER":
        out["rank_" + k] = _num(_ocr(img, R["rank_" + k], "012345", white=True))
        out["ready_" + k] = icon_ready(img, k)
        cd = _num(_ocr(img, ICON[k], "0123456789", white=True)) if not out["ready_" + k] else None
        out["cd_" + k] = cd if cd is not None and cd < 200 else None
    return out


# --- digit templates (tesseract confuses 3/5 on this font) ------------------------------------------------------------
import os as _os, cv2 as _cv2
_PD = np.load(_os.path.join(_os.path.dirname(__file__), "panel_digits.npz")); _PT, _PY = _PD["T"], _PD["Y"]

def _tmpl_read(img, box, white_on_green=False, min_corr=0.55):
    """Digits (and '/') of a panel field by template; junk glyphs skipped; None when a glyph matches nothing."""
    a = np.array(img.crop(box).convert("RGB")).astype(int)
    m = (a.min(axis=2) > 170) if white_on_green else (a.mean(axis=2) > 150) & (a.min(axis=2) > 95)
    xs = np.nonzero(m.sum(axis=0) > 0)[0]
    if not len(xs): return ""
    groups, s, p = [], xs[0], xs[0]
    for x in xs[1:]:
        if x - p > 1: groups.append((s, p)); s = x
        p = x
    groups.append((s, p)); out = ""; grey = a.mean(axis=2)
    for g0, g1 in groups:
        sub = m[:, g0:g1 + 1]; ys = np.nonzero(sub.sum(axis=1))[0]
        if len(ys) < 5: continue
        crop = grey[ys[0]:ys[-1] + 1, max(0, g0 - 1):g1 + 2]
        v = _cv2.resize(crop.astype(np.float32), (12, 16), interpolation=_cv2.INTER_AREA).flatten(); v = (v - v.mean()) / (v.std() + 1e-6)
        c = _PT @ v / len(v); i = int(c.argmax())
        if c[i] < min_corr: return None
        y = int(_PY[i])
        if y == -1: continue
        out += "/" if y == 10 else str(y)
    return out

def read_panel_t(img):
    """Template version of read_panel."""
    out = {}
    s = _tmpl_read(img, R["hp_text"], white_on_green=True) or ""
    m = re.match(r"(\d+)/(\d+)$", s)
    out["hp"], out["hp_max"] = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    out["hp_bar"] = hp_bar_frac(img)
    for k in ("ad", "armor", "ms"):
        s = _tmpl_read(img, R[k]); out[k] = int(s) if s and s.isdigit() else None
    s = _tmpl_read(img, R["as"]); out["as"] = float(s[0] + "." + s[1:]) if s and s.isdigit() and len(s) >= 2 else None
    for k in "QWER":
        s = _tmpl_read(img, R["rank_" + k]); out["rank_" + k] = int(s) if s and s.isdigit() and int(s) <= 5 else None
        out["ready_" + k] = icon_ready_t(img, k)
        out["cd_" + k] = None if out["ready_" + k] else cooldown_s(img, k)
    return out


# --- cooldown seconds on the ability icons (white digits, crossed by a thin clock hand) ---------------------------------
_CD = np.load(_os.path.join(_os.path.dirname(__file__), "cd_digits.npz")); _CT, _CY = _CD["T"], _CD["Y"]
READY_SAT = 0.45  # coloured share of a ready icon: 0.53-0.75; greyed (cooldown / rank 0): <= 0.38 (W is bluish even greyed)

def icon_ready_t(img, k):
    a = np.array(img.crop(ICON[k]).convert("HSV")).astype(int)
    return bool((a[..., 1] > 90).mean() > READY_SAT)

def cooldown_s(img, k):
    """Seconds left on a greyed icon (digit templates); None when no digit."""
    x0, y0, x1, y1 = ICON[k]
    a = np.array(img.crop((x0 + 1, y0 + 4, x1 - 1, y0 + 26)).convert("RGB")).astype(int)
    m = a.min(axis=2) > 195
    n, lab, stats, _ = _cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
    gl = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if h < 9 or h > 13 or w > 9 or area < 12 or area / (w * h) < 0.25: continue
        v = _cv2.resize((lab[y:y + h, x:x + w] == i).astype(np.uint8) * 255, (6, 10), interpolation=_cv2.INTER_NEAREST).flatten() > 127
        d = np.abs(_CT - v[None, :]).sum(axis=1); j = int(d.argmin())
        if d[j] <= 12 and _CY[j] >= 0: gl.append((x, str(int(_CY[j]))))
    return int("".join(c for _, c in sorted(gl))) if gl else None
