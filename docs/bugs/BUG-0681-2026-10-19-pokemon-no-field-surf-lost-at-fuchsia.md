# BUG-0681 — Pokémon long play stalls at Fuchsia with Surf taught: no field Surf, no route to Seafoam

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0681 |
| Reported  | 2026-10-19 |
| Status    | Fixed |
| Severity  | High |
| Area      | shared / game / pokemon runner (TASK-33) |
| Fixed in  | build 90145 |
| Commit    | see `git log --grep BUG-0681` |

---

## Summary

Dispatcher run `20261019-135530` (host-clone-1) fished a Poliwag (POISSIRENE) at Fuchsia (31, 22), taught it Surf, cleared
`surf_deferred` and started `seafoam` (BUG-0673 working as meant). The next event was `lost` (map 7, next 162 = Seafoam B4F),
and the player stood on (31, 22) for 300 ticks: stall `same_spot`, save locked.

## Root cause

- `milestones.py` (`seafoam`): the guide was `[CINNABAR_ISLAND, SEAFOAM_1F … SEAFOAM_B4F]` and the area held only the
  islands, Cinnabar's mansion and gym. Seafoam is reached from Fuchsia by sea: Route 19 (0x1E) south, Route 20 (0x1F) west.
  Neither route was in the guide or the area, and Cinnabar is itself across the sea, so from Fuchsia there was no route,
  no map to explore, and `go_to_map` returned `no route` on every tick.
- `overworld.py` / `runner.py`: water was never walkable. The grid listed it (`Grid.water`, for the rod) but nothing ever
  used Surf in the field, so even a known Route 19 would have had no way past its shore.

## Fix

- `seafoam` guide `[FUCHSIA, ROUTE19, ROUTE20, SEAFOAM_1F … SEAFOAM_B4F]`, Routes 19 and 20 in its area.
- `Runner.grid`: with a Surf user in the party, the water squares are walkable; `overworld.astar` charges `SURF_COST` (12)
  for a land-to-water step, so a land way of similar length wins. `Grid.water` is now read by tile (the player's own
  square while surfing is water) and leaves out squares a swimmer stands on.
- `Runner.walk` → `surf_onto`: a land-to-water step faces the water and uses Surf from the party menu
  (`hm.use_surf`, sharing `hm.use_field_move` with Cut). Event `surf`; a square Surf fails on twice becomes a wall
  (`surf_failed`). Getting off is a plain step onto land.
- Guard test: `test_seafoam_guide_surfs_from_fuchsia_and_the_runner_gets_on_the_water`.

## Not covered

Water inside caves (the Seafoam floors, cavern tileset) is still not walkable: if the floors need Surf before they are
drained, that is the next stall.
