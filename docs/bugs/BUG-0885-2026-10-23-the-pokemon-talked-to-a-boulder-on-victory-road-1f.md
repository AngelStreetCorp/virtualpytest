# BUG-0885 — The Pokémon talked to a boulder on Victory Road 1F and stood still for 300 ticks

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0885                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon's long play stopped for good. The run `20261023-231857` (host-clone-1, the `latest`
lane) was written off as `same_spot` — the same map position for 300 ticks — on map **108**
(Victory Road 1F), position **(5, 16)**, milestone `hall_of_fame`, with 33 milestones done and
`deferred: []` (this is **not** a `deferred_end` stall). The lock it wrote stopped the lane, so the
game lost every minute until the fix was deployed.

The game was fine and the player was standing next to a **boulder**. The last events of the run:

```json
{"kind": "walk_target", "map": 108, "pos": [9,16], "target": [5,15], "branch": "guard"}
{"kind": "npc_walled", "who": "guard", "map": 108, "square": [5,15], "talks": 3}
{"kind": "lost", "map": 108, "next": 34}
{"kind": "stalled", "reason": "same_spot", "milestone": "hall_of_fame", "map": 108, "pos": [5,16]}
```

The runner walked to the boulder at (5, 15), pressed **A** on it three times and then stood still.

## Root cause

**Three faults in a row, each of which the earlier fixes made permanent.**

**1. The plan of the floor was a push that cannot be set up.**
`strength.py` held `plan=(((2, 10), "DOWN", 2),)` for Victory Road 1F: push the boulder at (2, 10)
two squares down, with the player north of it at (2, 9). That boulder stands in the **one-wide
passage** to the stairs at (1, 1), so the square the push starts from is on the far side of the
boulder — the boulder seals the very passage the push needs. Measured on the canonical save in the
emulator: the player's part of the floor is 129 squares, the stairs' part 178, and the square
(2, 10) is the only link between them. The push was therefore given up
(`push_unreachable`, `runner.py:1295-1306`), and the give-up **closed the floor for good**:
`seafoam_pushes_done = len(plan)` (`runner.py:1304`). The memo of the run still carries
`seafoam_pushes_done: 1` and the old plan, so the floor was never tried again.

**2. The "no route" fallback talked to a rock.**
With the puzzle closed, `go_to_map` found no route to Victory Road 2F and fell back to
`guard_in_reach` (`runner.py:1976`): *"the nearest **person** standing in the player's part"*. That
helper took **every sprite** in the part — and on this floor the nearest sprite is the picture-63
**boulder** at (5, 15), one square from the player. Talking to a boulder does nothing at all: the
three talks were counted, the boulder was marked as a wall, and the player stood still for 300 ticks.
`unblock` / `blocker_on_the_way` (`runner.py:2815`) had the same flaw.

**3. The push of Victory Road 1F was never the puzzle of that floor.**
The published puzzle of Victory Road 1F (Bulbapedia, *Walkthrough:Pokémon Red and Blue/Part 15*) is
the **pressure switch**: *"Near the entrance, there is a boulder to the west and a pressure switch to
the east. To activate the switch, use Strength to move the boulder eastward (↓1, →4, ↑2, →7, ↑2, →1,
and ↓1)."* The switch lifts the barrier on the rocky ridge and opens the way north. The switch is
verifiable in the ROM: tile **45** occurs exactly once on the floor, at **(17, 13)**, and the
published push sequence ends exactly there — from the boulder at (5, 15): ↓1 → (5, 16), →4 → (9, 16),
↑2 → (9, 14), →7 → (16, 14), ↑2 → (16, 12), →1 → (17, 12), ↓1 → **(17, 13)**.

## Fix

1. **`strength.py`** — the plan of Victory Road 1F is the pressure switch: the boulder west of the
   entrance is pushed onto the switch east of it, in the seven pushes above, each naming the square
   the boulder stands on before the push.
2. **`runner.py` (`strength_puzzle_step`)** — a plan that changed starts its pushes over: the
   counter of the old plan (closed by the give-up) would skip the pushes of the new one. The key is
   a string, so it survives the save/load round trip of the memo unchanged.
3. **`runner.py` (`guard_in_reach`, `blocker_on_the_way`)** — a boulder (picture 63) is never a
   person: it is never talked to and never counted as a blocker to talk away.
4. **`runner.py` (`avoid_warps`)** — the square the push of Victory Road 1F starts from is the exit
   mat **(9, 17)**, and it can only be reached over its twin **(8, 17)**. An exit mat (a warp square
   on the border of the map) fires when the player steps *off* the map, not when he steps on it, so
   the border warp squares may be crossed when the runner walks to a warp square of the map.

The whole plan was replayed against the measured floor of the canonical save (the runner's own grid,
the boulder moving after every push): every stand square is reachable and the boulder ends exactly
on the switch at (17, 13).

Guard tests: `test_the_victory_road_1f_plan_pushes_the_boulder_onto_the_pressure_switch`,
`test_a_push_plan_that_changed_starts_its_pushes_over`,
`test_a_boulder_is_never_talked_to_as_a_guard`,
`test_an_exit_mat_may_be_crossed_on_the_way_to_a_warp_square`.
185 pokemon tests pass.

## Verification

- `python3 -m pytest -q tests/shared/test_pokemon.py` → **185 passed**.
- The plan of Victory Road 1F was replayed on the floor measured in the emulator (the canonical
  save, read-only): 7 of 7 pushes executable, the boulder on the switch at (17, 13).
- The diagnosis of the stall, with the events and the measurements:
  `~/vpt-private/pokemon/stalls/stall_latest_20261023-231857.diagnosis.md`.

## Files

- `shared/src/lib/game/pokemon/strength.py` — the plan of Victory Road 1F.
- `shared/src/lib/game/pokemon/runner.py` — the counter of the pushes, the guard fallback, the
  blocker on the way, the path over an exit mat.
- `tests/shared/test_pokemon.py` — four guard tests.
