# BUG-0689 — Pokémon long play goes up and down one Seafoam ladder

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0689 |
| Reported  | 2026-10-19 |
| Status    | Fixed |
| Severity  | High |
| Area      | shared / game / pokemon runner (TASK-33) |
| Fixed in  | build 90145 |
| Commit    | see `git log --grep BUG-0689` |

---

## Summary

Stall `20261019-144223` (host-clone-2, `no_progress` at Seafoam B1F (map 159), milestone `seafoam`): the runner went down
the ladder at (4, 2) to B2F (160), came straight back up, and did this again for 5 minutes of game time.

## Root cause

B1F has three ladders down to B2F. On B1F the guide's next map was "B2F", any part, so the route took the nearest ladder,
(4, 2). That ladder lands in a corner of B2F whose only way out is back up. On B2F the route to B3F (161) was therefore
back up to B1F and down the ladder at (13, 7). On B1F again the destination was "B2F, any part", and the nearest ladder
won again (`Runner.milestone_step` in runner.py called `go_to_map(here, nxt, ...)` with no goal part).

## Fix

`runner.py`: when the guide's next map is not the milestone's last, the goal part of that map is the part with the warp
to the map after it (`World.part_with_warp_to`), when a route to it is known. On B1F the route takes the ladder (13, 7),
which lands in the part of B2F that has the ladder down to B3F. Replay of the stalled save: B1F, B2F, then B3F, a map
never reached before. Guard test: `test_seafoam_b1f_takes_the_ladder_into_the_part_of_b2f_that_leads_on`.
