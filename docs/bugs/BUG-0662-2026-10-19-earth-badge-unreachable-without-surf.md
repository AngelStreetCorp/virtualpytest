# BUG-0662 — Pokémon runner stalls at earth_badge when Surf is deferred

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0662 |
| Reported  | 2026-10-19 |
| Status    | Fixed |
| Severity  | High |
| Area      | shared / game / pokemon runner (TASK-33) |
| Fixed in  | build 90145 |
| Commit    | see `git log --grep BUG-0662` |

---

## Summary

The long-play run stalled 10 times in a row at `earth_badge` (2026-10-18 21:00 UTC to run `20261019-041502`), on the
Cerulean Trashed House (map 62) and in Cerulean City (map 3), each time on a different square. Clearing the lock only
bought another stall.

## Root cause

The save has `surf_deferred` (no party member can learn Surf) and 5 badges. Route 23 is crossed by Surf and its gates
check all 8 badges, so no route reaches Victory Road. `seafoam` and `volcano_badge` are deferred when Surf is (BUG-0643),
but `earth_badge` (`shared/src/lib/game/pokemon/milestones.py`) was only done in the Hall of Fame. The runner was `lost`,
explored Cerulean doors and talked to guards until a stall detector stopped it. The guard and text fixes
(BUG-0651 to BUG-0657) only moved the square it stalled on.

## Fix

- `earth_badge` is done when `surf_deferred` is set, like `volcano_badge`. Every milestone is then done or deferred:
  the runner ends the run with `story done` and saves.
- `game_pokemon.py`: a run that ends with `story done` does not count toward the `no_progress_runs` stall.
- Test: `test_earth_badge_is_deferred_without_surf` in `tests/shared/test_pokemon.py`.

## Still open

The story only goes on once a Surf learner joins (Silph Co. 7F Lapras gift, a Good Rod Poliwag or Goldeen, a Nidoking)
and `surf_deferred` is cleared, and the Marsh badge has no milestone yet (TASK-33).
