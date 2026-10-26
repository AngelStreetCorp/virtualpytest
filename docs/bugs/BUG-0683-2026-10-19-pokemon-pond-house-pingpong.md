# BUG-0683 — Pokémon long play ping-pongs between Fuchsia's pond and the Good Rod house

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0683 |
| Reported  | 2026-10-19 |
| Status    | Fixed |
| Severity  | High |
| Area      | shared / game / pokemon runner (TASK-33) |
| Fixed in  | build 90145 |
| Commit    | see `git log --grep BUG-0683` |

---

## Summary

Stall `20261019-142323` (host-clone-1, `same_spot` at Fuchsia (31, 22), milestone `seafoam`) was first a repeat of
BUG-0681, whose fix had not been committed. With BUG-0681 in, a replay of the save still did not leave Fuchsia: the runner
walked through the door at (31, 24) into the Good Rod house (map 164), turned round, came back out of the same door and did
this again for the whole run (550 ticks, `warp_stuck` at (31, 24) again and again).

## Root cause

(31, 22) is the pond behind the fishing guru's house, where BUG-0673 fished the Surf learner. That pocket's only way out is
the house's back door. In Fuchsia the route to Route 19 was right: the back door, then the house's front door (2, 7), then
Fuchsia's south edge. Inside the house, though, `Runner.milestone_step` (runner.py, the "off the route" branch) treated map
164 as a detour because it is not in `seafoam`'s area, and headed "back to Fuchsia" by the nearest door: the back door,
straight into the pond again.

## Fix

`milestones.py`: `GOOD_ROD_HOUSE` is in the `seafoam` area, so inside the house the guide leads on to Route 19 (the world
graph's route `164 → 7 by (2, 7) → south edge`). Guard test:
`test_seafoam_area_holds_the_good_rod_house_so_the_pond_is_left_by_its_front_door`.
