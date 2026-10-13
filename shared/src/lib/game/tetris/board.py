"""
Tetris rules of the target page and the El-Tetris placement heuristic.

The court is a list of 10 columns of 20 cells (court[x][y], y = 0 at the top), 1 = filled,
the same layout as the page's `blocks[x][y]`. Pieces, rotations and line clearing copy the
page's code: no wall kicks, a rotation is just the next 16-bit mask.
"""

from typing import List, Optional, Tuple

NX, NY = 10, 20
Court = List[List[int]]

# One 16-bit mask per rotation (dir 0..3), keyed by the page's piece colour.
SHAPES = {
    "cyan": [0x0F00, 0x2222, 0x00F0, 0x4444],    # I
    "blue": [0x44C0, 0x8E00, 0x6440, 0x0E20],    # J
    "orange": [0x4460, 0x0E80, 0xC440, 0x2E00],  # L
    "yellow": [0xCC00, 0xCC00, 0xCC00, 0xCC00],  # O
    "green": [0x06C0, 0x8C40, 0x6C00, 0x4620],   # S
    "purple": [0x0E40, 0x4C40, 0x4E00, 0x4640],  # T
    "red": [0x0C60, 0x4C80, 0xC600, 0x2640],     # Z
}
PIECE_NAMES = {"cyan": "I", "blue": "J", "orange": "L", "yellow": "O", "green": "S", "purple": "T", "red": "Z"}

# El-Tetris weights (Islam El-Ashi, 2011): landing height, rows cleared, row transitions,
# column transitions, holes, well sums.
WEIGHTS = (-4.500158825082766, 3.4181268101392694, -3.2178882868487753,
           -9.348695305445199, -7.899265427351652, -3.3855972247263626)


def empty_court() -> Court:
    return [[0] * NY for _ in range(NX)]


def cells(piece: str, d: int, x: int, y: int) -> List[Tuple[int, int]]:
    mask, out = SHAPES[piece][d], []
    for i in range(16):
        if mask & (0x8000 >> i):
            out.append((x + i % 4, y + i // 4))
    return out


def fits(court: Court, piece: str, d: int, x: int, y: int) -> bool:
    return all(0 <= cx < NX and 0 <= cy < NY and not court[cx][cy] for cx, cy in cells(piece, d, x, y))


def landing_y(court: Court, piece: str, d: int, x: int, y: int = 0) -> Optional[int]:
    """Row where the piece rests when dropped from row y, or None if it doesn't fit there."""
    if not fits(court, piece, d, x, y):
        return None
    while fits(court, piece, d, x, y + 1):
        y += 1
    return y


def place(court: Court, piece: str, d: int, x: int, y: int) -> Tuple[Court, List[Tuple[int, int]], int]:
    """(court after the piece locks at (x, y) and full rows clear, the piece's cells, rows cleared)."""
    new = [col[:] for col in court]
    placed = cells(piece, d, x, y)
    for cx, cy in placed:
        new[cx][cy] = 1
    full = [row for row in range(NY) if all(new[col][row] for col in range(NX))]
    for row in full:  # like the page's removeLine: everything above moves down one row
        for col in range(NX):
            del new[col][row]
            new[col].insert(0, 0)
    return new, placed, len(full)


def features(court: Court, placed: List[Tuple[int, int]], lines: int) -> Tuple[float, ...]:
    landing = NY - min(cy for _, cy in placed)
    row_t = col_t = holes = wells = 0
    for y in range(NY):
        prev = 1
        for x in range(NX):
            if court[x][y] != prev:
                row_t += 1
            prev = court[x][y]
        if prev != 1:
            row_t += 1
    for x in range(NX):
        prev, seen = 0, False
        for y in range(NY):
            v = court[x][y]
            if v != prev:
                col_t += 1
            prev = v
            if v:
                seen = True
            elif seen:
                holes += 1
        if prev != 1:
            col_t += 1
        depth = 0
        for y in range(NY):
            left = court[x - 1][y] if x > 0 else 1
            right = court[x + 1][y] if x < NX - 1 else 1
            if not court[x][y] and left and right:
                depth += 1
                wells += depth
            else:
                depth = 0
    return (landing, lines, row_t, col_t, holes, wells)


def reachable(court: Court, piece: str, d0: int, x0: int, y0: int, d: int, x: int) -> bool:
    """The page rotates in place (no wall kicks), so: rotate at (x0, y0) first, then shift."""
    dd = d0
    while dd != d:
        dd = (dd + 1) % 4
        if not fits(court, piece, dd, x0, y0):
            return False
    step = 1 if x > x0 else -1
    for xx in range(x0, x, step):
        if not fits(court, piece, d, xx + step, y0):
            return False
    return True


def best_placement(court: Court, piece: str, d0: int, x0: int, y0: int) -> Optional[dict]:
    """The highest-scoring reachable placement: {d, x, y, lines, score}, or None (no move left)."""
    best = None
    for d in range(4):
        for x in range(-3, NX):
            if not reachable(court, piece, d0, x0, y0, d, x):
                continue
            y = landing_y(court, piece, d, x, y0)
            if y is None:
                continue
            after, placed, lines = place(court, piece, d, x, y)
            score = sum(w * f for w, f in zip(WEIGHTS, features(after, placed, lines)))
            if best is None or score > best["score"]:
                best = {"d": d, "x": x, "y": y, "lines": lines, "score": score}
    return best


def placement_keys(d0: int, x0: int, y0: int, target: dict) -> List[str]:
    """Key names for the userinterface's move nodes: rotations, shifts, one DOWN per row, plus one
    DOWN that locks the piece (the page locks a piece when DOWN can't move it) instead of waiting
    for gravity."""
    keys = ["rotate"] * ((target["d"] - d0) % 4)
    dx = target["x"] - x0
    keys += ["right"] * dx if dx > 0 else ["left"] * -dx
    keys += ["down"] * (max(0, target["y"] - y0) + 1)
    return keys


def court_from_string(text: str) -> Court:
    """The page state's court string: 200 chars, column-major (x * 20 + y), '1' = filled."""
    return [[1 if text[x * NY + y] == "1" else 0 for y in range(NY)] for x in range(NX)]


def court_rows(court: Court) -> List[str]:
    """Readable rows for reports: '.' empty, '#' filled, top row first."""
    return ["".join("#" if court[x][y] else "." for x in range(NX)) for y in range(NY)]
