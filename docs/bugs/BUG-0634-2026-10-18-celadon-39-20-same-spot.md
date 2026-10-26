# BUG-0634 — Pokemon saffron runner stands at Celadon (39, 20) for 600 ticks after the drink leaves the bag

Numbering: BUG-0633 is the latest on main; BUG-0634 was unused when this was written.

## Summary

Host run `20261018-193002` (host-clone-1, build `main-2026.10.18-88729`) ended on `milestone=saffron` with
25 milestones done, stalled `same_spot` on map 6 (Celadon) at `(39, 20)` after 659 s. The run logged no
`guide_skip`, no walk and no map change. Only `strategy` and two `hm_failed` (Strength) events came before
the stall. The saved memo still says `drink_bought=true` and `guide_i=9`, but the bag held no drink.

## Evidence

Read-only from `host-clone-1`, copied to `~/vpt-private/pokemon/bug0634/` (mode 600, not committed):
`stall_latest_20261018-193002.json` and `memory_latest.json`.

- `last_events` of the stall: `strategy` (resumed), `hm_failed` Strength tries 2 and 3, `stalled` same_spot at
  `(6, [39, 20])`. No `guide_skip`. `stall_counters.spot_ticks = 600`.
- `memo.guide_i = 9` (first CELADON of the saffron route). If a drink were in the bag on Celadon, the
  `saffron_step` branch always calls `_saffron_skip_drink_detour` (bump 9 → 11, one `guide_skip` event per
  observe). None was logged in this run, so the branch did not see a drink.
- `memo.bag_seen` (written by `note_items` at the start of every `saffron_step` call) has 16 item ids and no
  drink (`0x3C`–`0x3E`). HM03 (198) and HM04 (199) are present.
- `memo.hm_tries = {Surf: 3, Strength: 3}` = `CUT_TRIES`, so `hm.pending_hm` returns nothing and the HM step
  does not run any more.
- `memo.bad_warps` contains `[6, 39, 19]`, the Celadon Mart door.
- Offline replay (saved world, open grid, runner at (39, 20), `bad_warps` as saved):
  `go_to_map(6, MART_ROOF)` returns `walk` toward `(39, 19)`. The only route to the roof goes through that door
  (`world.route(6, 0x7E)` → `[(136, warp (39, 19)), …]`).

## Root cause

Two decisions that together hold the runner at (39, 20):

1. **The stale drink flag (`runner.py` `saffron_step`, the `drink_bought` gate).** The drink is not in the
   bag, so the `if any(d in bag …)` branch is skipped and `saffron_step` returns None. The MART_ROOF buy
   at the end of `saffron_step` is gated on `not drink_bought`, which stays True. Nothing ever buys a second
   drink, and the runner is sent to the roof regardless.
2. **The sole bad door (`runner.py` `go_to_map`, the warp choice).** The route to MART_ROOF starts with the mart
   door `(39, 19)`, which is already in `bad_warps`. The `usable` list excludes it, so `cands` is empty, and the
   `how` left in place is still the bad warp. The escalation that would mark a door after six failed steps
   (and abandon it) lives inside `if cands:`, so it never runs. The runner walks into `(39, 19)` on every tick
   (UP from `(39, 20)`) and the same-spot detector fires after 600 ticks.

The HM step is not the cause: `teach_hm` only runs while `pending_hm` returns an HM with tries left, and the
Strength tries were exhausted (3 of 3) before the stall. The GUIDE index is correct for the plan (the roof is
the next guide map once the drink is gone); it is the flag and the door that stop the step.

## Fix

- `saffron_step`: on Celadon with no drink in the bag and `drink_bought` True, clear `drink_bought` (event
  `drink_missing`). The MART_ROOF branch then buys again.
- `go_to_map`: when the only usable door to the next map is itself in `bad_warps`, drop that mark (event
  `warp_retry`) and recompute `usable`. The door is tried again; six failed steps mark it again. The route no
  longer walks into a marked door as if it were free and forever.

Only the saffron milestone reaches the first change (it is the only one that buys a drink). The second change
applies to every milestone that goes through `go_to_map`, but only when the only door of a route is marked. No
other milestone was changed.

## Test

`tests/shared/test_pokemon.py::test_saffron_without_drink_rebuys_through_the_mart_door_not_the_marked_one`
builds Celadon (`warp (39, 19) → 0x88`) and the 5F map (`warp → MART_ROOF`) in a fake world, with an empty bag,
`drink_bought=True` and `bad_warps=[[6, 39, 19]]`. It asserts that `saffron_step` clears the flag, that
`go_to_map(CELADON, MART_ROOF)` walks to `(39, 19)`, and that the door is no longer marked.

- Before the fix (`origin/main` runner.py): fails at the first assertion (`drink_bought` is still True).
- After the fix: passes. `tests/shared/test_pokemon.py -k without_drink_rebuys` → 1 passed.
- Full file: 114 passed, 1 failed. The failure is `test_jev_choose_logs_with_refs_and_returns_decision_id`
  (`jev_choose() missing 1 required positional argument: 'ai_usage'`), which fails identically on `origin/main`
  and is not related to this change.

## Not verified

- No live emulator run. I could not establish from the saved files why the bag lost the drink. The gate guard
  at ROUTE7_GATE (`talk_to_nearest`) is one possibility (the gate is in the learned world, `76`), but the
  evidence does not show it. If the guard took it, the runner still has to pass the gate.
- Whether an UP press from (39, 20) enters the mart at all. Earlier runs bought the drink through this door, so
  the door works in some state. The retry only helps if the door works sometimes. If it never fires from
  (39, 20), this fix will not clear the stall, and the next step is a live check on the emulator of that single
  press.
- The retry cycles every six failed steps; it logs a `warp_unusable` event each cycle. This is bounded but noisy.
