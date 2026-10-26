# BUG-0635 — Pokemon runner retries the Celadon mart door forever (warp retry is capped)

Numbering: BUG-0634 is the latest on main; BUG-0635 was unused when this was written.

## Summary

BUG-0634 fixed the sole-door stall by dropping the `bad_warps` mark on Celadon's mart door (39, 19) and
retrying it. On the live game that door is not a door (UP from (39, 20) hits a wall), so the retry walked
into it, six steps later marked it again, and the next `go_to_map` retried it again. The loop ran 98 UP presses
at (39, 20) before the same-spot detector fired. The retry was not capped.

## Evidence

- Live probe, 2026-10-18: UP from (39, 20) on map 6 hits a wall. The door at (33, 19) to map 137 works.
- The saved world (`world['6']['warps']`) still lists `(39, 19, 136, 0)`: the ROM warp table has it, but the
  square does not trigger.
- BUG-0634 host run: 98 UP presses at (39, 20) after the retry, then the same-spot stall.

## Root cause

`runner.py` `go_to_map`, warp branch: the BUG-0634 retry drops the mark whenever the only usable door is marked,
with no limit. A door that fails again is marked again, and the next call drops the mark again. Nothing
remembered that the door had already been retried, so the cycle never ended.

Removing the warp from the `World` was not an option: `World.learn` rewrites `maps[here]` from the game's warp
table on every tick the runner stands on that map (`runner.py` `observe`, `world.py` `learn`), so the removal
would be undone on the next tick. `parts["warp"]` is indexed by warp position, so deleting an entry would also
misalign it.

## Fix

- `runner.py` `go_to_map`, warp branch (retry, ~line 1328): the retry runs at most once per door. It appends
  `[map, x, y]` to `memo["warp_retried"]` (event `warp_retry`, as before).
- `runner.py` `go_to_map`, `first_hop_ok` (~line 1302): a door that is in `bad_warps` **and** in
  `warp_retried` is dead for the rest of the run (it lives in the memo, like `bad_warps`). No route may start
  with it. `find_route` then picks another route, explores, or returns `no route`, and the runner never returns
  a walk to that door again.
- `runner.py` `go_to_map`, cap branch (~line 1343): when a door stuck six times is marked again after its retry,
  the event is `warp_dropped` (the first failure stays `warp_unusable`). The cap is visible in the log.
- `stall.py` `build_report`: `warp_retried` is included in the stall report `key_memo`, so a stall shows whether
  the retry was used.

No change to `World`, the saved world or the saffron milestone logic.

## Test

`tests/shared/test_pokemon.py::test_warp_retried_once_then_dead_is_not_walked_again`: Celadon with the mart door
(39, 19) as its only warp, `bad_warps=[[6, 39, 19]]`, runner at (39, 20). First `go_to_map` with `stuck=6`
walks to the door (the retry). Second `go_to_map` with `stuck=6` must return `no route` and must not walk to
the door again.

- Before the fix (`origin/main` runner.py): fails on the second assertion (walks = `[(39, 19), (39, 19)]`,
  return `walk`).
- After the fix: passes.

## Not verified

- No live emulator run. The fix makes Celadon's roof unreachable through that door after two failures. If the
  door works sometimes (BUG-0634's open question), the runner now stalls on `no route` instead of retrying. The
  next step, if it stalls there, is a live check of the single UP press from (39, 20) and a corrected world
  entry for the wall warp, not a change to the runner.
