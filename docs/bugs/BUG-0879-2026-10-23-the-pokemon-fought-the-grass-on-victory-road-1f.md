# BUG-0879 — The Pokémon fought the grass on Victory Road 1F for ever: a push that cannot be set up was asked for again

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0879                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon's long play stopped for good. The run `20261023-194719` (host-clone-1, the `latest`
lane) was written off as `no_progress` — "no milestone, no new map and no new square for 5 min of
game time" — on map **108** (Victory Road 1F), position **(2, 11)**, milestone `hall_of_fame`. The
lock it wrote stopped the lane, so the game lost every minute until the fix was deployed. The same
stall came back 40 minutes later (`stall_latest_20261023-203059.json`, map 108, pos (2, 12),
`cells: 2`): same signature, so it is the stall and not a one-off.

The runner was **not** stuck on a key and the game was not frozen: it fought **42 wild battles**
(ONIX, MACHOC, NOSFERAPTI, RACAILLOU) with our HP constant at 171/225, and it never once left the
**two squares** of grass it stood on.

```json
{"kind": "battle_choice", "kind_battle": "wild", "enemy_level": 39, "choice": "move2", "choice_name": "TRANCH'HERBE"}
{"kind": "battle_end", "outcome": "won", "battle": "wild", "turns": 1}
{"kind": "battle_choice", "kind_battle": "wild", "enemy_level": 39, "choice": "run", "choice_name": "FUITE", "by": "heuristic"}
{"kind": "battle_end", "outcome": "fled", "battle": "wild", "turns": 1}
{"kind": "stalled", "reason": "no_progress", "milestone": "hall_of_fame", "map": 108, "pos": [2, 11]}
```

A local replay of the canonical save (`test_scripts/game/local/pokemon_play_local.py`) reproduces it
exactly: 349 steps, 462 battle ticks, and only **two** squares of map 108 ever visited — `108:2:12`
and `108:2:11` — with 13 `blocked_by` events ("at [2, 10] target [2, 9]") and 19 `npc_walled`
events ("map 108 square [2, 10] talks 3").

## Root cause

**`walk()` never says "no path" for a square it cannot reach, so the give-up that BUG-0877 added
for Victory Road 1F's boulder never ran.**

### 1. The floor

The `hall_of_fame` milestone sends every Victory Road floor to the Strength puzzle before the guide
gets a say (`shared/src/lib/game/pokemon/runner.py:998-999`):

```python
if ms.id == "hall_of_fame" and here in strength.VICTORY_ROAD:
    return self.strength_puzzle_step(here, info)
```

The plan of that floor is `((2, 10), "DOWN", 2)` (`shared/src/lib/game/pokemon/strength.py:110-125`),
so the push starts from **`stand = (2, 9)`**, the square north of the boulder at (2, 10). Measured
on the stalled save (the ROM, the saved state and the emulator):

```
map 108, player (2, 12), grid with the sprites (the boulders) blocking:
  astar (2, 12) -> (2, 9) : None        <- the push start is in another part of the floor
  astar (2, 12) -> (1, 1) : None        <- the stairs to Victory Road 2F are unreachable too
  astar (2, 12) -> (8, 17): 13 steps    <- the way back to Route 23 is open
  toward (2, 9)          : ['UP']       <- the greedy fallback points into the boulder
  live boulders          : (5, 15), (14, 2), (2, 10)
```

(2, 9) is only reachable through the one-wide corridor the boulder seals, and the detour round the
other boulder at (5, 15) is closed as well. The way on is Route 23's warp (14, 31) to Victory Road
2F (194) — the way BUG-0878's waypoints describe — but the runner never gets to use them.

### 2. The spin

`strength_puzzle_step()` asks for the push's start square on every tick
(`shared/src/lib/game/pokemon/runner.py:1268`) and gives the floor up only when the walk answers
`"no path"` (`runner.py:1269-1282`, the BUG-0877 behaviour). But the walk does not answer that:

1. `runner.py:2079` — `path = overworld.astar(walk, (px, py), target)` returns `None` for (2, 9).
2. `runner.py:2081` — the runner asks `unblock()` instead. The boulder is a sprite, so it is taken
   for a person standing in the way: the runner walks up to it and presses A, the game answers that
   the boulder will not budge (`blocked_by`, `npc_walled`), and after three talks the boulder is
   written into `memo["walls"]["108"]` — the stalled save carries exactly that.
3. `runner.py:2158` — with the talks used up, `unblock()` re-plans with
   `overworld.astar(...) or overworld.toward(...)`. `overworld.toward`
   (`shared/src/lib/game/pokemon/overworld.py:302`) returns the square closest to the goal,
   **ignoring the walls**: `['UP']`, straight into the boulder.
4. `runner.py:2103` — the press is blocked (the boulder does not move) and the BUG-0740 fallback
   tries another key: DOWN. The player is back at (2, 12). Next tick, the same.
5. `runner.py:1269` — `walked` is `"talk"`/`"walk"`, never `"no path"`, so the give-up branch is
   never taken. `strength_puzzle_step()` answers every tick, `story_step()` never returns `None`,
   and the guide — which knows the way on (`route 108 -> 34`, the warp at (8, 17), 13 steps) — never
   runs.

The player ping-pongs between (2, 11) and (2, 12), the grass of Victory Road 1F, a wild battle per
step: no new square, no new map, no milestone — `no_progress` after 300 s of game time
(`stall_counters.progress_s: 300.18`).

## Fix

* `shared/src/lib/game/pokemon/runner.py` — `strength_puzzle_step()`: the reachability of the square
  the push starts from is now asked of **the grid itself** (`overworld.astar(self.grid(), …)`), not of
  the walk. When the push cannot be set up, the floor is given up (`push_unreachable`) and the
  `hall_of_fame` guide takes over: the runner walks the 13 steps back to the warp at (8, 17) onto
  Route 23, exactly the way BUG-0878's waypoints describe.

No defer flag is involved: the game's memory has no `*_deferred` flag here (`deferred: []`), and the
story needs the whole game — the Elite Four and the Hall of Fame are still ahead.

## Verification

* Guard test in `tests/shared/test_pokemon.py`
  (`test_a_push_whose_start_square_is_out_of_reach_is_given_up_even_when_the_walk_does_not_say_no_path`)
  — the whole file passes (179 tests).
* A local replay of the canonical save (420 s): `push_unreachable` fires once, the runner **leaves
  Victory Road 1F**, surfs Route 23 and ends on map 34 at (10, 96) after 955 ticks with **no stall**
  (before the fix: 42 wild battles, two squares, `no_progress`).
* Deployed to host-clone-1 and host-clone-2 (build `main-2026.10.23-89829`); the lane's lock was
  cleared and the next run started with `--clear_stall yes`.
* On the host (run `20261023-212125`, host-clone-1): the events leave map 108 (10 events) for map 34
  (45 events) — the runner walks (8, 17) -> (4, 31) -> (4, 35) -> (4, 36), **surfs at (8, 72)** with
  POISSIRENE and goes on to (8, 85) -> (11, 96): 530 s of play and a new map, where before it fought
  the same grass on one square for 300 s. The run then ends as `same_spot` on map 34 at (10, 96) —
  the last mile, below.

## What is still open

The run plays again and **leaves Victory Road 1F**, but the last mile of the story does not advance
yet, and the way on is not what BUG-0878 assumed. Measured on the live maps (map 34 = Route 23,
20 x 144, tileset 23, with the runner's own grid — the party knows Surf, so the water is a way):

* Route 23's road is a switchback: the **west road** (x = 0..7) holds the gate warps (7, 139)/(8, 139)
  -> 193 and the warp (4, 31) -> 108 (Victory Road 1F) and ends at the top at the VR 1F door; the
  **east strip** (x = 14..19, y = 32..37) holds the warp (14, 31) -> 194 (Victory Road 2F) and is a
  dead end except for its north end, which reaches the plaza (y = 20..23) and the north edge
  (y = 0, x = 9..10 -> map 9).
* The part model therefore splits the map: the player lands in part **4** (the gate and the west road)
  and the warp (14, 31) sits in part **0** (the plaza and the north strip), so `route 34 -> 194` from
  part 4 is **None** — the runner answers "no route" and stands still on Route 23.
* The real way on is therefore **Route 23 -> Victory Road 1F -> the stairs at (1, 1) -> Victory Road
  2F**, and the `hall_of_fame` waypoints have the order backwards for a player coming from the gate:
  they say `VICTORY_ROAD_1F -> ROUTE_23 -> VICTORY_ROAD_2F`, so on Route 23 the runner asks for
  Victory Road 2F (no route) instead of Victory Road 1F (the warp at (4, 31), reachable). They have
  to become `ROUTE_23 -> VICTORY_ROAD_1F -> VICTORY_ROAD_2F -> VICTORY_ROAD_3F`.
* The stairs at (1, 1) are in part **0** of map 108, cut off from the player's pocket by the
  **tile-pair wall between (4, 8) and (5, 8)** (and the vertical ones at x = 5..7 between rows 8 and
  9). Those walls come from the ROM's tile-pair table for the cave tileset 0x11 (the pairs
  (0x20,0x05), (0x41,0x05), (0x2A,0x05), (0x05,0x21)). The ROM's ledge table (`LedgeTiles` at
  0x1A6D4 in the French ROM) has only **8 entries, all for the outdoor tileset**, so the cave's jump
  tiles are not in it and `full_grid` models jumps for the outdoor tileset only.

The next piece of TASK-33 is that grid: measure the step at (4, 8)/(5, 8) in the emulator (a false
positive tile-pair wall?) and the cave's jump tiles, then fix the waypoint order. The measurements are
in `docs/tasks/TASK-33-handover.md`.
