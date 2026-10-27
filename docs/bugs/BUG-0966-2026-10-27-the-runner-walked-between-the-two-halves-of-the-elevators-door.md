# BUG-0966 — The runner walked between the two halves of the elevator's door, in the Rocket Hideout

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0966                                                     |
| Reported  | 2026-10-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | shared (pokémon long-play runner)                            |
| Fixed in  | build 90256 |
| Commit    | branch `fix/pokemon-elevator-door`                           |

---

## Symptom

The unattended Pokémon Blue lane (TASK-33) stalled on 2026-10-27: the run `20261027-033452`
(host-clone-2, the **`second`** lane) wrote `stall_second_20261027-033452.json` with the reason
`no_progress` — "no milestone, no new map and no new square for 5 min of game time" — on **map
199** (the Rocket Hideout's B1F) at square **(24, 19)**, milestone `poke_flute`, 20 milestones
done (`silph_scope`), **no deferral** (`deferred: []`).

The player was **standing on** the elevator's door, and the runner walked from one half of it to
the other, for ever:

```
walk_target  map 199  pos [24, 19]  target [25, 19]  branch door  edge null
walk_target  map 199  pos [25, 19]  target [24, 19]  branch door  edge null
... (29 times) ...
stalled      reason no_progress  milestone poke_flute  map 199  pos [24, 19]
```

The local replay of the pulled save reproduces it exactly (1 585 `walk_target` events on the same
two squares), so the run is not a one-off.

## Root cause

### The player was in the elevator's corridor, and the corridor is a dead end

Measured on the live save (the world graph of `memory_second.json` and the tiles of the ROM):

| map | id | warps | the player's part |
|---|---|---|---|
| Rocket Hideout B1F | 199 | `(23,2)→200`, `(21,2)→135` (the Game Corner's hole), `(21,24)→200`, `(24,19)→203`, `(25,19)→203` | 2 |
| Rocket Hideout B2F | 200 | `(27,8)→199`, `(21,8)→201`, `(21,22)→199`, `(24,19)→203`, `(25,19)→203` | 15 |
| the elevator's cabin | 203 | `(2,1)→199/4`, `(3,1)→199/4` | 0 |
| the Game Corner | 135 | `(15,17)→6`, `(16,17)→6`, `(17,4)→199/1` | 0 |

The player's part of map 199 is **part 2**, and the only warp of that part is the elevator
(`(24,19)` and `(25,19)`). The corridor is 27 squares — the two door squares at the bottom of a
two-square room, the floor above them and a lane that ends at the east border of the map — so the
elevator really is the only way out of it.

The world graph agrees, in the only way it can:

```
route(199, part 2) → 135 : None                                  # the Game Corner: no way out
route(200, part 15) → 135 : [(199, ('warp', (27, 8))), (135, ('warp', (21, 2)))]
route(202, part 1)  → 135 : None                                  # Giovanni's half of B4F: the elevator only
```

The cabin is a **leaf** of the graph: its two warps lead back to the floor it came from
(`199/4` = `(25,19)`, the corridor), because the game patches the cabin's destination when a floor
is picked on the panel, and the graph cannot know that.

### The runner walked onto the twin of the door it stood on

`Runner.door_beside()` (`shared/src/lib/game/pokemon/runner.py`) returns the door square **one
step away** from the player — the BUG-0965 fallback for "the graph knows no way out". The player
was standing on `(24,19)`, itself a door square, so the only candidate was `(25,19)`: the other
half of the same two-tile door. **Moving between the two halves of a door never triggers a warp**
(the runner's own comment on `step_off_warp` says so: "not onto a twin warp square (a 2-wide
gangway): moving between the two never triggers either"), so the runner's steps moved the player
back and forth and the door never fired.

### The door fires on a press into the wall, and the runner never pressed

Measured on the emulator with the stalled save:

```
start:       map 199 pos (24, 19)
after UP:    map 199 pos (24, 18)     # stepping off the door onto the floor: nothing
after DOWN:  map 199 pos (24, 19)     # stepping back onto the door: nothing
press DOWN from (24, 19):  map 203 pos (2, 1)    # THE ELEVATOR FIRES
```

The Rocket elevator's door is drawn in a wall: the player stands on the door square and presses
into the wall next to it, the step is refused and the warp happens instead. The tiles around it
(from the ROM): `(24,20)` and `(25,20)` are walls (tile 51), `(23,19)` is a wall (tile 43),
`(24,18)` and `(25,18)` are floor (tile 1), `(24,19)` is tile 66 and `(25,19)` is tile 82 — the
two halves of the door.

### And the cabin would have sent it back to the corridor

`hideout_step()` rode `"1ER"` (B1F) whenever the milestone was not `silph_scope`. B1F's landing
part is the corridor — the dead end the player had just left. The elevator's menu (read from the
emulator) offers exactly three floors: `1ER`, `2EME`, `4EME`. The floor with a way out is
`2EME` (B2F): from B2F's landing part (15) the ledges and the stairs at `(27,8)` lead back to
B1F's part 0, and from there the hole `(21,2)` leads to the Game Corner and out to Celadon.

## Fix

1. **`Runner.fire_door()`** (`shared/src/lib/game/pokemon/runner.py`): when the world graph knows
   no way out **and the player stands on a door**, the door under his feet is fired — the press
   goes into the wall next to it, never into the twin and never into a walkable square. This is
   the only thing that makes the Rocket elevator fire. A door that never fires is marked unusable
   after four presses, as `step_off_warp` does.
2. **`Runner.lift_floor()`**: the floor the cabin takes is the one the world graph knows a way out
   of (`2EME` here), not the floor it came from. Giovanni's floor (`4EME`) is still the answer
   when the Silph Scope is the errand.

Guard tests (all three fail without the fix):

- `test_the_runner_fires_the_door_it_stands_on_when_the_graph_knows_no_way_out`
- `test_the_door_the_player_stands_on_is_fired_into_the_wall`
- `test_the_elevator_takes_the_floor_the_graph_knows_a_way_out_of`

`python3 -m pytest -q tests/shared/test_pokemon.py` → **224 passed**.

The diagnosis of the stall, with the measurements, is in
`~/vpt-private/pokemon/stalls/stall_second_20261027-033452.diagnosis.md`.
