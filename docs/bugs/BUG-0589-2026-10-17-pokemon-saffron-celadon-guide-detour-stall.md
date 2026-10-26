# BUG-0589 — Saffron milestone looped back to MART_ROOF when drink was already in the bag

## Summary
TASK-33 saffron reached `same_spot` stalls at Celadon City `(39, 20)` even when the drink
was already in the bag (stamps `20261015-091504`, `20261015-121504`, `20261015-124503`).
The pillar fix (`47650221e fix(pokemon): saffron_step checks ALL saffron-area edges`) caught the
case where the runner's part of Celadon did *not* include a saffron-edge square; it did not
catch the case where it did — the runner's GUIDE pointer was still parked on the first CELADON
entry of the milestone path, so `overworld_tick` asked `go_to_map` to route it to MART_ROOF
(a redundant drink-buy trip), and at `(39, 20)` every UP press hit the south-gate warp at
`(39, 19)` (already in `bad_warps`) — 600 ticks of "walk / no progress" later, stall.

## Repro on host-clone-1 (2026-10-15 12:45)
- state at `var/lib/vpt-private/pokemon/state_latest.json`: Celadon, map 6, pos (39, 20)
- memo at `memory_latest.json`:
  - `drink_bought: True`, `bag_seen: [60]` (Fresh Water = 0x3C)
  - `guide_i: 9`
  - `done: [..., "strength"]`
  - `bad_warps: [[50, 4, 0], [47, 4, 0], [36, 45, 3], [6, 39, 19]]` ← `(6, 39, 19)` is the south gate
- the saffron milestone `maps = [WARDENS_HOUSE, FUCHSIA, ROUTE15, ..., ROUTE7, CELADON,
  MART_ROOF, CELADON, ROUTE7, SAFFRON]` (two CELADON entries with MART_ROOF between them)
- `saffron_step` saw `drink_bought == True` and the runner's part already included the saffron
  edge squares `(49, 10)` / `(49, 11)`, so it returned `None`
- `overworld_tick` then read `maps[9] == CELADON == here` → `nxt = maps[10] == MART_ROOF`
- `go_to_map(here=6, dest=126, ...)` routed the runner back to MART_ROOF — the planner walks
  `UP` toward the MART_ROOF door
- every `UP` press at `(39, 20)` is the south-gate warp `(39, 19)`, already in `bad_warps`, so
  `step(UP)` returns `False`, `walk()` still returns `"walk"`, `stuck` increments
- `runner.run(seconds)` wrote 329 walks in 300 s, then 600 with no position change → `same_spot`
  stall, fresh `saffron_step` lock every replay

## Local reproduction (2026-10-17)
- copy of host save in `~/vpt-private/pokemon/host_repro/state.json` + `memory.json`
- Xvfb on `:97`, GameServer on `127.0.0.1:8767`, `pokemon_play_local.py --seconds 60` then 300
- each: `{walk: 329 / 329}` ticks, pos `(39, 20)`, milestone `saffron`, `stalled: null`
- probing `overworld_tick` with the call-site traced showed `go_to_map(here=6, dest=126)` and
  `step(UP)` was the only key that `walk()` ever tried; pos unchanged, `stuck` grew from 0 to 4
  over four ticks
- probing the saffron step directly: `saffron_edges == [(49, 10), (49, 11)]`,
  `part contains both` → saffron_step returns `None` (correct per the previous fix); the route
  that was wrong was `overworld_tick`'s GUIDE-pointer choice of `MART_ROOF` as the next map

## Fix
- `runner.saffron_step` now skips the MART_ROOF detour: when the runner already has the drink
  in the bag (the bag check runs each tick, but we capture the pre-check state), and it is on
  Celadon, and the GUIDE pointer is on the first CELADON entry of the milestone path, bump
  GUIDE to the second CELADON entry — so `overworld_tick` picks `nxt = ROUTE7` (the next step
  on the second half of the path). One event `guide_skip, from_=9, to=11, milestone=saffron,
  map=CELADON` is recorded so the stall detector and review scripts notice the path.
- `runner._saffron_skip_drink_detour(here)` is the helper; safe on test-only Runner builds
  (`object.__new__`, no `world` / `current()` resolution possible) because every access is
  guarded.
- 4 new regression tests in `tests/shared/test_pokemon.py`: GUIDE-on-first-CELADON bumps,
  runner-not-on-CELADON does not, drink-not-bought does not, idempotent on a second-CELADON
  GUIDE. 107/107 in `tests/shared/test_pokemon.py`.

## Why the previous saffron fix didn't catch this
The original pillar fix (`47650221e`) was scoped to "runner's part of the current map lacks
any saffron-edge square, so `first_hop_ok` rejects the edge and the A* falls back to a warp
hop." In that case saffron_step walks the runner to a saffron-edge square. When the runner's
part *already* includes a saffron-edge (the `(39, 20)` host save has `part` including
`(49, 10)` and `(49, 11)` — they share a single connected component across the whole walkable
Celadon layout), saffron_step returns `None` and the overworld_tick continues. The test added
with that fix (`test_saffron_step_returns_none_when_runner_already_in_part_with_saffron_edge`)
asserted the same `None` return — both ends of the fix landed in the silent zone where the
runner LOOKS like it's moving (counts.walk increments) but isn't (pos unchanged).
