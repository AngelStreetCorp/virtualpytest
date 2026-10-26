# BUG-0880 — The Pokémon stood still on Route 23: the guide asked for a map the runner cannot reach

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0880                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon's long play stopped for good. The run `20261023-213300` (host-clone-1, the `latest`
lane) was written off as `same_spot` — the same map position for 300 ticks — on map **34**
(Route 23), position **(10, 96)**, milestone `hall_of_fame`, with 33 milestones done. The lock it
wrote stopped the lane, so the game lost every minute until the fix was deployed.

The game was fine and the runner pressed **no key at all**: the last three events of the run are

```json
{"kind": "strategy", "trigger": "resumed after a stop", "source": "fallback",
 "plan": "Follow the story: Take Route 22, Route 23 and Victory Road to Indigo Plateau and beat the Elite Four."}
{"kind": "lost", "map": 34, "next": 194}
{"kind": "stalled", "reason": "same_spot", "milestone": "hall_of_fame", "map": 34, "pos": [10, 96]}
```

A local replay of the canonical save reproduces it exactly: **737 ticks, every one of them
"no route"**, milestone `hall_of_fame`, map 34, pos (10, 96), no key pressed.

## Root cause

**The waypoints of the last mile were the wrong way round for a runner that comes through the
gate, so the guide asked for a map with no route to it.**

`milestones.py` walked the last mile as `… ROUTE_22, ROUTE22_GATE, VICTORY_ROAD_1F, ROUTE_23,
VICTORY_ROAD_2F, …` (the order BUG-0878 chose, on the assumption that Route 23's second warp,
(14, 31), leads to Victory Road 2F). The guide advances to the **next** waypoint from the map the
runner stands on (`runner.py:950-965`: `j = min(i + 1, len(maps) - 1); nxt = maps[j]`), so a runner
standing on Route 23 was asked for **Victory Road 2F (194)**.

Measured on the canonical save's own world graph (the live map, read through the runner's code):

* Route 23 (34) holds four warps: `(7,139)/(8,139) -> 193` (the gate), `(4,31) -> 108`
  (Victory Road 1F) and `(14,31) -> 194` (Victory Road 2F).
* The part model splits the map: the player lands in **part 4** (the gate and the west road) and the
  warp to 194 sits in **part 0** (the plaza and the north strip).
* So `world.route(34, 108, start_part=4)` is **known** (the warp at (4, 31), 81 steps away, and
  `astar` to (4, 31) is 81 steps long) while `world.route(34, 194, start_part=4)` is **None**.

`go_to_map` found no route, so it answered `"no route"` on every tick (`runner.py:1839-1853`,
which emits the `lost` event: `map=34, next=194`). The player never moved, and the stall detector
wrote `same_spot` after 300 ticks.

The assumption of BUG-0878 is therefore refuted by the map itself: the warp to Victory Road 2F is
not a way on for a runner that stands on Route 23.

## Fix

1. **`milestones.py`** — the last mile walks `… ROUTE22_GATE, ROUTE_23, VICTORY_ROAD_1F,
   VICTORY_ROAD_2F, …`. From the gate the runner now asks for Victory Road 1F, whose warp is
   reachable, instead of asking for Victory Road 2F, which is not.
2. **`runner.py`** — a waypoint that cannot be reached from where the runner stands no longer
   freezes it: the runner walks back to the waypoint it came from (`waypoint_unreachable` event)
   instead of answering "no route" for ever.

Guard tests: `test_the_hall_of_fame_waypoints_walk_route_23_to_victory_road_1f`,
`test_the_guide_asks_for_victory_road_1f_from_route_23_and_not_for_the_unreachable_2f`,
`test_a_waypoint_the_runner_cannot_reach_sends_it_back_instead_of_standing_still`.
181 pokemon tests pass.

## What is still missing (the last mile, measured on the live maps)

With the guide fixed the runner crosses Route 23 and enters Victory Road 1F — it moves again — but
the floor's own puzzle is not solved yet, and it is the last blocker before the Elite Four. What
was measured on the live floor (the canonical save of the earlier run `20261023-194559`, the
emulator, the runner's own grid):

* Victory Road 1F (108, 20 x 18 squares) holds three boulders: **(2, 10)**, **(5, 15)** and
  **(14, 2)**. The stairs up to Victory Road 2F are the warp **(1, 1) -> 194**.
* The only link from the player's pocket to the north part (where the stairs are) is the corridor
  `x = 2`, rows 9…13, and the boulder at **(2, 10)** stands in it. With the boulder in place
  `astar` to (2, 9) and to (1, 1) are both `None`.
* The game refuses to push that boulder north a second time: pushed north once it rests at (2, 9)
  and cannot go on (the square north of it, (2, 8), holds tile `0x12`, which is not passable), and
  the player is then walled in — pressing RIGHT, LEFT or UP from (2, 10) does nothing. This is the
  "exit only" barricade the Red/Blue walkthroughs describe ("if you were to try to push it north,
  it would get stuck and bar the path permanently").
* The boulder at **(5, 15)** can be pushed north once (it comes to rest at (5, 14), the player
  follows into its old square) and no further: the square north of it, (5, 13), holds tile
  `0x15`, and the game refuses the push. (5, 13) is drawn as a striped step in the game's own
  picture of the floor, next to the raised platform in the north-east — the switch or the stair of
  the floor, but pressing UP on it changes nothing, so what opens the way north is still to be
  measured.
* The floor's tiles explain why the runner's grid cannot walk the north part: the cave's tile
  pairs (`0x05` next to `0x20/0x21/0x2a/0x41`) are walls in the ROM's pair table, and the ROM's
  ledge table has only 8 entries, all for the outdoor tileset, so the cave's one-way jump tiles are
  not modelled at all.

**Next piece of work:** find what the boulder at (5, 15) is for (the switch at (5, 13)?) and model
the cave's jump tiles, so the stairs at (1, 1) can be reached and Victory Road 2F, 3F and Indigo
Plateau follow. Until then the runner walks the last mile's first leg (Route 23 -> Victory Road
1F) and comes back, instead of standing still.

## Files

- `shared/src/lib/game/pokemon/milestones.py` — the `hall_of_fame` waypoints.
- `shared/src/lib/game/pokemon/runner.py` — the guide's destination choice.
- `tests/shared/test_pokemon.py` — three guard tests.
