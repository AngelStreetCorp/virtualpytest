# BUG-0655 — Pokémon runner's walk target changes, and the cause, are not logged

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0655 |
| Reported  | 2026-10-19 |
| Status    | Fixed (pending deploy) |
| Severity  | Low |
| Area      | shared / game / pokemon runner (TASK-33) |
| Fixed in  | build 90145 |
| Commit    | TBD |

---

## Summary

Map 3 at (19, 12) ping-pongs between two walk targets: the explore route toward map 33, and the guard fallback
at (20, 2). The stall log shows the stall, but nothing records which target the runner chose on each tick or which
branch chose it, so the flip cannot be read from the log. This bug adds that diagnostic. No movement changes.

## Evidence

Stall report 20261019-030003 (TASK-33): the runner stays on map 3 around (19, 12) and alternates between the
explore route toward map 33 and the guard fallback at (20, 2). The existing `walk_stuck` event (BUG-0646) gives the
target of a stuck episode only, and `explore` (BUG-0640 / the area explorer) logs only when its destination changes,
so the per-tick choice is not visible.

## Root cause

Not yet diagnosed. `Runner.go_to_map` in `shared/src/lib/game/pokemon/runner.py` picks the walk target from three
branches (the route or explore route from `find_route`, the unvisited-door route, and the guard fallback when there is
no route), and nothing records which one chose it.

## Fix

Diagnostic only, no change to routing, movement or stuck logic.

- `Runner.note_walk_target(here, target, edge, branch)` is called where `go_to_map` picks the target: before the
  walk toward the next hop, and before the walk toward a guard that is not adjacent yet.
- It emits one `walk_target` event when the target (map, square, edge side) or the branch changes, and records the
  last one in `memo["last_walk_target"]` and `memo["last_walk_branch"]`. A target that stays the same logs nothing.
- Event fields: `map`, `pos`, `target` (list), `branch`, `edge` (side or null).
- Branch labels: `route` (the world route to the milestone's map), `explore` (an explore route, or the unvisited
  door route), `guard` (the walk toward a person in the way). Warp and edge hops are not labels: the hop type is
  not in the event; `edge` shows an edge hop.
- `find_route` now returns `(route, exploring)` so the label is known where the target is picked.

## Test

`test_walk_target_is_logged_only_when_the_target_or_its_branch_changes` in `tests/shared/test_pokemon.py`: a target
that flips every tick between two squares gives 4 events for 4 ticks; a constant target gives one event (its first
tick) and none after; a change of branch alone on the same square gives one more event.
`test_any_errand_in_giovannis_half_of_b4f_heads_for_the_elevator` stubs `find_route`, so its stub now returns the
pair.
