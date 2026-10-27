"""
Strength boulder puzzles: Seafoam Islands (drain) and Victory Road (path).

A puzzle is a known map id (Seafoam B3F/B4F, Victory Road 1F/2F/3F) with a fixed number of
boulders and holes. The solver reads the live boulder sprite positions and returns the
canonical push order; the runner walks to each boulder, faces it, presses A and walks
the indicated number of steps. A boulder pushed into a hole disappears from the sprite
list (and may drain the water floor).

Map ids confirmed against `pokered/constants/map_constants.asm` (commit ref-pret):
- Seafoam B3F = $A1, B4F = $A2, 1F = $C0; Victory Road 1F = $6C, 2F = $C2, 3F = $C6.
- Boulder sprite picture id = $3F = 63 (SPRITE_BOULDER, pokered/constants/sprite_constants.asm).

Out of scope for this module:
- The HM-slave party member that frees the leader's PP (`TASK-33` §"Ideas"). The same leader
  pushes every boulder; the puzzle is faster with a slave but solvable with one.
- Surf and Strength acquisition: covered by `surf` and `strength` milestones in
  `milestones.py` (already green on the emulator).
- Drains on B4F currents: returned via `PuzzleLayout.currents` for the runner to apply
  post-step; the planner itself does not simulate currents (verified at runtime).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import overworld
from .memory import Read

# pokered constants/sprite_constants.asm: SPRITE_BOULDER = $3F = 63.
BOULDER_PICTURE = 63

# Map ids (pokered/constants/map_constants.asm). Used by `plan_strength_puzzle(read, here)` and
# by `milestones.py` for the new `seafoam`/`earth_badge` paths. Note: CAPTAINS_ROOM = 0x65 in
# milestones already; these ids do not collide.
SEAFOAM_1F, SEAFOAM_B1F, SEAFOAM_B2F = 0xC0, 0x9F, 0xA0
SEAFOAM_B3F, SEAFOAM_B4F = 0xA1, 0xA2
SEAFOAM_ISLANDS = (SEAFOAM_1F, SEAFOAM_B1F, SEAFOAM_B2F, SEAFOAM_B3F, SEAFOAM_B4F)

VICTORY_ROAD_1F, VICTORY_ROAD_2F, VICTORY_ROAD_3F = 0x6C, 0xC2, 0xC6
VICTORY_ROAD = (VICTORY_ROAD_1F, VICTORY_ROAD_2F, VICTORY_ROAD_3F)

# Adjacent maps the milestones cross.
INDIGO_PLATEAU, INDIGO_PLATEAU_LOBBY, HALL_OF_FAME = 0x09, 0xAE, 0x76
CINNABAR_ISLAND, CINNABAR_GYM, MANSION_1F = 0x08, 0xA6, 0xA5
ROUTE_22, ROUTE_23 = 0x21, 0x22

# A single push action. The player walks to `boulder`, faces `direction`, presses A and walks
# `steps` squares; each step pushes the boulder one tile in `direction` until it lands in a hole
# (the boulder disappears) or runs into another boulder / a wall (the runner stops the push).
Push = Tuple[Tuple[int, int], str, int]   # ((x, y), "UP"|"DOWN"|"LEFT"|"RIGHT", steps)


@dataclass(frozen=True)
class PuzzleLayout:
    """The static part of one Strength puzzle. The boulder positions are read live; everything
    else (holes, push order, currents) is constant per map id."""
    name: str
    # Canonical solution: which boulder to push, in which direction, how many steps. Pushed-into-
    # hole boulders leave the sprite list, so the next push isn't blocked by them. Coordinates
    # are in map squares (1 square = 2 tiles); the puzzle maps are 30 x 18 squares (15 x 9 blocks).
    plan: Tuple[Push, ...]
    # Boulder sprite count when the puzzle is open. When the live count drops below this, the
    # puzzle is partially or fully solved and a new plan is not needed.
    boulders_open: int
    # Currents: (x, y) -> (dx, dy). A step onto the current square pushes the player in (dx, dy).
    # Seafoam B4F only (Generation I tiles $2D and $3D). The planner does not use this; it is
    # exposed for the runner to integrate into the grid (see TASK-34 §"Open questions").
    currents: Dict[Tuple[int, int], Tuple[int, int]] = field(default_factory=dict)
    # BUG-0892: the pressure switch of a floor (the square the chain's last boulder rests on) opens
    # a barrier of the floor while the boulder lies on it: the wall pairs the barrier is made of.
    # Victory Road 1F: the barrier on the rocky ridge, between (5, 8)-(7, 8) and (5, 9)-(7, 9).
    switch_at: Optional[Tuple[int, int]] = None
    switch_opens: Tuple[Tuple[Tuple[int, int], Tuple[int, int]], ...] = ()


# Canonical push plans. The coordinates mirror the published maps:
#   - Seafoam B3F / B4F (15 x 9 blocks = 30 x 18 squares), boulders arrayed in a 4-around-pillar
#     pattern around the central water column. The exact per-save coords vary; the planner reads
#     boulder sprites live and uses these as the push directions and step counts.
#   - Victory Road 1F / 2F / 3F (15 x 9 blocks / 10 x 9 blocks), one or three boulders blocking
#     the path; the south-first ordering is what the runner must follow.
# Tests inject their own layouts via `PUZZLES[map_id] = ...` when they want different coordinates.
PUZZLES: Dict[int, PuzzleLayout] = {
    SEAFOAM_B3F: PuzzleLayout(
        name="Seafoam B3F",
        # 4 boulders; push each DOWN into the hole two squares south of it (canonical plan).
        plan=(
            ((12, 6), "DOWN", 3),
            ((14, 6), "DOWN", 3),
            ((12, 8), "DOWN", 3),
            ((14, 8), "DOWN", 3),
        ),
        boulders_open=4,
    ),
    SEAFOAM_B4F: PuzzleLayout(
        name="Seafoam B4F",
        # 4 boulders; push each UP into a hole two squares north. The currents below are the
        # Gen 1 B4F water currents; integrate them into the grid or apply post-step.
        plan=(
            ((12, 12), "UP", 2),
            ((14, 12), "UP", 2),
            ((12, 14), "UP", 2),
            ((14, 14), "UP", 2),
        ),
        boulders_open=4,
        # Canonical B4F currents (pokered attributes/seafoam_islands_b4f.asm): two push left, two
        # push right.
        currents={
            (8, 8): (-1, 0),
            (22, 8): (1, 0),
            (8, 14): (-1, 0),
            (22, 14): (1, 0),
        },
    ),
    VICTORY_ROAD_1F: PuzzleLayout(
        name="Victory Road 1F",
        # The pressure switch of the floor: the boulder west of the entrance is pushed onto the switch
        # east of it, which lifts the barrier on the rocky ridge and opens the way north.
        # BUG-0874: the plan used to say (8, 12) - the square the player already stands on - and
        # "DOWN", which no boulder of that floor could answer.
        # BUG-0881: the plan then said (2, 10) "DOWN" 2 - a push that cannot be set up: that boulder
        # stands in the one-wide passage to the stairs (1, 1) and the plan wanted the player north of
        # it at (2, 9), the far side of the boulder, which the boulder itself seals (the player's part
        # of the floor is 129 squares, the stairs' part 178, and the square (2, 10) is the only link
        # between them). The published puzzle of the floor (Bulbapedia, "Walkthrough:Pokemon Red and
        # Blue/Part 15": "Near the entrance, there is a boulder to the west and a pressure switch to the
        # east. To activate the switch, use Strength to move the boulder eastward (down 1, right 4, up 2,
        # right 7, up 2, right 1, and down 1)") is the pressure switch, and the sequence ends exactly on
        # it: the switch is the only tile 45 of the floor, at (17, 13). Each push names the square the
        # boulder stands on before the push.
        # BUG-0886: the floor has a second boulder, the one in the corridor to the stairs: it is the
        # only link between the player's part of the floor and the stairs (1, 1), and it cannot be
        # pushed from the north - the player cannot stand at (2, 9), the far side of the boulder. The
        # switch comes first: the pressure switch lifts the barrier on the rocky ridge (the tiles at
        # (5, 8)-(7, 9) of the cave tileset), and only then can the player walk round to (2, 9) and
        # push the boulder SOUTH out of the corridor (three squares, to (2, 13) - measured on the
        # stalled save: with the boulder on (2, 13) the stairs are 27 steps away, with it on (2, 9),
        # (2, 11) or (2, 12) they are out of reach). So the corridor push is the last one.
        plan=(
            ((5, 15), "DOWN", 1),     # the boulder west of the entrance
            ((5, 16), "RIGHT", 4),
            ((9, 16), "UP", 2),
            ((9, 14), "RIGHT", 7),
            ((16, 14), "UP", 2),
            ((16, 12), "RIGHT", 1),
            ((17, 12), "DOWN", 1),     # onto the pressure switch at (17, 13)
            ((2, 10), "DOWN", 3),     # the boulder in the corridor to the stairs: pushed south out of it
        ),
        boulders_open=1,
        # BUG-0892: the boulder that rests on the pressure switch (17, 13) opens the barrier on
        # the rocky ridge: the pairs (5, 8)-(5, 9), (6, 8)-(6, 9) and (7, 8)-(7, 9). Measured on the
        # live save: opening any one of them grows the player's part of the floor from 129 squares
        # to 292 and the stairs (1, 1) and the stand square (2, 9) of the corridor push are then
        # walkable. The grid kept the barrier for ever, so the corridor push could not be set up
        # and the floor could not be finished.
        switch_at=(17, 13),
        switch_opens=(((5, 8), (5, 9)), ((6, 8), (6, 9)), ((7, 8), (7, 9))),
    ),
    VICTORY_ROAD_2F: PuzzleLayout(
        name="Victory Road 2F",
        # BUG-0955: the plan of this floor was measured on a save whose boulders had already been
        # pushed: it named (10, 12), (12, 8) and (8, 6), and none of them is a boulder of the
        # floor (the live boulders of the floor are (4, 14), (5, 5) and (23, 16)), so the chain
        # never found a rock, the floor's plan was given up and the lane ping-ponged between
        # Victory Road 1F and 2F until the detector wrote no_progress (the run of 20261026-145622).
        # The published walkthrough (Bulbapedia, "Walkthrough:Pokemon Red and Blue/Part 15", §2F):
        # "Another boulder can be found to the south. Push this one southwestward (←1, ↓2, ←2) to
        # reach the switch and clear the next barrier." The boulder to the south of the landing
        # square (0, 8) is the one at (4, 14): ←1 puts it on (3, 14), ↓2 on (3, 16) and ←2 on the
        # switch at (1, 16) - the tile 45 of the floor, measured on the live save.
        plan=(
            ((4, 14), "LEFT", 1),
            ((3, 14), "DOWN", 2),
            ((3, 16), "LEFT", 2),
        ),
        boulders_open=3,
        switch_at=(1, 16),
    ),
    VICTORY_ROAD_3F: PuzzleLayout(
        name="Victory Road 3F",
        # One boulder down the corridor; push DOWN into the gap.
        plan=(((5, 8), "DOWN", 4),),
        boulders_open=1,
    ),
}


def _live_boulders(read: Read) -> List[Tuple[int, int]]:
    """The on-screen boulder sprite positions read live from memory. Off-screen sprites appear as
    `0xFF` (hidden) in `overworld.sprite_list` and are filtered out; for the puzzles above all
    boulders live on screen while the player is in the room, so `sprite_list` is sufficient."""
    try:
        sprites = overworld.sprite_list(read)
    except Exception:
        return []
    return [pos for pic, pos in sprites if pic == BOULDER_PICTURE]


live_boulders = _live_boulders   # the public name: the runner reads the floor's boulders live


def plan_strength_puzzle(read: Read, here: int) -> Optional[List[Push]]:
    """The Strength push sequence for `here`, or `None` if no puzzle or already solved.

    The push list is the canonical solution the runner can execute blindly: walk to the
    boulder, face `direction`, press A and walk `steps` squares. The planner doesn't simulate
    A* around the boulders (the runner does that between pushes); it just tells the runner
    which boulder next and in which direction.

    `None` is returned when:
      - `here` is not a Strength puzzle map (no entry in `PUZZLES`), or
      - the live boulder sprite count is below the puzzle's `boulders_open` threshold
        (one or more boulders have already been pushed into holes).
    """
    layout = PUZZLES.get(here)
    if layout is None:
        return None
    if len(_live_boulders(read)) < layout.boulders_open:
        return None
    return list(layout.plan)


def chain_step(plan, live, upto=None) -> Optional[tuple]:
    """Where the chain of a floor is, read from the live boulders: the step to do next, the square
    the rock stands on, the square it has to reach, the direction and how many squares are left.

    BUG-0896: the plan's counter was the runner's own guess about the rock, and it lied. A push
    that did not move the rock was counted all the same, so the chain went on with a rock that
    stood somewhere else (the run of 20261024-225457: the rock stood at (7, 16) while the chain
    believed it was on (9, 16), (9, 14), (16, 14)...). The rock is the truth about the chain: it
    says which push is next, and a rock that stands between two squares of the plan is pushed on
    to the end of the step it is in.

    BUG-0891: a rock that is out of sight is not a rock that is gone, so the chain never jumps to a
    LATER push of the plan because another rock happens to be in sight. `upto` is the step the
    counter is on: the chain may only be pulled BACK to the step of the rock that is really there.

    BUG-0896: a rock one square BEHIND the square a step starts from is the same rock: it was
    pushed the wrong way and the player ended up on the wrong side of it (the run of 20261024-225457:
    the rock of the pressure switch stood at (9, 14) and the player east of it, while the plan's
    push needs the player west of it). Such a rock is pushed on to the end of the step it is in.

    `live` is the set of the squares the floor's rocks stand on (read live from the sprites).
    None when no rock of the chain is in sight.
    """
    steps = list(plan) if upto is None else list(plan)[:upto + 1]
    # the rock that stands on the square a step starts from
    for i, (sq, direction, count) in enumerate(steps):
        start = (int(sq[0]), int(sq[1]))
        if start in live:
            dx, dy = overworld.STEP[direction]
            return i, start, (start[0] + dx * count, start[1] + dy * count), direction, count
    # the rock that stands between the start and the end of a step (a push that was cut short), and
    # the rock that stands one square behind the start (it was pushed the wrong way and the player
    # is on the wrong side of it)
    for i, (sq, direction, count) in enumerate(steps):
        start = (int(sq[0]), int(sq[1]))
        dx, dy = overworld.STEP[direction]
        target = (start[0] + dx * count, start[1] + dy * count)
        for k in range(1, count):
            mid = (start[0] + dx * k, start[1] + dy * k)
            if mid in live:
                return i, mid, target, direction, count - k
        behind = (start[0] - dx, start[1] - dy)
        if behind in live:
            return i, behind, target, direction, count + 1
    return None


def switch_step(layout: Optional[PuzzleLayout]) -> int:
    """The index of the chain step that lands the boulder on the switch of the floor, -1 when the
    floor has no switch.

    BUG-0892: the boulder that rests on the pressure switch is not a sprite on the screen any more
    (the switch tile shows it), so the runner cannot read the switch from the game: it knows it put
    the boulder there itself."""
    if layout is None or not layout.switch_at:
        return -1
    switch = (int(layout.switch_at[0]), int(layout.switch_at[1]))
    for i, (sq, direction, steps) in enumerate(layout.plan):
        dx, dy = overworld.STEP[direction]
        if (int(sq[0]) + dx * steps, int(sq[1]) + dy * steps) == switch:
            return i
    return -1


def puzzle_for(map_id: int) -> Optional[PuzzleLayout]:
    """The static layout for `map_id`, or `None` if no puzzle is known on that map. Used by
    `milestones.py` to decide whether a map is part of the strength path (without a live read)."""
    return PUZZLES.get(map_id)
