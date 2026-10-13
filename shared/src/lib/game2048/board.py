"""2048 board rules. Boards are rows[y][x] with 0 for an empty cell."""

from typing import List, Optional

Board = List[List[int]]

MOVES = ("LEFT", "DOWN", "RIGHT", "UP")


def _slide(line: List[int]) -> List[int]:
    """Slide and merge one line toward index 0 (each tile merges at most once)."""
    tiles = [v for v in line if v]
    out = []
    i = 0
    while i < len(tiles):
        if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
            out.append(tiles[i] * 2)
            i += 2
        else:
            out.append(tiles[i])
            i += 1
    return out + [0] * (len(line) - len(out))


def _line_gain(line: List[int]) -> int:
    tiles = [v for v in line if v]
    gain, i = 0, 0
    while i < len(tiles):
        if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
            gain += tiles[i] * 2
            i += 2
        else:
            i += 1
    return gain


def apply_move(rows: Board, direction: str) -> Board:
    """Board after a move, without the random spawn."""
    if direction == "LEFT":
        return [_slide(r) for r in rows]
    if direction == "RIGHT":
        return [_slide(r[::-1])[::-1] for r in rows]
    cols = [list(c) for c in zip(*rows)]
    if direction == "UP":
        cols = [_slide(c) for c in cols]
    else:
        cols = [_slide(c[::-1])[::-1] for c in cols]
    return [list(r) for r in zip(*cols)]


def merge_gain(rows: Board, direction: str) -> int:
    """Points a move scores (sum of the merged tiles)."""
    if direction in ("LEFT", "RIGHT"):
        return sum(_line_gain(r if direction == "LEFT" else r[::-1]) for r in rows)
    cols = [list(c) for c in zip(*rows)]
    return sum(_line_gain(c if direction == "UP" else c[::-1]) for c in cols)


def legal_moves(rows: Board) -> List[str]:
    return [d for d in MOVES if apply_move(rows, d) != rows]


def max_tile(rows: Board) -> int:
    return max((v for r in rows for v in r), default=0)


def tile_count(rows: Board) -> int:
    return sum(1 for r in rows for v in r if v)


def empty_cells(rows: Board) -> int:
    return sum(1 for r in rows for v in r if not v)


def board_text(rows: Board) -> str:
    return "\n".join(" ".join(f"{v or '.':>4}" for v in r) for r in rows)


def first_legal(rows: Board, priority=MOVES) -> Optional[str]:
    for direction in priority:
        if apply_move(rows, direction) != rows:
            return direction
    return None
