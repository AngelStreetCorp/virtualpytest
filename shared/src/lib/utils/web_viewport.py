"""Where the browser page sits inside a web host's captured desktop frame (FINGERPRINT.md "Web fingerprints").

A web device's capture is the whole desktop: taskbar, clock, tab strip and address bar around the page. The full-frame dHash
of ten different pages is therefore nearly the same picture (ten screens scored 0 bits against each other). The fingerprint
of a web screen is computed on the page area only; the box comes from the browser itself (window position and inner size),
so it holds at any window size, with the window moved, or with a different capture scale.
"""
from typing import Any, Dict, Optional, Tuple

# Evaluated in the page; a plain object of CSS pixels (screen.* is the whole display the window sits on).
VIEWPORT_JS = ("({sx: window.screenX, sy: window.screenY, ow: window.outerWidth, oh: window.outerHeight, "
               "iw: window.innerWidth, ih: window.innerHeight, sw: screen.width, sh: screen.height})")

MIN_SIDE_PX = 64


def viewport_box(m: Dict[str, Any], img_w: int, img_h: int) -> Optional[Tuple[int, int, int, int]]:
    """(x, y, w, h) of the page area in the frame's pixels, or None when the metrics are unusable.

    The window's side and bottom borders are equal (outerWidth - innerWidth) / 2; everything else the browser
    adds to outerHeight (tabs, address bar) is on top. The frame is the screen scaled to img_w x img_h."""
    try:
        sx, sy, ow, oh, iw, ih, sw, sh = (float(m[k]) for k in ('sx', 'sy', 'ow', 'oh', 'iw', 'ih', 'sw', 'sh'))
    except (KeyError, TypeError, ValueError):
        return None
    if min(iw, ih, sw, sh, img_w, img_h) <= 0:
        return None
    border = max((ow - iw) / 2.0, 0.0)
    x = sx + border
    y = sy + (oh - ih) - border
    kx, ky = img_w / sw, img_h / sh
    x0, y0 = max(int(round(x * kx)), 0), max(int(round(y * ky)), 0)
    x1, y1 = min(int(round((x + iw) * kx)), img_w), min(int(round((y + ih) * ky)), img_h)
    if x1 - x0 < MIN_SIDE_PX or y1 - y0 < MIN_SIDE_PX:
        return None
    return x0, y0, x1 - x0, y1 - y0


def crop_to_box(img, box):
    """The page area of a frame (numpy image), or the frame itself when there is no box."""
    if img is None or not box:
        return img
    x, y, w, h = box
    return img[y:y + h, x:x + w]
