# BUG-0639 — Pokémon runner ping-ponged between Saffron and Route 5 for 30 minutes

- **Reported**: 2026-10-18
- **Visible to**: Pokémon Blue runs (TASK-33) in the Seafoam milestone, after Saffron.

## Summary

The runner stood at Saffron's north edge, (18, 0) and (18, 1), for 30 minutes of game time with no milestone progress. Each tick it walked north over the edge onto Route 5 (map 16), landed in the south half of that map, and then walked back south to Saffron. The planner picked a different route from each map, so the two never settled.

## Evidence

- Stall report `stall_latest_20261018-211502` (run `20261018-211502`): reason `no_progress`, milestone `seafoam`, map 10 (Saffron), pos (18, 1), 30 min game time, `stall_counters.spot_ticks = 1`.
- Earlier stall at (18, 0) in the same milestone (event at 1792350132).
- Memo `entry`: `{from: 10, side: north, exit: [18, 0], map: 16, landing: [8, 35]}`. The landing is in part 8 of map 16. A 10-square shift on the north edge puts (8, 35) back at (18, 1) on Saffron, which matches the stall position.
- The memo log has no `lost`, `explore` or `dead_end` event during the milestone. So no no-route branch fired.
- Offline replay on the saved world graph: from Saffron (part 1) the route to the nearest Pokémon Center (Cerulean, map 64, which `prepare` needs before Seafoam) starts north over Route 5 (3 hops). From the Route 5 landing (part 8) the same route starts south back to Saffron (8 hops, round by Route 6). The Seafoam route itself has no known path (Cinnabar, map 8, is unvisited), so the Seafoam branch never ran.

## Root cause

Two rules in `shared/src/lib/game/pokemon/`:

1. `world.py` `_land`: an edge hop lands in a part of the next map only when the strip on the far side touches exactly one part. Route 5's south strip touches parts 6, 7 and 8, so the landing part is `None`. A `None` part is treated as open: every hop out of it is allowed, including the one back north. The pocket (part 8) has no way north except through the gate house (map 70), which the runner has never visited.
2. `runner.py` `go_to_map`: the dead-end handling (`retreat`, which marks the entry's exits as bad) only runs when there is no route at all (`no_route_ticks >= NO_ROUTE_TICKS`). Here there was always a route, so the pocket was never marked. The planner on Route 5 chose the long way back to Saffron, and on Saffron chose the north edge again.

`overworld_tick` reaches `go_to_map` through `prepare()`: Seafoam has `prepare=True`, and `seafoam` is not in `memo.prepared`, so the Cerulean Center errand runs before the Seafoam story step on every tick.

## Fix

- `runner.py` `go_to_map`: a bad edge exit (`memo.bad_exits`) no longer counts as a first hop of a route (`first_hop_ok` removes its squares from the edge).
- `runner.py` `go_to_map`: when the runner is standing in the part it entered by an edge (the landing square is in its part) and the route's first hop goes straight back over that edge, call `retreat()`. `retreat()` marks the exits of the previous map that lead into this part and walks back. The condition excludes `dest == from`, so `retreat()`'s own call cannot recurse.

No change to `world.py`, to the milestones, or to the saved memo. Existing marks in `memo.bad_exits` apply on the next tick.

## Test

`tests/shared/test_pokemon.py::test_a_dead_end_entered_by_an_edge_is_left_and_its_exits_are_not_taken_again` builds a synthetic world: Saffron (10), Route 5 (16) with a south pocket (part 8), Route 6 (17) with a warp back into Route 5's north half, and Cerulean (3).

- Before the fix: from the pocket, the route walks south (correct), but `bad_exits` is not marked, so the assertion fails. Confirmed once against the unfixed code.
- After the fix: the pocket's north exits of Saffron (x 10-29) are marked, and from Saffron the route to Cerulean goes south round by Route 6.

`python3 -m pytest tests/shared/test_pokemon.py -q`: 117 passed (116 before).

## Not verified

- The real tile geometry was not saved, so the pocket is inferred from the world graph and the stall positions, not checked on the tiles. A live check on the host would confirm that every Saffron north exit into Route 5's south half lands in the dead-end pocket.
- The gate house (map 70) was never visited. The fix avoids the ping-pong by taking the known Underground route. A later change could explore the gate house first.
