"""
Profile-driven Tetris frame reader (TASK-51 G2).

Reads a captured frame and returns:

    {
        "court":    court[x][y] (0/1) — 1 = a filled cell, including the
                    active piece on top of the stack. The ghost is ignored
                    (a translucent ghost is below the locked-cell saturation
                    threshold),
        "next":     ["T", "J", ...]  — one piece name per next-queue slot,
                    identified by *shape* (4-cell pattern), not by colour,
        "frame":    image_path,      — kept for the runner's KPI/report
    }

The `VisionProfile` (profiles.py) holds everything that varies between games:
how the court is located (auto-detect on jakesgordon, fixed ROI on the
Tetris-99 / NSO frames), the cell size in pixels, the saturation rule that
counts a cell as filled, and the next-queue ROIs. The reader is the same
for every profile — it just defers to those numbers.

Identifying the piece from a 4-cell mask is the only piece of colour-free
matching the loop needs; skins (jakesgordon's flat colours, Tetris 99's
brighter colours, GB greys) all sit above the saturation threshold.

Animations are not handled here: a court during a line clear or a garbage
rise is wrong. The runner requires two identical consecutive frames before
it commits (G4).
"""

from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .board import NX, NY, Court
from .profiles import PIECE_NAMES, SHAPES_BY_NAME, VisionProfile
from shared.src.lib.utils import cv2_io


def _cells_from_mask(mask: int) -> List[Tuple[int, int]]:
    """Cells set in a 16-bit rotation mask (1 cell per bit, top-left of 4x4 = (0, 0))."""
    out: List[Tuple[int, int]] = []
    for i in range(16):
        if mask & (0x8000 >> i):
            out.append((i % 4, i // 4))
    return out


def _build_shape_lookup() -> Dict[frozenset, str]:
    """Map every piece's 4 rotations (normalised to top-left) to its name.

    A piece can have fewer than 4 unique shapes (I, S, Z are 180°-symmetric),
    but multiple rotations can produce the same shape; we keep one entry per
    unique shape. All seven pieces have distinct canonical shapes, so the
    lookup is unambiguous.
    """
    lookup: Dict[frozenset, str] = {}
    for name, masks in SHAPES_BY_NAME.items():
        seen: set = set()
        for mask in masks:
            cs = _cells_from_mask(mask)
            min_cx = min(c[0] for c in cs)
            min_cy = min(c[1] for c in cs)
            key = frozenset((c[0] - min_cx, c[1] - min_cy) for c in cs)
            if key in seen:
                continue
            seen.add(key)
            lookup[key] = name
    return lookup


SHAPE_LOOKUP: Dict[frozenset, str] = _build_shape_lookup()


def identify_piece(cells: List[Tuple[int, int]]) -> Optional[str]:
    """Name the piece from its 4-cell mask, or None if it doesn't match.

    Colour never enters this function: every tetromino has a unique shape,
    and every rotation normalises to the same lookup table. Skins (GB greys,
    Tetris 99's brighter colours) all map to the same name.
    """
    if len(cells) != 4:
        return None
    min_cx = min(c[0] for c in cells)
    min_cy = min(c[1] for c in cells)
    key = frozenset((c[0] - min_cx, c[1] - min_cy) for c in cells)
    return SHAPE_LOOKUP.get(key)


def diff_cells(a: Court, b: Court) -> int:
    """Number of cells where two courts differ (for accuracy KPIs)."""
    return sum(1 for x in range(NX) for y in range(NY) if a[x][y] != b[x][y])


# ---------------------------------------------------------------------------
# Court auto-detection (jakesgordon-style 1:2 dark component)
# ---------------------------------------------------------------------------

BORDER_PX = 2
DARK_SUM = 200
MIN_COURT_H = 200


def locate_court(img: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """(x, y, w, h) of the court inside its border, or None when no court is
    found. jakesgordon draws the court as a dark-bordered 1:2 component on a
    pale textured background; Tetris 99's busy 99-board screen fails this
    test, so the guideline profile uses a fixed ROI instead.
    """
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


# ---------------------------------------------------------------------------
# VisionReader
# ---------------------------------------------------------------------------


class VisionReader:
    """Reads a court + next queue from a captured frame, per a VisionProfile."""

    def __init__(self, profile: VisionProfile):
        self.profile = profile

    def read(self, image_path: str) -> Optional[Dict[str, Any]]:
        img = cv2_io.imread(image_path)
        if img is None:
            return None
        court = self._read_court(img)
        if court is None:
            return None
        next_pieces = self._read_next(img) if self.profile.next_rois else []
        return {"court": court, "next": next_pieces, "frame": image_path}

    def _read_court(self, img: np.ndarray) -> Optional[Court]:
        if self.profile.auto_detect_court:
            rect = locate_court(img)
            if rect is None:
                return None
            x0, y0, w, h = rect
            cw, ch = w / NX, h / NY
        else:
            x0, y0, w, h = self.profile.court_roi or (None, None, None, None)
            if x0 is None or not self.profile.cell_px:
                return None
            cw = ch = self.profile.cell_px
        court: Court = [[0] * NY for _ in range(NX)]
        for cx in range(NX):
            for cy in range(NY):
                xa = int(x0 + cw * (cx + self.profile.inner))
                ya = int(y0 + ch * (cy + self.profile.inner))
                xb = int(x0 + cw * (cx + 1 - self.profile.inner))
                yb = int(y0 + ch * (cy + 1 - self.profile.inner))
                patch = img[ya:max(ya + 1, yb), xa:max(xa + 1, xb)].reshape(-1, 3)
                bb, gg, rr = np.median(patch, axis=0)
                if max(rr, gg, bb) - min(rr, gg, bb) >= self.profile.fill_threshold:
                    court[cx][cy] = 1
        return court

    def _read_next(self, img: np.ndarray) -> List[Optional[str]]:
        """Read the next-queue slots. Each slot is a small ROI where the piece
        sits in a 4x4 grid; we read every cell and shape-match.
        """
        out: List[Optional[str]] = []
        for roi in self.profile.next_rois or []:
            cells = self._read_piece_cells(img, roi)
            out.append(identify_piece(cells) if cells else None)
        return out

    def _read_piece_cells(self, img: np.ndarray,
                          roi: Tuple[int, int, int, int]) -> List[Tuple[int, int]]:
        """Fill the 4-cell mask in a piece-preview ROI."""
        x0, y0, w, h = roi
        cell = self.profile.next_cell_px
        cols = max(1, w // cell)
        rows = max(1, h // cell)
        filled: List[Tuple[int, int]] = []
        for c in range(cols):
            for r in range(rows):
                xa = int(x0 + c * cell + cell * self.profile.inner)
                ya = int(y0 + r * cell + cell * self.profile.inner)
                xb = int(x0 + (c + 1) * cell - cell * self.profile.inner)
                yb = int(y0 + (r + 1) * cell - cell * self.profile.inner)
                patch = img[ya:max(ya + 1, yb), xa:max(xa + 1, xb)].reshape(-1, 3)
                bb, gg, rr = np.median(patch, axis=0)
                if max(rr, gg, bb) - min(rr, gg, bb) >= self.profile.fill_threshold:
                    filled.append((c, r))
        return filled


# ---------------------------------------------------------------------------
# Backwards-compat shim (the G1 reader.py exposed `read_court` and `diff_cells`).
# G2's tests still import them; keep the function name working.
# ---------------------------------------------------------------------------


def read_court(image_path: str, profile: Optional[VisionProfile] = None) -> Optional[Court]:
    """Read just the court from a frame. Defaults to jakesgordon auto-detection
    so existing callers (G3 runner's final-court diff) keep working."""
    profile = profile or VisionProfile(name="jakesgordon", auto_detect_court=True, cell_px=30,
                                       fill_threshold=90, inner=0.25)
    result = VisionReader(profile).read(image_path)
    return result["court"] if result else None