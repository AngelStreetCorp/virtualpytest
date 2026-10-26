"""TASK-131: exact CS from the in-game HUD counter (top right, the yellow number beside the minion icon).

The Live Client Data API ``creepScore`` only moves in steps of 10, which makes CS/min useless on a 5-minute game.
The HUD counter shows every CS. It is read from a fixed crop (fractions of the screenshot, so a 1920x1200 grab and the
960x600 saved shots give the same answer): yellow pixels, split into digits by column gaps, each digit matched to
template glyphs (``cs_digits.npz``, built by :func:`build_templates` from labelled frames). Read-only.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

# (x0, y0, x1, y1) as fractions of the screenshot: the number only, right of the minion icon
CS_RECT = (0.9185, 0.0017, 0.952, 0.0267)
GLYPH_W, GLYPH_H = 10, 16
TEMPLATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cs_digits.npz")
_templates: Optional[Dict[str, Any]] = None


def _crop(img: Any) -> Any:
    h, w = img.shape[:2]
    return img[max(0, int(CS_RECT[1] * h)):int(CS_RECT[3] * h) + 1, int(CS_RECT[0] * w):int(CS_RECT[2] * w) + 1]


def glyphs(img_bgr: Any) -> List[Any]:
    """Left-to-right normalised digit images (GLYPH_H x GLYPH_W floats 0..1) of the yellow counter."""
    import cv2
    import numpy as np

    c = _crop(img_bgr)
    if c.size == 0:
        return []
    scale = 48.0 / c.shape[0]
    big = cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    hsv = cv2.cvtColor(big, cv2.COLOR_BGR2HSV)
    mask = (cv2.inRange(hsv, (15, 70, 150), (38, 255, 255)) > 0).astype(np.uint8)
    cols = mask.sum(axis=0) > 0
    out, x, n = [], 0, len(cols)
    while x < n:
        if cols[x]:
            x0 = x
            while x < n and cols[x]:
                x += 1
            seg = mask[:, x0:x]
            ys = np.nonzero(seg.sum(axis=1))[0]
            if seg.sum() >= 40 and len(ys):
                g = seg[ys[0]:ys[-1] + 1].astype(np.float32)
                out.append(cv2.resize(g, (GLYPH_W, GLYPH_H), interpolation=cv2.INTER_AREA))
        else:
            x += 1
    return out


def _load() -> Dict[str, Any]:
    global _templates
    if _templates is None:
        import numpy as np

        z = np.load(TEMPLATE_FILE)
        _templates = {k: z[k] for k in z.files}
    return _templates


def read_cs(img_bgr: Any) -> Optional[int]:
    """Exact CS shown on the HUD, or None when the counter is not readable (menu, loading screen, covered)."""
    import numpy as np

    gl = glyphs(img_bgr)
    if not gl or len(gl) > 3:
        return None
    t = _load()
    s = ""
    for g in gl:
        best, bd = None, 1e9
        for d, tpl in t.items():
            dist = float(np.abs(g - tpl).mean())
            if dist < bd:
                best, bd = d, dist
        if best is None or bd > 0.25:
            return None
        s += best
    return int(s)


def build_templates(labelled: Sequence[Tuple[Any, int]], path: str = TEMPLATE_FILE) -> Dict[str, int]:
    """``labelled`` = [(bgr image, true CS)]; averages every digit glyph per digit value. Returns samples per digit."""
    import numpy as np

    acc: Dict[str, List[Any]] = {}
    for img, cs in labelled:
        gl = glyphs(img)
        if len(gl) == len(str(cs)):
            for d, g in zip(str(cs), gl):
                acc.setdefault(d, []).append(g)
    np.savez(path, **{d: np.mean(v, axis=0) for d, v in acc.items()})
    return {d: len(v) for d, v in sorted(acc.items())}
