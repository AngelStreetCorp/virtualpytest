"""
Tetris game profiles (TASK-51).

A profile captures everything that varies between Tetris *games* (not devices):
rotation system (jakesgordon's in-place vs SRS with kicks), spawn position,
how DOWN behaves (jakesgordon: one row per key, locks on a stuck DOWN; SRS:
gravity moves the piece and a hard-drop key locks it), hold piece, and the
number of preview pieces. Devices (web, Android, Switch) differ in how to
*send* the keys; that's the userinterface tree's job.

The court is always 10 columns x 20 rows. The piece masks are the same as the
Tetris Guideline (SRS) — jakesgordon's page uses the same 4x4 rotation
masks. What differs is reachability:

  - jakesgordon: a rotation is just the next 16-bit mask; no wall kicks.
    The piece can rotate in place only.
  - guideline (SRS): a rotation tries up to five kick positions; the first
    that fits wins. Walls and floor push the piece out of the way.

Keys the runner needs for each profile:

  jakesgordon   : rotate, left, right, down         (DOWN per row + 1 to lock)
  guideline     : rotate (CW), left, right, hard_drop   (gravity drops it,
                                                          one key locks)
                 + rotate_ccw, hold, soft_drop if the tree defines them.

SRS kick tables follow the Tetris Wiki SRS spec, in (x, y) with y pointing
*up*. Apply them in our court (y pointing *down*) by negating y.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Piece masks (SRS-compatible). Same as jakesgordon's page: one 16-bit mask
# per rotation, bit i set means cell (i % 4, i // 4) of the 4x4 box is filled.
# Keyed by the canonical piece name (I, J, L, O, S, T, Z), NOT by colour.
# ---------------------------------------------------------------------------

SHAPES_BY_NAME: Dict[str, List[int]] = {
    "I": [0x0F00, 0x2222, 0x00F0, 0x4444],
    "J": [0x44C0, 0x8E00, 0x6440, 0x0E20],
    "L": [0x4460, 0x0E80, 0xC440, 0x2E00],
    "O": [0xCC00, 0xCC00, 0xCC00, 0xCC00],
    "S": [0x06C0, 0x8C40, 0x6C00, 0x4620],
    "T": [0x0E40, 0x4C40, 0x4E00, 0x4640],
    "Z": [0x0C60, 0x4C80, 0xC600, 0x2640],
}
PIECE_NAMES: Tuple[str, ...] = ("I", "J", "L", "O", "S", "T", "Z")


# ---------------------------------------------------------------------------
# SRS kick tables (Tetris Wiki, y points UP). Apply by negating y.
# SRS_KICKS[piece_class][from_rotation] = list of (dx, dy_up) tried in order.
# ---------------------------------------------------------------------------

SRS_KICKS: Dict[str, List[List[Tuple[int, int]]]] = {
    "JLSTZ": [
        [(0, 0), (-1, 0), (-1, +1), (0, -2), (-1, -2)],  # 0 -> R
        [(0, 0), (+1, 0), (+1, -1), (0, +2), (+1, +2)],  # R -> 2
        [(0, 0), (+1, 0), (+1, +1), (0, -2), (+1, -2)],  # 2 -> L
        [(0, 0), (-1, 0), (-1, -1), (0, +2), (-1, +2)],  # L -> 0
    ],
    "I": [
        [(0, 0), (-2, 0), (+1, 0), (-2, -1), (+1, +2)],  # 0 -> R
        [(0, 0), (-1, 0), (+2, 0), (-1, +2), (+2, -1)],  # R -> 2
        [(0, 0), (+2, 0), (-1, 0), (+2, +1), (-1, -2)],  # 2 -> L
        [(0, 0), (+1, 0), (-2, 0), (+1, -2), (-2, +1)],  # L -> 0
    ],
}


def srs_kick(piece_name: str, from_d: int) -> List[Tuple[int, int]]:
    """SRS kicks for one rotation step (from_d -> from_d + 1), in Y-DOWN coords.

    The piece's I-piece kicks are different from JLSTZ. The O-piece never
    needs kicks (it fits in its own 2x2 regardless).
    """
    if piece_name == "O":
        return [(0, 0)]
    table = SRS_KICKS["I"] if piece_name == "I" else SRS_KICKS["JLSTZ"]
    # Negate y to convert from Y-up (Tetris Wiki) to our Y-down court.
    return [(dx, -dy) for dx, dy in table[from_d % 4]]


# ---------------------------------------------------------------------------
# Rules profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rules:
    """Everything that differs between Tetris games (not devices)."""

    name: str                              # "jakesgordon" | "guideline" | ...
    rotation: str                          # "jakesgordon" | "srs"
    spawn_x: int                           # 0-indexed column of the 4x4 box's left edge
    spawn_y: int                           # 0-indexed row of the 4x4 box's top edge
    has_kicks: bool                        # True: SRS-style wall kicks on rotation
    hard_drop: bool                        # True: a hard_drop key locks the piece
    hold: bool = False                     # True: the piece can be held
    previews: int = 1                      # count of next pieces visible
    # jakesgordon-specific: maps the page's piece colour to the canonical name.
    # Empty dict when the page already speaks the canonical name (Guideline).
    colour_to_name: Dict[str, str] = field(default_factory=dict)

    def resolve_name(self, piece_id: str) -> str:
        """Turn a piece id (colour for jakesgordon, name for guideline) into a name."""
        if piece_id in PIECE_NAMES:
            return piece_id
        if piece_id in self.colour_to_name:
            return self.colour_to_name[piece_id]
        # Fallback: unknown id — let the caller see a clear error rather than
        # silently treating it as a name.
        raise KeyError(f"unknown piece id {piece_id!r} for profile {self.name!r}")


# jakesgordon's page keys pieces by colour (cyan/blue/orange/yellow/green/
# purple/red). Map each to the canonical tetromino name.
JAKESGORDON_COLOUR_TO_NAME = {
    "cyan": "I", "blue": "J", "orange": "L", "yellow": "O",
    "green": "S", "purple": "T", "red": "Z",
}

JAKESGORDON = Rules(
    name="jakesgordon",
    rotation="jakesgordon",
    spawn_x=3,
    spawn_y=0,
    has_kicks=False,
    hard_drop=False,                # DOWN moves one row; a stuck DOWN locks the piece
    hold=False,
    previews=1,
    colour_to_name=JAKESGORDON_COLOUR_TO_NAME,
)

# Tetris Guideline / SRS (Tetris 99 Marathon, Tetris Effect, Puyo Puyo Tetris).
# 5-piece preview, hard drop via d-pad up, hold on the hold button.
GUIDELINE = Rules(
    name="guideline",
    rotation="srs",
    spawn_x=3,                      # standard SRS spawn: 4x4 box's left edge at column 3
    spawn_y=0,                      # top row of the visible board; rows 21-22 are hidden
    has_kicks=True,
    hard_drop=True,
    hold=False,                     # not used by v1's bot
    previews=5,
    colour_to_name={},              # pieces already keyed by name (I/J/L/O/S/T/Z)
)


def rules_by_name(name: str) -> Rules:
    if name == "jakesgordon":
        return JAKESGORDON
    if name == "guideline":
        return GUIDELINE
    raise KeyError(f"unknown Tetris profile {name!r}")


# ---------------------------------------------------------------------------
# Vision profile (G2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisionProfile:
    """Per-game vision settings (TASK-51 G2).

    The `VisionReader` uses these to turn a captured frame into a court + next
    queue. Everything that varies between *games* (not devices) lives here.
    Devices only differ in how to send the keys; that's the userinterface's
    job.

    - auto_detect_court: jakesgordon's dark-bordered court is the only one the
      page draws on a clean background. Tetris 99's 99-board screen fails the
      detection, so it uses a fixed ROI.
    - court_roi: (x, y, w, h) in pixels of the captured frame. Required when
      auto_detect_court is False.
    - cell_px: cell size in pixels; required when auto_detect_court is False.
      Inferred from the auto-detected court otherwise.
    - fill_threshold: a cell is filled when max(R,G,B) - min(R,G,B) >= this.
      Empty cells sit around 30-60; locked jakesgordon cells >= 128;
      Guideline pieces also >= 128; a translucent ghost reads as ~30-90
      (below threshold), so the ghost is ignored.
    - next_rois: list of (x, y, w, h) for each next-piece preview slot.
    - next_cell_px: cell size inside the next-piece ROI.
    """

    name: str
    auto_detect_court: bool = False
    court_roi: Optional[Tuple[int, int, int, int]] = None
    cell_px: int = 0
    fill_threshold: int = 90
    inner: float = 0.25
    next_rois: Optional[List[Tuple[int, int, int, int]]] = None
    next_cell_px: int = 16


# jakesgordon's web page: the reader auto-detects the court and uses the page's
# own piece colour in the next-queue box at (730, 105) (a small 4x4 grid of
# ~16 px cells in the live capture). The next ROI is calibrated once.
JAKESGORDON_VISION = VisionProfile(
    name="jakesgordon",
    auto_detect_court=True,
    cell_px=30,                                 # fallback for non-auto path
    inner=0.25,
    fill_threshold=90,
    next_rois=[(720, 105, 80, 80)],             # 4x4 grid of ~16 px cells
    next_cell_px=16,
)

# Tetris 99 / NSO / Switch: needs a fixed ROI per console. The numbers below
# are placeholders — they'll be calibrated in S0 once the Switch is woken. The
# reader still has to work end-to-end on the jakesgordon profile in v1.
GUIDELINE_VISION = VisionProfile(
    name="guideline",
    auto_detect_court=False,
    court_roi=(0, 0, 300, 600),                 # 10 cols x 20 rows of 30 px
    cell_px=30,
    fill_threshold=80,
    next_rois=[(310, 30, 80, 80)] * 5,           # 5 next slots, calibrated in S0
    next_cell_px=16,
)