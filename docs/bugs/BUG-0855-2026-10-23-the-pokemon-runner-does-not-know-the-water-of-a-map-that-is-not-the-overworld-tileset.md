# BUG-0855 — The Pokémon runner does not know the water of a map that is not the overworld tileset

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0855                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                      |
| Severity  | High                                                        |
| Area      | game                                                        |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon Blue long-play runner (TASK-33) stalled `same_spot` on Route 23 (map 34) at (11, 105): "the same map
position for 300 ticks", milestone `hall_of_fame`. The run `20261020-234745` (host-clone-1) had all eight badges
and everything the story needs — Surf, Strength, the Secret Key — and had to walk the road of Route 23 from the
gate house up to Victory Road.

It walked the road (46 new squares, from (7, 136) to (11, 105)) and then stopped at the foot of the map's
**water**:

```
walk_target map 34 pos (7, 136) target (8, 119) branch guard
walk_target map 34 pos (8, 120) target (12, 105) branch guard
text_stuck ticks 60 pos (11, 105) map 34  (x4)
npc_walled who=guard map 34 square (12, 105) talks=3
lost map 34 next 108                       ← the runner wanted Victory Road 1F and had no way on
stalled same_spot map 34 pos (11, 105)
```

Every `walk_target` is `branch guard`: with **no route**, `go_to_map()` falls back on talking to the nearest
person, the three people on the road were talked to three times each and walled, and the runner stood still.
A local replay of the same save on the emulator reproduces it exactly — 415 ticks, every one of them
`"no route"`, the player never moves from (11, 105).

## Root cause

**The water was only modelled for the overworld tileset.** `shared/src/lib/game/pokemon/overworld.py:177`
(in `full_grid`):

```python
out.water = {sq for sq, t in tiles.items() if t in WATER_TILES and t not in ok_tiles and sq not in blocked} \
    if tileset == OVERWORLD_TILESET else set()
```

Route 23 uses **tileset 23**, so `out.water` was **empty** and the map's water was, to the runner, a wall.

That empty water set breaks the run in three places:

1. `Runner.grid()` (`runner.py:380`) — "Surf known, water is a way" — opens the water squares
   (`walk.update({sq: True for sq in getattr(walk, "water", ())})`). With no water set, nothing is opened.
2. The A* (`overworld.astar`) skips every square that is not walkable, so there is **no path over the water**.
3. `world.parts()` flood-fills the walkable squares to tell a map's parts apart, so the runner's world graph
   learned Route 23 as **nine parts**: the player's part `6` and the parts `4` and `0` of the two Victory Road
   warps — (4, 31) → map 108 and (14, 31) → map 194 — with no connection between them.

The map read out of the stalled save shows why: map 34 is 20 x 144 squares, and **y = 103 down to y = 72 is one
band of tile 0x14 — the water** — with a small island (tile 0x23) at (8, 90) and (9, 90)/(8, 91)/(9, 91). The
runner's part and the Victory Road warps are only joined through that water, so `go_to_map()` found **no route to
Victory Road 1F (108)** — the `lost` event of the stall report — and the run stood still.

The game knows the water by its **tile id alone** (0x14), not by the tileset it is drawn with, and it accepts the
surf: measured in the emulator on the stalled save, from (11, 104) with the tile in front at 0x14,
`START → POKéMON → POISSIRENE → SURF` gives **"POISSIRENE monte sur …"**. The milestone itself says so
(milestones.py:281, BUG-0662: "Route 23 is crossed by Surf").

## Fix

`shared/src/lib/game/pokemon/overworld.py`: the water set is computed for **every** tileset now — the game's
water tile (0x14) everywhere, the shore tiles (the rod's) on the overworld as before:

```python
water_ids = WATER_TILES if tileset == OVERWORLD_TILESET else (WATER_TILE,)
out.water = {sq for sq, t in tiles.items() if t in water_ids and t not in ok_tiles and sq not in blocked}
```

Nothing else had to change: with the water known, `Runner.grid()` opens it (the party member POISSIRENE knows
Surf), the A* finds the way over the band, `world.parts()` learns Route 23 as one part and `go_to_map()` gets a
route to Victory Road 1F. The runner surfs once from the shore (the menu trip `START → POKéMON → SURF`), walks
over the water — the game keeps him on the surfboard until he steps on land again — and surfs a second time from
the island.

## Verification

* Guard tests in `tests/shared/test_pokemon.py`
  (`test_the_water_of_a_map_that_is_not_the_overworld_tileset_is_known`,
  `test_the_surf_crossing_of_a_map_that_is_not_the_overworld_tileset_is_a_way`): both fail without the fix.
* `python3 -m pytest -q tests/shared/test_pokemon.py` → 166 passed.
* A local replay of the stalled save with the fix: the runner surfs over the band and walks into Victory Road 1F
  (map 108).
* No defer flag was involved: `deferred` was empty and no `*_deferred` flag was set — the game needs Victory Road
  and the Elite Four, and the runner simply had no way on.

## Still open (not this stall)

* The **sign at the bottom of Route 23** (run `20261020-233457`): the runner's `text_stuck` handler presses B
  twice after 60 text ticks and the sign's box opens again on the next tick — the sign wants another key, and a
  sign the runner has already read should not be read again.
* The **people on the road** of Route 23: they are talked to and walled rather than fought, and the guard
  fallback is what a run with no route falls back on.

Diagnosis: `~/vpt-private/pokemon/stalls/stall_latest_20261020-234745.diagnosis.md`.
