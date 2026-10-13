"""
Pixel court reader for jakesgordon.com Tetris, from any captured frame.

The court is a canvas with a dark 2 px border and a 1:2 aspect, drawn over a pale textured
background. Pieces are flat, saturated colours (cyan, blue, orange, yellow, green, purple,
red) with a black outline. So:
- locate: the dark connected component whose bounding box is ~1 wide : 2 high;
- read: a cell is filled when the median colour of its inner area is saturated.
"""

from typing import Optional, Tuple

import cv2
import numpy as np

from .board import NX, NY, Court
from shared.src.lib.utils import cv2_io

BORDER_PX = 2
DARK_SUM = 200        # B+G+R below this is "dark" (border #333, block outlines)
MIN_COURT_H = 200
MIN_SATURATION = 90   # max(RGB) - min(RGB): pieces >= 128, the empty-cell texture ~40-60
INNER = 0.25          # sample the cell's centre, away from the black outline


def locate_court(img: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """(x, y, w, h) of the court inside its border, or None."""
    dark = (img.astype(np.int32).sum(axis=2) < DARK_SUM).astype(np.uint8) * 255
    count, _, stats, _ = cv2.connectedComponentsWithStats(dark)
    best = None
    for i in range(1, count):
        x, y, w, h, _ = stats[i]
        if h >= MIN_COURT_H and 0.45 < w / h < 0.55 and (best is None or h > best[3]):
            best = (int(x), int(y), int(w), int(h))
    if best is None:
        return None
    x, y, w, h = best
    return x + BORDER_PX, y + BORDER_PX, w - 2 * BORDER_PX, h - 2 * BORDER_PX


def read_court(image_path: str) -> Optional[Court]:
    """The court as court[x][y] (1 = filled), or None when no court is found on the frame."""
    img = cv2_io.imread(image_path)
    if img is None:
        return None
    rect = locate_court(img)
    if rect is None:
        return None
    x0, y0, w, h = rect
    cw, ch = w / NX, h / NY
    court = [[0] * NY for _ in range(NX)]
    for cx in range(NX):
        for cy in range(NY):
            xa, ya = int(x0 + cw * (cx + INNER)), int(y0 + ch * (cy + INNER))
            xb, yb = int(x0 + cw * (cx + 1 - INNER)), int(y0 + ch * (cy + 1 - INNER))
            patch = img[ya:max(ya + 1, yb), xa:max(xa + 1, xb)].reshape(-1, 3)
            b, g, r = np.median(patch, axis=0)
            court[cx][cy] = 1 if max(r, g, b) - min(r, g, b) >= MIN_SATURATION else 0
    return court


def diff_cells(a: Court, b: Court) -> int:
    return sum(1 for x in range(NX) for y in range(NY) if a[x][y] != b[x][y])
