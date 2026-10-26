# BUG-0874 — Victory Road 1F's boulder never moved: the plan named the wrong square and the push was never armed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0874                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The long play reached the last floor before the Indigo Plateau and stopped there: the run stood on
Victory Road 1F (map 108) at (8, 12) and never moved again, with `no path` on every tick.

The stall of run `20261023-132854` was reported from the same place, and a local replay of the same
save shows the same behaviour without any host involved:

```
{"ticks": 776, "counts": {"walk": 104, "surf failed": 1, "surf": 1, "text": 57, "cutscene": 1, "no path": 612},
 "milestone": "hall_of_fame", "map": 108, "pos": [8, 12], "party": 5, "stalled": null}
```

612 of the 776 ticks were `no path`: the runner was asking for a path to a square it already stood on.

## Root cause

Three faults, one after the other.

**1. The canonical push plan did not match the floor.**
`shared/src/lib/game/pokemon/strength.py` — `PUZZLES[VICTORY_ROAD_1F]`:

```python
plan=(((8, 12), "DOWN", 5),),      # the boulder
```

(8, 12) is **the square the player stands on**, and no boulder of that floor is there. The live floor
(read from the game's sprite list) holds three picture-63 boulders:

```
boulders: [(5, 15), (14, 2), (2, 10)]
```

Only the one at **(2, 10)** stands in the one-wide passage between the rows 9 and 11, and with the
boulders in the way the stairs at (1, 1) are unreachable at all (`overworld.astar` returns `None`
from the entrance (8, 17) to the exit (1, 1)).

**2. The push was never armed.** The runner pressed A on the boulder and walked into it. The game
answers "the boulder won't budge": the field move has to be the one in use. The runner had the right
helper all along — `hm.use_field_move` is how Surf and Cut are used — but not for Strength. The
evidence that the push never worked: the memo of the save says `seafoam_drained_b3f: None` and
`seafoam_pushes_done: 0`, so the Seafoam floors were never drained either.

**3. The player walked to the boulder, not to the side the push starts from.** The boulder blocks its
own square, so A* parks the player on an arbitrary side of it, and when that is not the side the push
needs, the runner walks to the boulder again and again.

## Fix

`shared/src/lib/game/pokemon/strength.py`

- The plan of Victory Road 1F is the boulder that really blocks the corridor: `((2, 10), "DOWN", 2)` —
  **down**, with the player **north** of it at (2, 9): the passage is one square wide, so the player
  cannot get south of the boulder to push it up, and the boulder slides down to the wall at (2, 14),
  which frees the corridor to the stairs.

`shared/src/lib/game/pokemon/hm.py`

- `strength_user()` and `use_strength()`: START, POKéMON, the Pokémon that knows Strength (Onix in
  the current save), FORCE in its field-move box — the flow Surf and Cut already use.

`shared/src/lib/game/pokemon/runner.py`

- The runner walks to the square the push starts from (the boulder, one square back), so the push
  always begins on the right side of the boulder.

Verified in a local replay of the stalled save: the runner now walks to (2, 11) next to the boulder,
arms Strength and **the boulder moves** (it left (2, 10) — the game refused to move it before).

## What is still open

The floor is not passable yet, and that is the next piece, not this one:

* The player must stand **north** of the boulder, at (2, 9), to push it down — and the north side is
  not reachable from where the runner stands: the grid's tile-pair walls at ((7, 8), (7, 9)) and
  ((11, 9), (11, 10)) cut the runner's 71 reachable squares off from the middle of the floor. Those
  are the game's **jump tiles** (the green ledges), and `overworld.full_grid` only models the
  overworld tileset's ledges as jumps, so the runner's A* refuses them.
* Until the ledges are modelled, the plan's stand square (2, 9) is out of reach and the run stalls on
  the floor with the boulder in the way.

The same gap blocks the Seafoam floors (their pushes also need the player on the far side of the
boulder). `docs/tasks/TASK-33-handover.md` carries the details.

## Verification

`python3 -m pytest -q tests/shared/test_pokemon.py` — 171 passed, including
`test_the_victory_road_boulder_plan_names_the_boulder_that_blocks_the_corridor` and
`test_the_runner_walks_to_the_side_the_push_needs_when_the_plan_names_no_boulder`.
