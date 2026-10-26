# BUG-0696 — Pokémon runner steps on Route 7 gate's dead door square for 5 min

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0696                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon (TASK-33)                                     |
| Fixed in  | build 90145 |
| Commit    | see `git log -- shared/src/lib/game/pokemon/runner.py`       |

---

## Symptom

Run `20261019-164824` (host-clone-1) stalled `no_progress` on milestone `seafoam` at Route 7 (18) (19, 9): after
`walk_target 18 (19, 2) -> (18, 9) route` it spent 5 min (361 `exit mat` ticks) stepping on and off (18, 9), the east door
of Route 7's gate house (76).

## Root cause

The gate has two east door squares, (18, 9) and (18, 10). Only (18, 10) fires (verified on the emulator: a LEFT from
(19, 10) enters the gate; any press on or into (18, 9) does nothing). The runner takes the nearer square, (18, 9).
The route step marks a door unusable after `stuck >= 6`, but `step_off_warp` moves the player every tick (off the mat
and back on), which resets `stuck`, so the dead square was never marked and the twin never tried.

## Fix

`step_off_warp` (`shared/src/lib/game/pokemon/runner.py`): after every side was tried twice on one door square, and another
door leads to the same map, the square goes to `bad_warps` (`warp_unusable` event) and the route takes the twin. A sole
door is left to the BUG-0634 retry. Guard test:
`test_a_door_square_that_never_fires_is_marked_and_its_twin_is_taken` in `tests/shared/test_pokemon.py`.

Replay of the stalled save: Route 7 gate -> Underground Path -> Route 8 -> Lavender -> Route 12 within 90 s.
