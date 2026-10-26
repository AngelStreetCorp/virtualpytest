# BUG-0656 — Pokémon runner ping-pongs between two guards once it stands next to the first

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0656 |
| Reported  | 2026-10-19 |
| Status    | Fixed (pending deploy) |
| Severity  | Medium |
| Area      | shared / game / pokemon runner (TASK-33) |
| Fixed in  | build 90145 |
| Commit    | TBD |

---

## Summary

When the Pokémon runner has no route out of its part of the map, `guard_in_reach` keeps its chosen guard (BUG-0651).
That target was released as soon as the runner stood next to the guard. A guard's sprite is hidden once the player is
close, so from the next square the only visible candidate was the other guard. The runner walked to him, and from
there back to the first. Neither guard was ever talked to, so neither talk count reached the cap and the loop went on.

## Evidence

Live run 2026-10-19 01:00 UTC, build `main-2026.10.19-88891`, `walk_target` events on map 3, branch `guard`, one
event about every 45 s:

- player (20, 3), target (30, 8)
- player (30, 9), target (20, 2)
- back and forth

Two guards are involved, at (30, 8) and (20, 2).

## Root cause

`guard_in_reach` (`shared/src/lib/game/pokemon/runner.py`) kept the memo target only while `abs(dx) + abs(dy) > 1`.
Once the player was adjacent, the kept target was dropped. The search then listed only the visible sprites, and the
adjacent guard's sprite was hidden, so the other guard was chosen. `talk_at` was never called for the adjacent guard,
so `guard_talks` never went up for him.

## Fix

In `guard_in_reach`, the kept target stays while its talk count is at or below `BLOCKER_TALKS_MAX`, adjacent or not.
When the target is adjacent, each call counts one talk, because the caller then runs `talk_at`, which presses A. The
target is released when it leaves the reachable part or reaches the cap, as before. Nothing else changed.

## Test

`test_an_adjacent_guard_stays_the_target_while_his_talks_are_below_the_cap` in `tests/shared/test_pokemon.py`. The
player stands next to guard A at (27, 12). A's sprite is then hidden and only B at (20, 2) is listed. The next
`guard_in_reach` call must still return A, and A's talk count must be 2.

- Before the fix (origin/main `runner.py`): returns (20, 2), test fails.
- After the fix: returns (27, 12), test passes.

The existing BUG-0651 test still passes: its talk count at (26, 12) stays 1.
