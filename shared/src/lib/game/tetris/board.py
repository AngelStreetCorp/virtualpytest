"""
Tetris court rules and the El-Tetris placement heuristic.

The court is a list of 10 columns of 20 cells (court[x][y], y = 0 at the top),
1 = filled, the same layout as jakesgordon's page. Pieces, rotations and line
clearing match both jakesgordon's masks and the Tetris Guideline (SRS) — the
masks themselves are identical. The rotation *system* is in the profile:

  jakesgordon: rotates in place, no wall kicks. A stuck DOWN locks the piece.
  guideline (SRS): tries up to five wall kicks on each rotation step. Gravity
                   drops the piece; a hard-drop key locks it.

`Rules` (profiles.py) holds everything else that varies between games: spawn
position, hard drop, hold, previews. Devices (web / Android / Switch) differ
in how to *send* the keys — that's the userinterface tree's job, and the
runner reads each action's actions from the loaded tree.

For backwards compatibility, the module-level helpers accept a colour piece
id ("cyan", "purple", ...) just like the original board, and default to the
jakesgordon profile. Guideline / SRS callers pass an explicit Rules.
"""

from typing import Dict, List, Optional, Tuple

from .profiles import JAKESGORDON, PIECE_NAMES, Rules, SHAPES_BY_NAME, srs_kick

NX, NY = 10, 20
Court = List[List[int]]

# Backwards-compat aliases: jakesgordon's page speaks colour, not name.
SHAPES: Dict[str, List[int]] = {
    "cyan": SHAPES_BY_NAME["I"],     "blue": SHAPES_BY_NAME["J"],
    "orange": SHAPES_BY_NAME["L"],   "yellow": SHAPES_BY_NAME["O"],
    "green": SHAPES_BY_NAME["S"],    "purple": SHAPES_BY_NAME["T"],
    "red": SHAPES_BY_NAME["Z"],
}
PIECE_NAME_BY_COLOUR: Dict[str, str] = {
    "cyan": "I", "blue": "J", "orange": "L", "yellow": "O",
    "green": "S", "purple": "T", "red": "Z",
}

# El-Tetris weights (Islam El-Ashi, 2011): landing height, rows cleared, row
# transitions, column transitions, holes, well sums.
WEIGHTS = (-4.500158825082766, 3.4181268101392694, -3.2178882868487753,
           -9.348695305445199, -7.899265427351652, -3.3855972247263626)


# ---------------------------------------------------------------------------
# Core helpers (profile-aware)
# ---------------------------------------------------------------------------


def empty_court() -> Court:
    return [[0] * NY for _ in range(NX)]


def cells(piece: str, d: int, x: int, y: int, rules: Optional[Rules] = None) -> List[Tuple[int, int]]:
    """Cells of `piece` at rotation `d`, top-left of the 4x4 box at (x, y)."""
    rules = rules or JAKESGORDON
    name = rules.resolve_name(piece)
    mask = SHAPES_BY_NAME[name][d % 4]
    out = []
    for i in range(16):
        if mask & (0x8000 >> i):
            out.append((x + i % 4, y + i // 4))
    return out


def fits(court: Court, piece: str, d: int, x: int, y: int, rules: Optional[Rules] = None) -> bool:
    """True when `piece` at rotation `d` and box-top-left (x, y) does not overlap
    a filled cell and stays inside the court."""
    return all(0 <= cx < NX and 0 <= cy < NY and not court[cx][cy]
               for cx, cy in cells(piece, d, x, y, rules))


def landing_y(court: Court, piece: str, d: int, x: int, y: int = 0,
              rules: Optional[Rules] = None) -> Optional[int]:
    """Row where the piece rests when dropped from row y, or None if it doesn't fit.

    For both jakesgordon and guideline this is the row where the piece lands
    on its own — guideline's gravity (lines / s per row) is unrelated.
    """
    rules = rules or JAKESGORDON
    if not fits(court, piece, d, x, y, rules):
        return None
    while fits(court, piece, d, x, y + 1, rules):
        y += 1
    return y


def place(court: Court, piece: str, d: int, x: int, y: int,
          rules: Optional[Rules] = None) -> Tuple[Court, List[Tuple[int, int]], int]:
    """(court after the piece locks at (x, y) and full rows clear, the piece's
    cells, rows cleared). The piece's locks-on-landing rule is the same on both
    jakesgordon and guideline: full rows collapse from the top."""
    rules = rules or JAKESGORDON
    new = [col[:] for col in court]
    placed = cells(piece, d, x, y, rules)
    for cx, cy in placed:
        new[cx][cy] = 1
    full = [row for row in range(NY) if all(new[col][row] for col in range(NX))]
    for row in full:  # like the page's removeLine: everything above moves down one row
        for col in range(NX):
            del new[col][row]
            new[col].insert(0, 0)
    return new, placed, len(full)


# ---------------------------------------------------------------------------
# Features (El-Tetris weights)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Reachability (profile-aware)
# ---------------------------------------------------------------------------


def reachable(court: Court, piece: str, d0: int, x0: int, y0: int, d: int, x: int,
              rules: Optional[Rules] = None) -> bool:
    """Can the piece get from (d0, x0, y0) to (d, x, y0) under these rules?

    - jakesgordon: rotate in place (no kicks), then shift sideways.
    - guideline (SRS): try the kick table on each rotation step, then shift.

    `y` stays fixed at y0 — reachability is about choosing the rotation and
    the column, not the row. The row is decided by `landing_y` afterwards.
    """
    rules = rules or JAKESGORDON
    name = rules.resolve_name(piece) if piece not in SHAPES_BY_NAME else piece
    if rules.has_kicks:
        return _reachable_srs(court, name, d0, x0, y0, d, x)
    return _reachable_jakesgordon(court, name, d0, x0, y0, d, x)


def _reachable_jakesgordon(court, piece, d0, x0, y0, d, x):
    """jakesgordon: rotate in place, then shift."""
    dd = d0
    while dd != d:
        dd_next = (dd + 1) % 4
        if not fits(court, piece, dd_next, x0, y0):
            return False
        dd = dd_next
    step = 1 if x > x0 else -1
    for xx in range(x0, x, step):
        if not fits(court, piece, d, xx + step, y0):
            return False
    return True


def _reachable_srs(court, piece, d0, x0, y0, d, x):
    """SRS: try the 5-kick table on each rotation step, then shift sideways."""
    cx, cy, cd = x0, y0, d0
    while cd != d:
        next_cd = (cd + 1) % 4
        # Per SRS: try each kick, pick the first that fits. y-axis flip is
        # already baked into `srs_kick` (it returns Y-down offsets).
        kicked = False
        for dx, dy in srs_kick(piece, cd):
            nx, ny = cx + dx, cy + dy
            if fits(court, piece, next_cd, nx, ny):
                cx, cy = nx, ny
                kicked = True
                break
        if not kicked:
            return False
        cd = next_cd
    step = 1 if x > cx else -1
    for xx in range(cx, x, step):
        if not fits(court, piece, cd, xx + step, cy):
            return False
    return True


# ---------------------------------------------------------------------------
# Best placement (profile-aware)
# ---------------------------------------------------------------------------


def best_placement(court: Court, piece: str, d0: int, x0: int, y0: int,
                   rules: Optional[Rules] = None) -> Optional[dict]:
    """The highest-scoring reachable placement: {d, x, y, lines, score}, or None."""
    rules = rules or JAKESGORDON
    best = None
    # x range is -3..NX-1 to allow partial off-court boxes (e.g. an L in spawn
    # at column -3 means cells at columns 0 and 1 only).
    for d in range(4):
        for x in range(-3, NX):
            if not reachable(court, piece, d0, x0, y0, d, x, rules):
                continue
            y = landing_y(court, piece, d, x, y0, rules)
            if y is None:
                continue
            after, placed, lines = place(court, piece, d, x, y, rules)
            score = sum(w * f for w, f in zip(WEIGHTS, features(after, placed, lines)))
            if best is None or score > best["score"]:
                best = {"d": d, "x": x, "y": y, "lines": lines, "score": score}
    return best


def placement_keys(d0: int, x0: int, y0: int, target: dict,
                   rules: Optional[Rules] = None) -> List[str]:
    """Key names for the userinterface's move nodes.

    - jakesgordon: rotate (CW only), left/right, one DOWN per row, plus the
      DOWN that locks the piece (the page locks a piece when DOWN can't move
      it instead of waiting for gravity).
    - guideline: rotate (CW), left/right, hard_drop (one key locks).
      The piece falls on its own — no per-row DOWN needed.

    The tree must define action nodes with these exact names. Keys not used by
    the profile are skipped (the runner reads whatever the tree has).
    """
    rules = rules or JAKESGORDON
    keys: List[str] = []
    keys += ["rotate"] * ((target["d"] - d0) % 4)
    dx = target["x"] - x0
    keys += ["right"] * dx if dx > 0 else ["left"] * -dx
    if rules.hard_drop:
        keys += ["hard_drop"]
    else:
        keys += ["down"] * (max(0, target["y"] - y0) + 1)
    return keys


# ---------------------------------------------------------------------------
# Court serialisation (web page-state format)
# ---------------------------------------------------------------------------


def court_from_string(text: str) -> Court:
    """The page state's court string: 200 chars, column-major (x * 20 + y), '1' = filled."""
    return [[1 if text[x * NY + y] == "1" else 0 for y in range(NY)] for x in range(NX)]


def court_rows(court: Court) -> List[str]:
    """Readable rows for reports: '.' empty, '#' filled, top row first."""
    return ["".join("#" if court[x][y] else "." for x in range(NX)) for y in range(NY)]