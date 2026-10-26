# BUG-0886 — The Pokémon walled its own way to Victory Road 2F and took turns with Route 23

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0886                                                     |
| Reported  | 2026-10-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon's long play stopped for good. The run `20261024-003359` (host-clone-1, the `latest`
lane) was written off as `same_spot` — the same map position for 300 ticks — on map **108**
(Victory Road 1F), position **(8, 17)**, milestone `hall_of_fame`, with 34 milestones done and
`deferred: []` (this is **not** a `deferred_end` stall: nothing was deferred, the story needs the
real game — the way on to Victory Road 2F and the Elite Four). The lock it wrote stopped the lane,
so the game lost every minute until the fix was deployed.

The runner was on the floor's exit mat and asked for the way to the next waypoint, Victory Road 2F
(map 194), tick after tick:

```json
{"kind": "waypoint_unreachable", "map": 108, "wanted": 194, "back": 34}
{"kind": "walk_target", "map": 108, "pos": [8, 17], "target": [9, 17], "branch": "route"}
{"kind": "walk_target", "map": 34,  "pos": [9, 17], "target": [9, 18], "branch": "route", "edge": "south"}
{"kind": "walk_target", "map": 34,  "pos": [4, 33], "target": [4, 31], "branch": "route"}
{"kind": "walk_target", "map": 108, "pos": [4, 31], "target": [4, 35], "branch": "guard"}
{"kind": "walk_target", "map": 108, "pos": [8, 17], "target": [9, 17], "branch": "route"}
… the same four events, for ever …
{"kind": "stalled", "reason": "same_spot", "milestone": "hall_of_fame", "map": 108, "pos": [8, 17]}
```

**Victory Road 1F and Route 23 took turns**: the runner could not reach the stairs of Victory Road 1F,
so BUG-0880's fallback ("the waypoint the guide asks for cannot be reached → walk back to the
waypoint it came from") sent it to Route 23, whose guide asks for Victory Road 1F again.

## Root cause

**The runner walled the corridor to the stairs with its own memory.**

The old fallback that talks to "the nearest person in the way" (`Runner.unblock` →
`wall_on_cap`) talked to the **boulders** of Victory Road 1F, and after three talks it marked their
squares as walls **for good** (`memo["walls"]["108"] = [[2, 10], [5, 15]]` in the canonical save).
BUG-0881 stopped the runner from *talking* to a boulder (`guard_in_reach`, `runner.py:2000`, and
`blocker_on_the_way`, `runner.py:2845`) — but the marks it had already written stayed in the memo,
and `Runner.grid()` (`runner.py:412`) still applied them.

The boulder at **(2, 10)** stands in the one-wide corridor to the stairs (1, 1). Measured on the
canonical save of this stall (the emulator page of `shared/src/lib/game/pokemon/web/`, one frozen
WRAM snapshot, the runner's own `overworld.full_grid`):

| the runner's grid of map 108 | the player's part | the stairs (1, 1) |
|---|---|---|
| the live map, the boulders **not** walled | **190 squares** | reachable, **27 steps** |
| the live map, the boulder at (2, 10) walled | **129 squares** | **out of reach** |

So the floor was cut in two — the player's part 129 squares, the stairs' part 178, and the square
(2, 10) the only link between them — and `world.route(108, 194)` was `None` every tick. That is the
ping-pong.

**Two things the floor's plan did not know.**

1. The floor has a **second** boulder, the one in the corridor to the stairs. `strength.py` named
   only the boulder of the pressure switch (the one at (5, 15)). The corridor boulder was never
   pushed, so it stood in the corridor for ever.
2. The boulder cannot be pushed from the north: the player would have to stand at (2, 9), the far
   side of the boulder. **The pressure switch comes first** — it lifts the barrier on the rocky
   ridge, and only then can the player walk round to (2, 9) and push the boulder **south** out of
   the corridor (three squares, to (2, 13)). Measured: with the boulder on (2, 13) the stairs are
   27 steps away; with it on (2, 9), (2, 11) or (2, 12) they are out of reach.

**And the floor is reset by the game.** The save has seven pushes of the pressure switch logged and
the boulder of the switch back at (5, 15), where it started: the game puts the boulders of a floor
back when the player leaves it and comes back — which is exactly what the ping-pong made it do. A
counter of pushes that survives a reset is a counter of pushes that is never done twice.

## The fix

1. **`Runner.grid()` no longer walls a boulder** (`shared/src/lib/game/pokemon/runner.py:411`). A
   boulder is pushed with Strength, it is not a wall — and a wall on it can seal a floor.
2. **The plan of Victory Road 1F ends with the corridor boulder** (`strength.py`): the pressure
   switch first (the seven pushes of BUG-0885), then `((2, 10), "DOWN", 3)` — the boulder of the
   corridor pushed south out of it.
3. **The counter of a floor's plan is reset when the map the player stands on changes**
   (`runner.py`, `overworld_tick`): a floor that was left and entered again has its boulders back,
   so its pushes start over.

## Evidence

* the stall report of the run (`~/vpt-private/pokemon/canonical/stall_latest.*.json`) and the run
  log and memo of the save (`~/vpt-private/pokemon/canonical/memory_latest.json`);
* the measurements above, taken on the canonical save with the runner's own grid (one frozen WRAM
  snapshot, so the running game cannot move the floor under the measurement);
* a local replay of the canonical save with the fix (`test_scripts/game/local/pokemon_play_local.py`):
  the `waypoint_unreachable` and the ping-pong are gone and the runner walks the floor;
* the guard tests `tests/shared/test_pokemon.py`:
  `test_a_boulder_is_never_a_wall_of_the_map`,
  `test_victory_road_1f_pushes_the_corridor_boulder_out_of_the_way_last`,
  `test_the_victory_road_1f_plan_pushes_the_boulder_onto_the_pressure_switch`.
