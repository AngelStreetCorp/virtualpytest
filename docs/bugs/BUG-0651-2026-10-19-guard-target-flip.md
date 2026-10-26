# BUG-0651 — Pokémon runner steps back and forth between two squares, aiming at two different guards

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0651 |
| Reported  | 2026-10-19 |
| Status    | Fixed (pending deploy) |
| Severity  | Medium |
| Area      | shared / game / pokemon runner (TASK-33) |
| Fixed in  | build 90145 |
| Commit    | TBD |

---

## Summary

When the Pokémon runner has no route out of its part of the map, `guard_in_reach` picks the nearest person it has not
talked to yet and walks to him. The choice was made again on every tick. A person's sprite is hidden once it is on
screen within 5 squares of the player, so the nearest candidate changed every tick and the runner oscillated between
two squares.

## Evidence

Local replay of a saved run, 1094 ticks, only two squares involved:

- tick 39: player at (21, 12). Guard sprite at (27, 12) is present, so the target is (27, 12).
- tick 40: player at (22, 12). The guard sprite is hidden (picture byte 0xFF, on screen), so the only candidate left
  is (20, 2) and the target becomes (20, 2).
- Each following tick flipped the same way: the runner stepped back to (21, 12) and then forward to (22, 12).

## Root cause

`guard_in_reach` (`shared/src/lib/game/pokemon/runner.py`) sorted the visible people in the part by distance on every
call and returned the nearest one. `overworld.sprite_list` deliberately drops a sprite whose image byte is 0xFF while
it is on screen within the 10 x 9 window, so visibility depends on the player's own position. Walking towards the
guard hid him, which removed him from the candidates, which sent the runner back.

The talk counter does not help here: it only counts talks made from an adjacent square, and the runner never got
adjacent.

## Fix

`guard_in_reach` keeps the square it chose in `memo["guard_target"]` as `[map, x, y]`. On the next tick it returns that
square while all of these hold:

- it is on the same map and still in the player's reachable part,
- it is not adjacent to the player (manhattan distance > 1),
- its talk count is still at or under `BLOCKER_TALKS_MAX`.

Otherwise the nearest candidate is chosen again and stored. When there is no candidate the stored square is cleared.
`overworld.sprite_list` is unchanged.

## Test

`test_the_guard_target_stays_put_when_his_sprite_is_hidden_once_the_player_is_close` in
`tests/shared/test_pokemon.py`: a fake part with (27, 12) and (20, 2); the guard is visible at (21, 12), hidden at
(22, 12), and the target must stay (27, 12). Next to him at (26, 12) the talk is counted and the target is chosen again.

Before the fix (runner.py as on `origin/main`) the test fails at the x = 22 assertion with target (20, 2). After the
fix it passes.

## Verification

Run `python3 -m pytest tests/shared/test_pokemon.py -q` (the file's full count is the check). A live run was not done
for this change; the replay above is the only evidence of the flip.
