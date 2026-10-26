# BUG-0878 — The run stood still on Victory Road 1F: a training it could not do, and a floor with no way out

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0878                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon's long play stopped for good. The run `20261023-175436` (host-clone-1, the `latest`
lane) was written off as `same_spot` — "the same map position for 300 ticks" — on map **108**
(Victory Road 1F), position **(2, 12)**, milestone `hall_of_fame`. The lock it wrote stopped the lane,
so the game lost every minute until the fix was deployed.

The game was alive and the runner was not stuck on a key: it simply **pressed no key at all**. A
local replay of the canonical save answers with one thing only:

```
tick 0..N: 'no grind area'   presses=[]   events=[]
```

and the run's own log holds two events: the strategy and the stall.

## Root cause

**A training that cannot even begin was never given up, and the floor the runner stood on has no way
out.**

### 1. The spin

The strategist answered the resume with `train_to_level: 70` (the leader, FLORIZARRE, was level 65),
so `overworld_tick()` asked for training on every tick
(`shared/src/lib/game/pokemon/runner.py:933-936`):

```python
want = strategy.memory(self.memo)["rules"].get("train_to_level")   # 70
top = max((p["level"] for p in self.party()), default=0)             # 65
if want and top < want and self.memo.get("stalled_target") != want:
    return self.grind(here, info, top, want)
```

`grind()` (`runner.py:2480`) only drops the target when the training has run **240 s without
experience** (`runner.py:2487-2494`, `GRIND_STALL_S = 240` at `runner.py:78`). A training that
cannot *start* — no way from this map to a grass area — never reaches that branch: `wander()`
(`runner.py:2497-2503`) answers `"no grind area"`, `grind()` hands the answer back unchanged, and the
tick ends with the player where it was.

The give-up could not have come in time anyway: `grind_s` grows by `min(5.0, seconds since the last
tick)` per tick (`runner.py:499-500`), while the stall detector gives up after **300 ticks**
(`shared/src/lib/game/pokemon/stall.py:37`, `SAME_SPOT_TICKS = 300`). With the fast ticks of today
(~0.33 s) 240 s of training needs ~730 ticks — the stall detector always won that race. The memo of
the stalled save says it: `grind_s = 798.6` s of training had already been spent, with the party at
91/454 HP and FLORIZARRE **and** KICKLEE fainted, so no wild battle was possible either.

### 2. The floor behind it

Measured on the live floor (the saved state and the emulator):

```
  0 ###########.##..####      W = warp      @ = the player
  1 #W..#######.###..###
  ...
 10 ##.##...###..#######      the boulder (picture 63) stands on (2, 10)
 11 ##..#...###..##...##
 12 #.@.#....#...#....##
```

* the stairs up to Victory Road 2F are the warp at **(1, 1)**;
* the boulder at **(2, 10)** and the cave's tile-pair walls `((5,8),(5,9)), ((6,8),(6,9)),
  ((7,8),(7,9))` seal the north-west part of the floor: with the boulder in place `overworld.astar`
  returns **None** for both the push's start square (2, 9) and the stairs (1, 1);
* the player stands at (2, 12), **south** of the boulder, so the push cannot be set up from here.

The way on is **Route 23's second warp, `(14, 31) -> Victory Road 2F (194)`** — the game's own warp
table holds it (map 34's warps: `[(7,139)->193, (8,139)->193, (4,31)->108, (14,31)->194]`). But the
milestone's waypoints (`shared/src/lib/game/pokemon/milestones.py:278-280`) said
`[... ROUTE_23] + [VICTORY_ROAD_1F, VICTORY_ROAD_2F, VICTORY_ROAD_3F] + [...]`, so **on Route 23 the
next waypoint was Victory Road 1F**: the runner walked to Route 23's own stair (4, 31), stepped on
it and came back down into the dead end — the log shows it (`walk_target` on map 34 with the target
(4, 31), then `explore toward 108`).

## Fix

* `shared/src/lib/game/pokemon/runner.py` — `grind()`: a training that **cannot begin** (no way to a
  grass area) is given up like a stalled one. The target is dropped (`stalled_target`), the
  `train_stalled` event says `reason="no grind area"`, the strategist is told, and **the story goes
  on** — instead of the runner pressing no key for 300 ticks.
* `shared/src/lib/game/pokemon/milestones.py` — the `hall_of_fame` waypoints now walk **Victory Road
  1F → Route 23 → Victory Road 2F** (1F before Route 23, 2F after it): the runner leaves the
  dead-end floor through the stair it came in by and takes Route 23's second warp to Victory Road 2F.

No defer flag is involved: the game's memory has no `*_deferred` flag here (`deferred: []`), and the
story needs the whole game — the Elite Four and the Hall of Fame are still ahead.

## Verification

* Guard tests in `tests/shared/test_pokemon.py`
  (`test_a_training_that_cannot_even_start_is_given_up_instead_of_asked_for_again`,
  `test_the_hall_of_fame_waypoints_walk_victory_road_1f_back_to_route_23`) — the whole file passes
  (178 tests).
* A local replay of the stalled save: before the fix every tick answered `no grind area` with no key
  pressed; after it the first tick gives the training up (`train_stalled`, `reason="no grind area"`)
  and the runner **walks**.
* Deployed to host-clone-1 (the lane that stalled) — the host runs `main-2026.10.23-89819` with the fix
  in place; host-clone-2 was queued behind another agent's run lease and takes the same build as soon
  as that lease is free. The lane's lock is cleared and the next run starts with `--clear_stall yes`.
* On the host, the lane now **plays**: the run walks, fights, heals and changes map
  (108 → 1 → 13 → 33 → 193 → 34 — 528 squares in 300 s) where before it stood on one square for 300
  ticks without pressing a key.

Diagnosis: `~/vpt-private/pokemon/stalls/stall_latest_20261023-175436.diagnosis.md`.

## What is still open

The run plays again, but **the last mile of the story does not advance yet**: the runner walks
Victory Road 1F → Route 23 → back to Victory Road 1F and the run ends as `no_progress`. Two
measurements say why, and both are the same missing piece — **the floor's jump tiles are not in the
grid**:

* Victory Road 1F's north-west part (the stairs at (1, 1)) is cut off in the runner's grid by the
  floor's tile-pair walls, so the push's start square (2, 9) cannot be walked to (BUG-0874's release
  note said it already: "the grid does not model the floor's jump tiles yet").
* The boulder cannot be pushed out of the way either: measured in the emulator, one push north from
  (2, 11) moves the boulder (2, 10) → (2, 9) and the player to (2, 10) — where the player is
  **trapped** (`overworld.astar` with the sprites in place returns `None` for (1, 1) from both
  (2, 10) and (2, 11)). (2, 8) is not a hole: the boulder stays at (2, 9).
* Route 23's north strip is cut off the same way, which is why the world graph's part model hides its
  second warp (14, 31) → Victory Road 2F from the part the player stands in.

So the way on stays Route 23's second warp, and the next piece of TASK-33 is the jump tiles in
`overworld.full_grid` (it models the outdoor ledges only, `LedgeTiles` at 0x1A6D4 in the French ROM).
The party is also hurt (91/454 HP, two fainted) and the Elite Four has to be entered healed: the
runner still needs a way to a Pokémon Center from the Victory Road side of the world, and the
Strength user (KICKLEE) is fainted.
