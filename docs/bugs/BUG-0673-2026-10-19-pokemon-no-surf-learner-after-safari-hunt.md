# BUG-0673 — Pokémon long play ends at 5 badges: no Surf learner after the Safari hunt

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0673 |
| Reported  | 2026-10-19 |
| Status    | Fixed |
| Severity  | High |
| Area      | shared / game / pokemon runner (TASK-33) |
| Fixed in  | build 90145 |
| Commit    | see `git log --grep BUG-0673` |

---

## Summary

Host run `20261019-113003` (deployment `pokemon-long-play-jev`, host-clone-1) stalled `deferred_end` at `earth_badge`,
Cerulean (6, 27), after one tick: every milestone read as done, `seafoam`, `volcano_badge` and `earth_badge` only through
`surf_deferred`. The save has 5 badges, HM03 in the bag, a party of Venusaur L51, Golbat L13 and Hitmonlee L30
(none can learn Surf; Hitmonlee knows Strength) and `strength_deferred` still set.

## Root cause

- The only Surf-learner sources were the Safari Zone hunt (`Runner.hunt_surf_learner`, run only while the current
  milestone is `surf`; it gave up after 2161 ticks with no Kangaskhan) and the TASK-105 gifts, which the long play
  never reaches. Once `surf` was done by its defer flag, nothing looked for a learner again.
- Nothing ever cleared a `*_deferred` flag, and `memo["done"]` is sticky: even a learner joining later would not have
  re-opened the skipped milestones (`strength_deferred` was already stale).

## Fix

- `milestones.py`: new milestone `surf_learner` right after `surf`, done when the party knows Surf; `GOOD_ROD` (0x4D),
  `GOOD_ROD_HOUSE` (0xA4, its doors are in the Fuchsia world graph) and `DEFERRED_BY` (the milestones each flag lets through).
- `runner.py`: `surf_rod_step` talks to the fishing guru for the Good Rod, then `fish()` walks to the nearest square
  next to water (on the current map, else Fuchsia), faces it and uses the rod (`hm.use_item`, the flute's menu trip made
  generic). A wild battle with a Surf learner the party lacks is a catch at any party size (`must_catch` in
  `battle.heuristic_choice`; the LLM chooser is not asked). `pending_hm` teaches HM03 as before.
- The trip to Fuchsia follows `ROAD_TO_FUCHSIA` (Cerulean, Route 9, Rock Tunnel, Lavender, Routes 12-15), the road
  the long play walked: on the first replay the world graph's shorter way through Saffron's north gate ping-ponged in
  Route 5's south pocket (the BUG-0639 pocket) for 10 minutes.
- `Runner.lift_defers()` (every overworld tick): a defer flag whose move the party knows is popped and its
  `DEFERRED_BY` milestones are removed from `done`, logged as `deferred_cleared`.
- `overworld.full_grid` lists `water` squares (lower-left tile 0x14 / 0x32 / 0x48 on the outdoor tileset, the tile the
  game's `IsNextTileShoreOrWater` checks).
- Test: `test_a_deferred_surf_is_played_by_the_good_rod_and_cleared_once_learned` in `tests/shared/test_pokemon.py`.

## Verified

Local replay of the host save for 14 min: the road to Fuchsia, the Good Rod, a Poliwag (PTITARD) on the 6th cast,
caught with 4 Poké Balls, Surf taught, `deferred_cleared` for both flags, milestone `seafoam` started.

## Still open

Field Surf: the runner has no Surf menu trip and no water squares in its walk grid, so it is `lost` toward Seafoam.
