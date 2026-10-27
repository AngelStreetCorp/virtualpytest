# BUG-0955 — Victory Road 2F's plan named boulders the floor does not have, and the lane ping-ponged between two floors

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0955                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | shared (pokémon long-play runner)                            |
| Fixed in  | build 90256 |
| Commit    | branch `fix/pokemon-vr2f-switch`                             |

---

## Symptom

The unattended Pokémon Blue lane (TASK-33) stalled on 2026-10-26: the run `20261026-145622`
(host-clone-1) wrote `stall_latest_20261026-145622.json` with the reason `no_progress` — "no
milestone, no new map and no new square for 5 min of game time" — on **map 194** (Victory Road 2F)
at square **(5, 5)**, milestone `hall_of_fame`, 33 milestones done (`earth_badge`), **no deferral**
(`deferred: []`).

The lane **ping-ponged between Victory Road 1F and 2F** (the player goes up and down on the host)
and the detector wrote the stall:

```
{"kind":"push_unreachable","map":194,"boulder":[10,12],"stand":[10,13],"pos":[0,8]}
{"kind":"walk_target","map":194,"pos":[0,8],"target":[1,1],"branch":"route"}
{"kind":"boulder_push","map":194,"boulder":[5,5],"to":[],"direction":"RIGHT","steps":1,"moved":false}
{"kind":"boulder_push","map":194,"boulder":[5,5],"to":[[5,4]],"direction":"UP","steps":1,"moved":true}
{"kind":"boulder_push","map":194,"boulder":[5,4],"to":[[5,3]],"direction":"UP","steps":1,"moved":true}
{"kind":"boulder_push","map":194,"boulder":[5,3],"to":[],"direction":"UP","steps":1,"moved":false}
{"kind":"hop_blocked","map":194,"next":198,"target":[1,1]}
{"kind":"walk_target","map":194,"pos":[5,5],"target":[0,8],"branch":"route"}
{"kind":"push_unreachable","map":108,"boulder":[5,15],"stand":[5,14],"pos":[1,1]}
...
{"kind":"stalled","reason":"no_progress","milestone":"hall_of_fame","map":194,"pos":[5,5]}
```

## Root cause

**The plan of Victory Road 2F named boulders the floor does not have.**

`shared/src/lib/game/pokemon/strength.py` held this plan for the floor:

```python
plan=(((10, 12), "UP", 4), ((12, 8), "RIGHT", 5), ((8, 6), "DOWN", 4)),
```

It was measured on a save whose boulders had already been pushed. Measured on the live save (the
canonical `state_latest.json`, booted in the local emulator):

* map 194 is 30 × 18 squares, with the warps `(0,8) → 108` (Victory Road 1F), `(29,7)/(29,8) → 34`
  (Route 23) and four to Victory Road 3F (map 198): `(1,1)`, `(23,7)`, `(25,14)`, `(27,7)`;
* the **boulders of the fresh floor are `(4, 14)`, `(5, 5)` and `(23, 16)`** — the fresh state is
  confirmed by the run's own first push of every cycle (`boulder_push boulder [5,5]`);
* **none of `(10, 12)`, `(12, 8)`, `(8, 6)` is a boulder of the floor.**

So `strength.chain_step()` never found a rock of the plan, the runner fell back to its own counter,
asked for the stand `(10, 13)` of a rock that is not there, and **gave the floor's plan up**
(`push_unreachable` → `seafoam_plan_given_up`, `runner.py:1424-1432`).

That left the floor to the generic push, and the generic push made it worse:

* the player lands on `(0, 8)`, the west pocket of the floor (73 walkable squares, measured);
* the pocket's **only** way out is the 1-wide niche at `x = 5` — `(5,6) → (5,5) → (5,4) → (5,3)` —
  and `(5,3)` opens into the north-west room with the stair `(1,1) → 198`. The niche boulder at
  `(5,5)` plugs it;
* `push_sealing_rock_aside()` (`runner.py:2646-2703`) tries the directions **UP, DOWN, LEFT, RIGHT**
  and takes the first one the *game* accepts. RIGHT was refused (the destination `(6,5)` is a wall,
  tile 18) — and it was refused for a second reason as well: the push code steps **before** it
  selects Strength (`runner.py:2687-2691`), so the first attempt always walks into a boulder without
  Strength in use. UP was then accepted, and it pushed the rock **along** the niche to `(5,4)` and
  `(5,3)`, where it plugs the niche even harder: it cannot be pushed down, the stand `(5,2)` is a
  wall.

The generic push therefore never opened the way, it sealed the pocket, marked the hop `(194 → 198)`
blocked and sent the runner back up to Victory Road 1F — for ever.

## Fix

`shared/src/lib/game/pokemon/strength.py`: **the plan of Victory Road 2F is the published
walkthrough's**, measured against the live save.

Bulbapedia, *Walkthrough:Pokémon Red and Blue/Part 15*, §2F: *"Another boulder can be found to the
south. Push this one southwestward (←1, ↓2, ←2) to reach the switch and clear the next barrier."*
and, in the walkthrough of the same floor: *"You'll start off on the west side of the second floor.
Directly to the south is another boulder. Push this boulder left, down, down, and left onto the
button."*

The boulder to the south of the landing square `(0,8)` is the one at **`(4, 14)`**:

```python
plan=(((4, 14), "LEFT", 1),      # west of the pocket's south boulder
      ((3, 14), "DOWN", 2),      # down to (3, 16)
      ((3, 16), "LEFT", 2)),     # onto the switch at (1, 16)
switch_at=(1, 16),
```

`(1, 16)` is the floor's **switch tile (45)** — measured on the live save, together with the other
switch tile at `(9, 16)` — so the plan ends on the switch that lowers the barrier of the floor.

The plan key changes, so the runner starts the new plan from the beginning and forgets the old
plan's "given up" mark (`runner.py:1329-1333`, BUG-0881): the stale `seafoam_pushes_done: 3` and
`seafoam_plan_given_up: true` of the save cannot skip the new pushes.

## Verification

- Guard test `test_the_plan_of_victory_road_2f_pushes_the_boulder_of_the_south_onto_the_switch`
  (fails without the fix), plus the updated
  `test_victory_road_2f_layout_returns_three_pushes_in_canonical_order`.
- `python3 -m pytest -q tests/shared/test_pokemon.py` → see the release note.
- The diagnosis, with the measured geometry of the floor:
  `~/vpt-private/pokemon/stalls/stall_latest_20261026-145622.diagnosis.md`.

## Still open (not this bug)

* The generic push still steps before it selects Strength (`runner.py:2687-2691` and
  `runner.py:2624-2628`), so its first attempt at a rock is always refused by the game and the
  refusal is remembered as a refusal. Harmless on this floor now (the plan does the work), but it
  makes the generic push weaker than it looks.
* The play of a run that dies mid-way is still lost (the state and the memory are written at the
  end of a run).
