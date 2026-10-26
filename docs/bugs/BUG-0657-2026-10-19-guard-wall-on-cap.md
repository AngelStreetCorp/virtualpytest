# BUG-0657 — Pokémon runner keeps talking to a guard past the cap and never walls him

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0657 |
| Reported  | 2026-10-19 |
| Status    | Fixed (pending deploy) |
| Severity  | Medium |
| Area      | shared / game / pokemon runner (TASK-33) |
| Fixed in  | build 90145 |
| Commit    | TBD |

---

## Summary

On map 3 the Pokémon runner stalls next to guards it has already talked to. A guard in the only way out is talked to
(the locked room opens once he is beaten), but the guard path never made his square a wall, and it talked to him one
time more than the route path does. The two paths also kept separate talk counts, so one NPC got a fresh count on
each path. Once the guards were capped they still blocked the grid, so the runner had no route and fell back to
"lost".

## Evidence

Review: `~/vpt-private/pokemon/live0660/guard_review.md` (read-only review of origin/main 754ae44ae, runner.py and
overworld.py).

- Stall `030003`: map 3, ping-pong between (30,8) and (20,2). This is BUG-0656's case, already fixed on main. Its run
  file has no `walk_target` events, so it cannot confirm that fix.
- Stall `034503`: map 3, `text_stuck` 14 times at (6,27) for 300 ticks, then `lost` on map 3. The memo holds 30 map 3
  guards in `guard_talks` at the cap of 4, and `walls["3"]` has no entry for them. They still blocked the grid, so
  there was no route.

## Root cause

Two rules disagreed about when a person becomes a wall.

1. **Guard path never walls.** `guard_in_reach` released a guard once his count passed the cap and never wrote his
   square to `memo["walls"]`. The route path (`unblock`) did wall at its 3rd talk.
2. **Cap is 4 talks on the guard path, 3 on the route path.** The guard check was `count <= BLOCKER_TALKS_MAX`, with
   the count bumped before the talk, so counts 0, 1, 2 and 3 each made a talk: four talks. The route path walled at 3.
3. **Two counters for one NPC.** The guard path used `memo["guard_talks"]` and the route path used
   `memo["blocker_talks"]`, both keyed `map:x,y`. A guard released from one counter started again at 0 on the other
   path, so he could take up to 4 + 3 talks, and was walled only on the second path.

## Fix

`shared/src/lib/game/pokemon/runner.py`:

- `wall_on_cap(kind, square, here)` (new): when the square's count in `blocker_talks` has reached
  `BLOCKER_TALKS_MAX`, it adds the square to `memo["walls"]` for the map (the same structure the route path already
  used) and emits one `npc_walled` event with `who`, `map`, `square` and `talks`. Returns True when capped.
- `guard_talk_left(here, q)` (new, used by `guard_in_reach`): the guard is talked to while his count is below
  `BLOCKER_TALKS_MAX` (the `<=` is now `<`, so 3 talks, not 4). A talk made from next to him bumps the count, and the
  3rd one calls `wall_on_cap`. At the cap it calls `wall_on_cap` and releases him.
- `unblock` (route path): uses the same `blocker_talks` counter and calls `wall_on_cap` for the 3rd talk. A square
  already at the cap re-plans without a talk.
- Counter kept: `blocker_talks`. `guard_talks` is gone (the route path already walled on it and the wall helper reads
  it). Runs that stalled with an old `guard_talks` memo start those guards at 0 in `blocker_talks`.
- `report.py`: the `blocker_wall` label is now `npc_walled`.

Not changed: the text branch (`text_stuck`), the busy branch, the BUG-0651 and BUG-0656 target keeping.

## Test

`test_a_guard_walls_on_his_third_talk_and_the_route_path_walls_the_same_npc_on_its_third_talk` in
`tests/shared/test_pokemon.py`:

- Guard path: three `guard_in_reach` talks on one guard; the square is in `walls` and `npc_walled` fires; the fourth
  call returns None (no fourth talk).
- Route path: after two guard talks, the next `unblock` talks once and walls him; the following `unblock` re-plans
  without a talk.

Before (origin/main `runner.py`): the test fails (the guard path never walls). After: passes.
Existing tests updated for the shared counter and the `npc_walled` event. Pokémon test file: 129 pass.
