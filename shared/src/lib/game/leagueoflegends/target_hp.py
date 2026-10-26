"""TASK-132: exact health of the unit selected by a LEFT click, read from the target frame at the top left (read-only).

Left-clicking a minion selects it (no attack); the frame at the top left then shows ``current / max`` health in white digits on the
health bar (e.g. ``406 / 465``; red bar = enemy, green = ally). The text sits in a fixed crop of a 1920x1200 screen. White pixels
are split into glyphs by column gaps and matched to templates built from labelled frames (:func:`build_templates`).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

TEXT_RECT = (180, 32, 350, 58)  # x0, y0, x1, y1 of the "current / max" text on a 1920x1200 screen
GLYPH_W, GLYPH_H = 12, 20
TEMPLATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "target_digits.npz")
_templates: Optional[Dict[str, Any]] = None


def glyphs(img_rgb: Any) -> List[Any]:
    """Left-to-right normalised glyph images (GLYPH_H x GLYPH_W, 0..1) of the white text; the ``/`` is a glyph too."""
    import cv2
    import numpy as np

    h, w = img_rgb.shape[:2]
    if (h, w) != (1200, 1920):
        return []
    x0, y0, x1, y1 = TEXT_RECT
    c = img_rgb[y0:y1, x0:x1].astype(np.int16)
    mask = ((c[..., 0] > 205) & (c[..., 1] > 205) & (c[..., 2] > 205) & (np.abs(c[..., 1] - c[..., 2]) < 25)).astype(np.uint8)
    cols = mask.sum(axis=0) > 0
    out, x, n = [], 0, len(cols)
    while x < n:
        if not cols[x]:
            x += 1
            continue
        a = x
        while x < n and cols[x]:
            x += 1
        seg = mask[:, a:x]
        ys = np.nonzero(seg.sum(axis=1))[0]
        if seg.sum() >= 12 and len(ys):
            g = seg[ys[0]:ys[-1] + 1].astype(np.float32)
            out.append((a, g))
    return out


def _norm(g: Any) -> Any:
    import cv2

    return cv2.resize(g, (GLYPH_W, GLYPH_H), interpolation=cv2.INTER_AREA)


def build_templates(labelled: Sequence[Tuple[Any, str]], path: str = TEMPLATE_FILE) -> Dict[str, Any]:
    """``labelled``: (RGB frame, "406/465") pairs. Saves the mean glyph per character (digits and ``/``)."""
    import numpy as np

    acc: Dict[str, List[Any]] = {}
    for img, label in labelled:
        gl = glyphs(img)
        chars = list(label.replace(" ", ""))
        if len(gl) != len(chars):
            continue
        for (_, g), ch in zip(gl, chars):
            acc.setdefault(ch, []).append(_norm(g))
    t = {ch: np.mean(v, axis=0) for ch, v in acc.items()}
    np.savez(path, **{("slash" if ch == "/" else ch): v for ch, v in t.items()})
    global _templates
    _templates = t
    return t


def _load() -> Dict[str, Any]:
    global _templates
    if _templates is None:
        import numpy as np

        z = np.load(TEMPLATE_FILE)
        _templates = {("/" if k == "slash" else k): z[k] for k in z.files}
    return _templates


def read_target_health(img_rgb: Any) -> Optional[Tuple[int, int]]:
    """``(current, max)`` health of the selected unit, or None when nothing readable is selected."""
    import numpy as np

    gl = glyphs(img_rgb)
    if not 5 <= len(gl) <= 9:
        return None
    t = _load()
    chars = ""
    for _, g in gl:
        gn = _norm(g)
        best, bd = None, 1e9
        for ch, tpl in t.items():
            d = float(np.abs(gn - tpl).mean())
            if d < bd:
                best, bd = ch, d
        if best is None or bd > 0.25:
            return None
        chars += best
    if chars.count("/") != 1:
        return None
    cur, mx = chars.split("/")
    if not cur or not mx or not (cur + mx).isdigit():
        return None
    cur_i, max_i = int(cur), int(mx)
    return (cur_i, max_i) if 0 <= cur_i <= max_i <= 5000 else None
