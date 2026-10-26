# BUG-0889 — A wall mark outlived its boulder and sealed Victory Road 1F

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0889                                                     |
| Reported  | 2026-10-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The `latest` lane stopped again, one stall after BUG-0888. The run `20261024-093928` (host-clone-1)
played for **23 minutes** (against ~190 s for every stalled run — BUG-0888's heal-trip freeze was
gone and the runner really plays now) and was written off as `no_progress` — "no milestone, no new map
and no new square for 5 min of game time" — on **map 108 (Victory Road 1F)** at **(7, 16)**,
milestone `hall_of_fame`, `deferred: []`.

The runner worked the floor's Strength plan over and over and never finished it:

```json
{"kind": "push_unreachable", "map": 108, "boulder": [2, 10], "stand": [2, 9], "pos": [16, 13]}
{"kind": "walk_target", "map": 108, "pos": [16, 13], "target": [1, 1], "branch": "route"}
{"kind": "boulder_push", "map": 108, "boulder": [2, 10], "to": [[2, 9]], "direction": "UP", "steps": 1, "moved": true}
{"kind": "walk_target", "map": 108, "pos": [2, 10], "target": [8, 17], "branch": "route"}
```

The floor's last push is `((2, 10), "DOWN", 3)`: the corridor boulder has to go **south**, out of the
one-wide passage to the stairs (1, 1), and to push it south the player has to stand **north** of it,
at (2, 9). The runner could not get there, the plan gave up, and the generic "push the boulder out of
the way" took over and pushed it the **wrong way** — north into the alcove at (2, 9), from where the
game refuses to push it any further. The boulder then stood on the only link between the player's
part of the floor and the stairs' part, so the guide's way on (Victory Road 2F) had no route: the
runner walked back to the exit mat (8, 17), left for Route 23, came back (the game restores the
boulders), worked the plan again and failed again — 37 boulder pushes, four times round the floor.

## Root cause

**A wall mark outlived the boulder it belonged to.**

The save's own memory still holds the floor's two boulders under `memo["walls"]`:

```
memory_latest.json → memo["walls"]["108"] = [[2, 10], [5, 15]]
```

`walls` marks a square as unwalkable for A* (a beaten trainer that never moves). These two marks are
left over from the old bug of BUG-0885: the runner used to *talk* to the boulders (the fallback that
talks to "the nearest person in the way"), and three talks marked them as walls for good. BUG-0886
stopped the talking and made `grid()` **skip** a wall on a square that still holds a boulder — but
the mark itself was never dropped. A boulder that is pushed away leaves its mark behind, and the mark
then becomes a wall on an **empty** square: exactly the passage to the stairs.

Measured on the stalled save with the runner's own grid:

```
WITH the stale walls        (2,9) reachable False   (1,1) reachable False   <- the floor is cut in two
WITHOUT the wall on (2,10)  (2,9) reachable True    (1,1) reachable True    <- the stairs are there
```

The chain:

1. the stale mark on (2, 10) seals the one-wide passage to the stairs;
2. the player cannot reach (2, 9) to push the corridor boulder south (`push_unreachable`), so the
   floor's plan gives up (`seafoam_pushes_done = len(plan)`);
3. the generic push shoves the boulder **north** into the alcove at (2, 9), from where the game
   refuses to push it further and the player cannot stand behind it to push it back;
4. the guide's way on (Victory Road 2F) has no route, so the runner leaves the floor and begins it
   again, for ever.

## Fix

`shared/src/lib/game/pokemon/runner.py` (`Runner.grid()`)

The marks on the squares a floor's puzzle names — the squares its boulders stand on — are dropped,
exactly like the mark on a boulder that is still there (BUG-0886). A boulder is a rock, not a person,
and the mark must not survive the rock.

The passage to the stairs opens again, and the plan's last push (the boulder south out of the
corridor, to (2, 13)) can be set up again. The local replay of the stalled save with the fix shows
the runner heading for the stairs at once:

```json
{"kind": "walk_target", "map": 108, "pos": [7, 16], "target": [1, 1], "branch": "route"}
```

## Tests

`tests/shared/test_pokemon.py::test_a_wall_mark_does_not_outlive_the_boulder_it_belongs_to` — a
boulder that has left its square must not leave a wall there, and the people that stay (a beaten
trainer) are still walls. 191 pokemon tests pass.

## What is left

The save this run left behind has the corridor boulder **wedged at (2, 9)**: the game refuses to push
it north any further, and the player cannot stand north of it to push it back south. Two things
follow, and they are the next fixes:

1. **the generic push must not shove a boulder the wrong way** — the plan says the corridor boulder
   goes south, the generic push sent it north; the plan has to win over the generic push;
2. **the plan must not be given up when the stand square is unreachable** — `push_unreachable` ends
   the floor's plan and hands the floor over to the generic push, which is what wedged the boulder.

A fresh entry into the floor works with BUG-0889 alone. The diagnosis is in
`~/vpt-private/pokemon/stalls/stall_latest_20261024-093928.diagnosis.md`.

## In plain words

The Pokémon pushed a rock out of a doorway, but the note it had left on the rock's square said
"wall here" — and a wall on an empty square closes the floor for good. The note goes with the rock.
