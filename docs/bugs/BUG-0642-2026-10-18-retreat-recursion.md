# BUG-0642 — `retreat()` recursed without end when a dead-end pocket had nothing new to mark

## Summary
Scheduled Pokémon runs after 20:06 UTC ended with `Unexpected error: maximum recursion depth exceeded` on the host, right after navigation. The navigation itself succeeded; the recursion was in the runner.

## Evidence
- Host journal (host-clone-1, 2026-10-18, local +02:00): `Unexpected error: maximum recursion depth exceeded` at 22:16 local, after `Found path with 1 steps` and `open_browser` succeeded.
- `shared/src/lib/game/pokemon/runner.py` `retreat()`: when every exit of the entered part was already in `bad_exits`, `fresh` was empty, and a route back to the entry map existed, `retreat()` called `go_to_map(here, from)`. `go_to_map` calls `retreat()` again in the same situation, so the two calls loop.

## Root cause
The walk-back branch added with BUG-0639 (`3c1e8a047`) returns `go_to_map` from `retreat()` even when no exit was marked this time.

## Fix
`retreat()` returns `None` when there is nothing new to mark. The walk-back runs only after at least one new exit is marked, so each call either marks an exit or stops.

## Test
`tests/shared/test_pokemon.py`: the existing suite passes (119). The recursion needs the live map to reproduce, so this has no dedicated test; the host run is the check.
