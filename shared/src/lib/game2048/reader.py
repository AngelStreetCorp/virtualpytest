"""
Pixel board reader for classic 2048 (classic.play2048.co), from any captured frame.

The reader never OCRs the tiles. It locates the board by its background colour, samples
the colour of each cell, and works in two modes:

- track(): the normal path. The caller knows the board before a move and the move is
  deterministic, so the frame only has to confirm the predicted tiles and show exactly one
  new tile (a 2 or a 4) in a predicted-empty cell. Every confirmed tile colour is learned,
  which calibrates the palette to the capture pipeline (HDMI/VNC shift colours).
- read(): a blind nearest-colour read of all 16 cells (initial board, resync).
"""

from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from .board import Board
from shared.src.lib.utils import cv2_io

Rgb = Tuple[float, float, float]

# Classic 2048 CSS colours (RGB). 0 = empty cell (rgba(238,228,218,.35) over the board).
CANONICAL: Dict[int, Rgb] = {
    0: (205, 193, 180),
    2: (238, 228, 218),
    4: (237, 224, 200),
    8: (242, 177, 121),
    16: (245, 149, 99),
    32: (246, 124, 95),
    64: (246, 94, 59),
    128: (237, 207, 114),
    256: (237, 204, 97),
    512: (237, 200, 80),
    1024: (237, 197, 63),
    2048: (237, 194, 46),
}
BOARD_BG: Rgb = (187, 173, 160)

# Board geometry as a fraction of the board width (classic CSS: 15px gaps, 106.25px cells
# on 500px desktop; 10px / 57.5px on 280px mobile - both ~0.03 / ~0.21).
GAP = 0.032
CELL = (1.0 - 5 * GAP) / 4
# Median colour of the tile's inner square: digit strokes cover well under half of it.
INNER = 0.12
# A settled empty cell or new 2/4 tile sits within this RGB distance of its reference;
# anything further is a frame caught mid-slide / mid-spawn animation.
MAX_MATCH_DIST = 22.0


def locate_board(img: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """(x, y, w, h) of the board: the largest near-square blob of the board colour.

    Every threshold is tried and the biggest square wins. A capture shift close to the
    strictest threshold splits the grid lines into pieces, and one piece can itself be
    square (the S21 HDMI capture read a 188x176 corner of a 258x258 board).
    """
    bgr = img.astype(np.int32)
    target = np.array(BOARD_BG[::-1], dtype=np.int32)
    dist = np.abs(bgr - target).sum(axis=2)
    found = []
    for threshold in (40, 60, 80, 100):
        mask = (dist < threshold).astype(np.uint8) * 255
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        if count <= 1:
            continue
        best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x, y, w, h, _ = stats[best]
        if w >= 120 and 0.85 < w / h < 1.15:
            found.append((int(w) * int(h), (int(x), int(y), int(w), int(h))))
    return max(found)[1] if found else None


def _dist(a: Rgb, b: Rgb) -> float:
    return float(np.sqrt(sum((float(i) - float(j)) ** 2 for i, j in zip(a, b))))


class BoardReader:
    def __init__(self):
        self.rect: Optional[Tuple[int, int, int, int]] = None
        self._learned: Dict[int, List[Rgb]] = {}
        self.offset: Rgb = (0.0, 0.0, 0.0)

    # --- frame sampling -------------------------------------------------------------
    def load(self, image_path: str) -> Optional[np.ndarray]:
        img = cv2_io.imread(image_path)
        if img is None:
            return None
        rect = locate_board(img)
        if rect:
            self.rect = rect
        return img if self.rect else None

    def cell_colours(self, img: np.ndarray) -> List[List[Rgb]]:
        x, y, w, h = self.rect
        size = CELL * (1 - 2 * INNER)
        out = []
        for r in range(4):
            row = []
            for c in range(4):
                x0 = int(x + w * (GAP + (CELL + GAP) * c + CELL * INNER))
                y0 = int(y + h * (GAP + (CELL + GAP) * r + CELL * INNER))
                patch = img[y0:y0 + max(1, int(h * size)), x0:x0 + max(1, int(w * size))].reshape(-1, 3)
                b, g, rr = np.median(patch, axis=0)
                row.append((float(rr), float(g), float(b)))
            out.append(row)
        return out

    # --- palette --------------------------------------------------------------------
    def calibrate_offset(self, img: np.ndarray) -> None:
        """Colour shift of the capture pipeline, from the board background in the gaps."""
        x, y, w, h = self.rect
        px, py = int(x + w * GAP / 2), int(y + h * 0.5)
        b, g, r = img[py - 1:py + 2, px - 1:px + 2].reshape(-1, 3).mean(axis=0)
        self.offset = (r - BOARD_BG[0], g - BOARD_BG[1], b - BOARD_BG[2])

    def reference(self, value: int) -> Rgb:
        seen = self._learned.get(value)
        if seen:
            return tuple(float(np.mean([s[i] for s in seen])) for i in range(3))
        base = CANONICAL[value]
        return tuple(min(255.0, max(0.0, base[i] + self.offset[i])) for i in range(3))

    def learn(self, value: int, colour: Rgb) -> None:
        seen = self._learned.setdefault(value, [])
        seen.append(colour)
        del seen[:-20]

    def classify(self, colour: Rgb, candidates=None) -> Tuple[int, float]:
        values = candidates or list(CANONICAL)
        scored = sorted((_dist(colour, self.reference(v)), v) for v in values)
        return scored[0][1], scored[0][0]

    def is_empty(self, colour: Rgb) -> bool:
        return self.classify(colour)[0] == 0

    def is_clean_empty(self, colour: Rgb) -> bool:
        return _dist(colour, self.reference(0)) <= MAX_MATCH_DIST

    # --- reads ------------------------------------------------------------------------
    def read(self, image_path: str, max_value: Optional[int] = None) -> Optional[Board]:
        """Blind read of the whole board (nearest palette colour per cell, values <= max_value)."""
        img = self.load(image_path)
        if img is None:
            return None
        if not self._learned:
            self.calibrate_offset(img)
        colours = self.cell_colours(img)
        values = [v for v in CANONICAL if max_value is None or v <= max_value]
        return [[self.classify(colours[r][c], values)[0] for c in range(4)] for r in range(4)]

    def read_fresh(self, image_path: str) -> Optional[Board]:
        """Read a new-game board: exactly two tiles, each a 2 or a 4."""
        img = self.load(image_path)
        if img is None:
            return None
        self.calibrate_offset(img)
        colours = self.cell_colours(img)
        board = [[0] * 4 for _ in range(4)]
        for r in range(4):
            for c in range(4):
                if not self.is_empty(colours[r][c]):
                    board[r][c] = self.classify(colours[r][c], [2, 4])[0]
        if sum(1 for row in board for v in row if v) != 2:
            return None
        self._learn_board(board, colours)
        return board

    def track(self, image_path: str, predicted: Board) -> Tuple[str, Optional[Board]]:
        """
        Match a frame against the predicted board (after a move, before the spawn).

        Returns (status, board):
          ('ok', board)        predicted tiles present + exactly one new 2/4 tile
          ('unchanged', None)  frame still shows the pre-move tile layout (not applied yet)
          ('moving', None)     anything else: animation in progress or a misread
        """
        img = self.load(image_path)
        if img is None:
            return "moving", None
        colours = self.cell_colours(img)
        empty = [[self.is_clean_empty(colours[r][c]) for c in range(4)] for r in range(4)]
        missing = [(r, c) for r in range(4) for c in range(4) if predicted[r][c] and empty[r][c]]
        new = [(r, c) for r in range(4) for c in range(4) if not predicted[r][c] and not empty[r][c]]
        if missing or len(new) != 1:
            return "moving", None
        # Every predicted tile must also show its predicted value: a frame from before the
        # move can look like "predicted + one new tile" when the move merges two tiles.
        for rr in range(4):
            for cc in range(4):
                value = predicted[rr][cc]
                if not value or self.classify(colours[rr][cc])[0] == value:
                    continue
                # 128..2048 are near-identical yellows: accept a close colour there only.
                if value < 128 or _dist(colours[rr][cc], self.reference(value)) > 2 * MAX_MATCH_DIST:
                    return "moving", None
        r, c = new[0]
        value, dist = self.classify(colours[r][c], [2, 4])
        if dist > MAX_MATCH_DIST:  # the new tile is still scaling in
            return "moving", None
        board = [row[:] for row in predicted]
        board[r][c] = value
        self._learn_board(board, colours)
        return "ok", board

    def occupancy(self, image_path: str) -> Optional[List[List[bool]]]:
        img = self.load(image_path)
        if img is None:
            return None
        colours = self.cell_colours(img)
        return [[not self.is_empty(colours[r][c]) for c in range(4)] for r in range(4)]

    def _learn_board(self, board: Board, colours: List[List[Rgb]]) -> None:
        for r in range(4):
            for c in range(4):
                self.learn(board[r][c], colours[r][c])
