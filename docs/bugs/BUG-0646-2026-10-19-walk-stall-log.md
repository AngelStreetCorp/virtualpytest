# BUG-0646 — Pokémon runner logs no walk decision when a walk stalls

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0646 |
| Reported  | 2026-10-19 |
| Status    | Fixed (pending deploy) |
| Severity  | Low |
| Area      | game / pokemon |
| Fixed in  | build 90145 |
| Commit    | TBD |

---

## Symptom

A Pokémon run stalled on map 3 at (30,20) and the stall report (20261019-000002) said only that the runner had not
moved. The event log had no record of which square the walk was aiming for, which edge it was crossing, or how much of
the map the player could reach, so the cause could not be read from the report.

## Root cause

Not a movement bug in this change. `Runner.walk()` counted failed steps in `self.stuck` but logged nothing about its
decision while it was stuck. Only the warp branch of `go_to_map` logged (`warp_stuck`).

## Fix

Diagnostic only, no change to movement, routes or the stuck logic. When `walk()` has failed to move four times in a row,
it logs one `walk_stuck` event:

`{"kind": "walk_stuck", "map": <map id>, "pos": [x, y], "target": [x, y], "edge": <edge or null>, "part_size": <squares reachable from pos>}`

It is logged once per stuck episode: the flag clears when a step moves. It is logged both when a step does not move the
player and when the route search finds no path.

## Test

- `tests/shared/test_pokemon.py::test_walk_logs_walk_stuck_once_per_stuck_episode` replays six stalled walks, one moving
  step, and six more stalled walks on a fake grid. It expects exactly two `walk_stuck` events with `part_size` 16 and
  the moves unchanged.
- `python3 -m pytest tests/shared/test_pokemon.py -q`: 123 passed.
