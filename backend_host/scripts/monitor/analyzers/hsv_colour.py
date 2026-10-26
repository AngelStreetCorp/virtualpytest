"""Car colour from an HSV histogram of the box (no model): type hsv_colour, attr `colour`.

Pixels of the central 60 % of the box (cuts the background at the edges) are put in one of
white / black / grey / red / blue / green / yellow / other by saturation, value and hue (OpenCV hue 0-179);
the most frequent class wins. Hue bands: red 0-9 and 165-179, yellow 20-34, green 35-84, blue 90-129;
orange, cyan and purple fall in `other`.
"""
from typing import Dict, Sequence

import cv2
import numpy as np

COLOURS = ('white', 'black', 'grey', 'red', 'blue', 'green', 'yellow', 'other')

V_BLACK = 60        # value below this: black whatever the hue
S_GREY = 45         # saturation below this: white / grey / black by value
V_WHITE = 170


def classify_crop(crop_bgr: np.ndarray, allowed: Sequence[str] = COLOURS) -> str:
    h, w = crop_bgr.shape[:2]
    if h < 2 or w < 2:
        return 'other'
    y0, y1 = int(h * 0.2), max(int(h * 0.8), int(h * 0.2) + 1)
    x0, x1 = int(w * 0.2), max(int(w * 0.8), int(w * 0.2) + 1)
    hsv = cv2.cvtColor(np.ascontiguousarray(crop_bgr[y0:y1, x0:x1]), cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0].astype(np.int32), hsv[..., 1].astype(np.int32), hsv[..., 2].astype(np.int32)

    black = val < V_BLACK
    achro = ~black & (sat < S_GREY)
    white = achro & (val >= V_WHITE)
    grey = achro & (val < V_WHITE)
    chroma = ~black & ~achro
    counts: Dict[str, int] = {
        'black': int(black.sum()),
        'white': int(white.sum()),
        'grey': int(grey.sum()),
        'red': int((chroma & ((hue < 10) | (hue >= 165))).sum()),
        'yellow': int((chroma & (hue >= 20) & (hue < 35)).sum()),
        'green': int((chroma & (hue >= 35) & (hue < 85)).sum()),
        'blue': int((chroma & (hue >= 90) & (hue < 130)).sum()),
    }
    counts['other'] = int(chroma.sum()) - sum(counts[c] for c in ('red', 'yellow', 'green', 'blue'))
    best = max((c for c in counts if c in allowed), key=lambda c: counts[c], default='other')
    return best if counts.get(best, 0) > 0 else 'other'


class HsvColour:
    """type: hsv_colour — keys: attr (default 'colour'), classes."""

    def __init__(self, attr: str = 'colour', classes: Sequence[str] = COLOURS):
        self.attr = attr
        self.classes = tuple(classes)

    def classify(self, frame_bgr: np.ndarray, bbox) -> str:
        x, y, w, h = [int(round(v)) for v in bbox]
        return classify_crop(frame_bgr[max(0, y):y + h, max(0, x):x + w], self.classes)
