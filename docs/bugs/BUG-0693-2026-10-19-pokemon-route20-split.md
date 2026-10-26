# BUG-0693 — Pokémon runner goes in and out of the Seafoam Islands: Route 20 is two seas

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0693                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon (TASK-33)                                     |
| Fixed in  | build 90145 |
| Commit    | see `git log -- shared/src/lib/game/pokemon/milestones.py`   |

---

## Symptom

Run `20261019-152852` (host-clone-1) stalled `no_progress` on milestone `seafoam`, Seafoam 1F (192) / Route 20 (31) at
(48, 5): for 5 min it walked out of the cave by (4, 17) to Route 20 (48, 6), straight back in by (48, 5), and out again
(`walk_target` 192 (4, 16) → (4, 17) `route`, then 31 (48, 6) → (48, 5) `explore`, ~40 times).

## Root cause

BUG-0690 made `seafoam` "surf Route 20 west to Cinnabar" (`milestones.py`, `Milestone("seafoam", …)`). With Surf the
Route 20 grid is two seas: the Fuchsia side (with the cave door (48, 5)) and the Cinnabar side (with the door (58, 9)) are
walled apart (x = 43, the row y = 12, x = 62); they meet only through the islands, whose B4F currents need the boulder
puzzle (placeholder plans in `strength.py`). The world graph had no way from part 2 (the player's) to the west edge, so on
Route 20 the guide explored back into the cave. Inside it, `World.route` found a false way out: Route 20 → Route 19 → back
onto Route 20's east edge, which touches two parts (one is a one-square water strip at y = 0 that runs across the whole
map), so `_land` gave part `None` and every Route 20 hop, the west edge included, looked open.

## Fix

The `seafoam` guide reaches Cinnabar the boulder-free way: Fuchsia, back along the road to Fuchsia (Routes 15–12,
Lavender, Rock Tunnel, Route 9, Cerulean), Routes 4 and 3, Pewter, Route 2 and Viridian Forest, Viridian, Route 1, Pallet
Town, then Surf down Route 21 (new `ROUTE21`) to Cinnabar. Route 19, Route 20 and the islands stay in `area`, so a save
standing there leads on. Guard test: `test_seafoam_reaches_cinnabar_by_pallet_and_route21_not_route20`.

## Verification

Replay of the stall's canonical save (`~/vpt-private/pokemon/stall152852/`, 240 s): Route 20 → Route 19 → Fuchsia →
Route 15 (and its gate) → 14 → 13 → 12, 454 ticks, no stall. Then the live run after `clear-stall` on the deployed hosts.
