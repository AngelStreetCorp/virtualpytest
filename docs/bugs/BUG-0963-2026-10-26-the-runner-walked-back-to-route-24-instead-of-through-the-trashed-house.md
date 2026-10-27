# BUG-0963 — The runner walked back to Route 24 instead of through Cerulean's trashed house

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0963                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | shared (pokémon long-play runner)                            |
| Fixed in  | build 90256 |
| Commit    | branch `fix/pokemon-vermilion-wayon`                         |

---

## Symptom

The unattended Pokémon Blue lane (TASK-33) stalled on 2026-10-26: the run `20261026-204910`
(host-clone-1, the `second` lane) wrote `stall_second_20261026-204910.json` with the reason
`no_progress` — "no milestone, no new map and no new square for 5 min of game time" — on **map 35**
(Route 24) at square **(10, 35)**, milestone `vermilion`, 12 milestones done (`bill`), **no
deferral** (`deferred: []`).

The runner stood at Cerulean City's north exit and stepped across the border with Route 24, in
both directions, every half second, for the whole stall window:

```
walk_target  map 3   pos [20, 0]   target [20, -1]  branch route  edge north
walk_target  map 35  pos [10, 35]  target [10, 36]  branch route  edge south
walk_target  map 3   pos [20, 0]   target [20, -1]  branch route  edge north
walk_target  map 35  pos [10, 35]  target [10, 36]  branch route  edge south
... (29 times) ...
stalled      reason no_progress  milestone vermilion  map 35  pos [10, 35]
```

`battle_s: 0.0` — the runner never fought, never reached Vermilion, never changed square.

## Root cause

The `vermilion` milestone (`shared/src/lib/game/pokemon/milestones.py:162`) guides the runner
through `[BILLS_HOUSE, ROUTE25, ROUTE24, CERULEAN, ROUTE5, ROUTE6, VERMILION]` and lists the maps
of its stretch as its area: `(TRASHED_HOUSE, PATH_ROUTE5, UNDERGROUND_PATH, PATH_ROUTE6)`.

On Cerulean (the waypoint at index 3) the next waypoint is **Route 5** (map 16), and the world
graph knows **no route** to it: Cerulean's south exit (its `south` edge, the one that leads to
Route 5) lies in **parts 4 and 9** of the city, while the runner stands in **part 0** — measured
on the live save's world graph. The two door squares of the **trashed house**, `(27, 11)` and
`(27, 9)`, are the only way between the parts, and stepping on them warps the player into the
house (map 62, never visited).

The guide therefore took the BUG-0880 branch (`shared/src/lib/game/pokemon/runner.py:1027`): no
route to the next waypoint → walk back to the waypoint the runner came from → **Route 24**. On
Route 24 the guide asks for Cerulean again (it is the next waypoint of the list), and that route
*is* known, so the runner walked straight back. The two maps swapped the runner for ever.

The way on was in the milestone's area the whole time, one door away:
`World.explore(3, area)` → `[(62, ('warp', (27, 11)))]`, the door of the trashed house, in the
player's own part. It was never tried: the explore branch of `find_route`
(`shared/src/lib/game/pokemon/runner.py:2204`) only runs when the *goal map* has no route, and
the fallback had replaced the goal with Route 24, which has one.

## Fix

The area of a milestone is the list of the maps of its stretch — the way on when the guide's next
waypoint cannot be reached yet. It now wins over the walk back.

- `shared/src/lib/game/pokemon/runner.py:2214` — new `Runner.way_on_in_area(here, area, part)`:
  asks the world graph whether an unvisited map of the milestone's area is reachable from where the
  runner stands (`World.explore`).
- `shared/src/lib/game/pokemon/runner.py:1030` — the guide keeps the next waypoint (so `go_to_map`
  explores the area) instead of walking back to the waypoint the runner came from.

The walk back (BUG-0880, BUG-0891) still runs when the area holds nothing new — e.g. Victory Road
1F, where leaving the floor puts its boulders back and the floor can be solved.

## Verification

- Guard test `test_the_way_to_route_5_goes_through_the_trashed_house_and_not_back_to_route_24`
  (`tests/shared/test_pokemon.py`): it builds the world graph measured on the live save and fails
  without the fix (`AttributeError: 'Runner' object has no attribute 'way_on_in_area'`).
- `python3 -m pytest -q tests/shared/test_pokemon.py` → **220 passed**.
- **Verified on the emulator**: the local replay of the canonical `second` save (7 min,
  `test_scripts/game/local/pokemon_play_local.py`) walks the whole stretch of the milestone, with no
  ping-pong at all:

  ```
  explore map 3  toward 62     ← the trashed house, the way on
  walk_target map 62 pos [27, 11] target [28, 12]   ← inside the house
  walk_target map 3  pos [27, 9]  target [27, 36]   ← out of the other door, to the south exit
  explore map 16 toward 71     ← Route 5, the path under it
  explore map 71 toward 119    ← the underground path
  explore map 119 toward 74    ← the path under Route 6
  hop map 17 at [17, 13]       ← Route 6
  ```

  The old log of the same save shows the ping-pong that the fix replaces
  (`waypoint_unreachable map 3 wanted 16 back 35`, then `stalled no_progress`).
- The diagnosis of the stall is in
  `~/vpt-private/pokemon/stalls/stall_second_20261026-204910.diagnosis.md` (private, never
  committed).
