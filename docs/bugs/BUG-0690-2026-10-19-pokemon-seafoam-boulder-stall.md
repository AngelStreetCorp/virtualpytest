# BUG-0690 — Pokémon long play stands still on Seafoam B3F

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0690 |
| Reported  | 2026-10-19 |
| Status    | Fixed |
| Severity  | High |
| Area      | shared / game / pokemon runner (TASK-33) |
| Fixed in  | build 90145 |
| Commit    | see `git log --grep BUG-0690` |

---

## Summary

Stall `20261019-150537` (host-clone-2, `same_spot`, milestone `seafoam`): right after BUG-0689 let the runner reach
Seafoam B3F (map 161), it stood on (12, 6) for 300 ticks. Events: `lost` toward B4F (162), then `walk_stuck` with
`pos` (12, 6) = `target` (12, 6).

## Root cause

On B3F `story_step` ran `strength_puzzle_step`. Its plan (`strength.PUZZLES[SEAFOAM_B3F]`) is a placeholder, not the
game's map: its first "boulder" is (12, 6), the square the player stood on. The step walks to the boulder while the
player is not on the square before it, so it asked for a walk to its own square, every tick. The milestone itself was
wrong too: in Generation I the Seafoam boulders only open Articuno's floor. Route 20 is surfed end to end to Cinnabar
Island, and the learned world graph already has that way (Route 20's west edge to map 8).

## Fix

`milestones.py`: the `seafoam` milestone is done on Cinnabar Island (Fuchsia, Route 19, Route 20, Cinnabar). It is
deferred by `surf_deferred` only, so `strength_deferred` no longer skips it. The Seafoam floors stay in `area`.
`runner.py`: no Seafoam puzzle step. A cached puzzle plan is used only on the floor it was made for (the stalled
save had cached the B3F plan, which Victory Road would otherwise have replayed). Guard test:
`test_seafoam_is_done_at_cinnabar_without_the_boulder_puzzle`.

## Follow-up: the saved guide pointer

The first run after the fix (`978c33a8`, host-clone-1) died on its first tick with `list index out of range`: the save
kept `guide_i = 6` from the old 8-map route, and the new route has 4 maps. `Runner.overworld_tick` now clamps the
pointer to the milestone's last map. Guard test: `test_a_saved_guide_pointer_past_a_shorter_route_is_clamped`.
