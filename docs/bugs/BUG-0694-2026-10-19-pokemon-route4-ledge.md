# BUG-0694 — Pokémon runner walks into Route 5's pocket: Route 4's ledge is one-way

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0694                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon (TASK-33)                                     |
| Fixed in  | build 90145 |
| Commit    | see `git log -- shared/src/lib/game/pokemon/milestones.py`   |

---

## Symptom

Run `20261019-160255` (host-clone-1) stalled `no_progress` on milestone `seafoam` at Route 5 (16) (10, 29): for 5 min it
walked between Route 5's south pocket and its gate house (70) (`walk_target 16 (3, 0) -> (3, -1) north`,
`16 (9, 29) -> (10, 29)`, `70 (10, 29) -> (3, 0)`, about 10 times).

## Root cause

The BUG-0693 guide went from Cerulean west over Route 4 and Route 3 to Pewter. Route 4's ledge only drops east, so
Cerulean is no way back west. After the Cerulean heal the runner found no route to Route 4 (`walk_target 3 (3, 7) ->
(-1, 7) west`), explored south into Route 5 and ping-ponged in the pocket BUG-0639 already met.

A replay of the save with the new guide still ping-ponged, between the gate house (70) and Route 5's last row above
Saffron's gym (`lost map 70 next 7`): the memo kept `bad_exits` on Route 5's south edge (into Saffron) and north edge (into
Cerulean), marked under older milestones. Clearing the stall lock kept them (`game_pokemon.py` reset only the counters).

## Fix

The `seafoam` guide leaves Route 12 west: Route 11, Diglett's Cave (the Route 11 house, the cave, the Route 2 house),
Route 2, Viridian, Route 1, Pallet Town, Route 21, Cinnabar. The Route 11 and Route 2 gates and Viridian Forest are in
`area`. Clearing a stall lock (`--clear_stall yes`) also drops the way-marks (`stall.forget_on_unlock`: bad exits and doors,
the edge entry, the "lost" note); the runner relearns any real one in a few ticks. Guard tests:
`test_seafoam_goes_by_diglett_cave_not_back_over_route4_ledge`, `test_a_cleared_stall_forgets_the_way_marks_that_walled_it_in`.

## Verification

Replay of the stall save with the lock cleared (`~/vpt-private/pokemon/stall160255/`): Route 5 -> Saffron -> Route 7 within
a minute, no ping-pong. Then the live run after `clear-stall` on the deployed hosts (see the TASK-33 handover).
