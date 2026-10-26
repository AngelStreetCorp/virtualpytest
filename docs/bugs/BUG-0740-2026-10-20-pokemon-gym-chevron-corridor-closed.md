# BUG-0740 — The Pokémon runner closes the gym's chevron corridor and walks in circles for ever

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0740                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed (pending deploy)                                      |
| Severity  | High                                                        |
| Area      | game                                                        |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon Blue long-play runner (TASK-33) stalls on the `earth_badge` milestone with the reason `no_progress`:
"no milestone, no new map and no new square for 5 min of game time". In run `20261020-213314` (host-clone-1) the
player stood in the Viridian gym (map 45) at (6, 9) and the run went nowhere.

The player was **not** stuck on a square: the run's own counters show `spot_ticks: 1` and 90 squares visited. It was
walking — the same two squares, back and forth. A local replay of the stalled save in the emulator logged **542
ticks of "walk"** and no new square at all.

The game was fine: the gym's leader (picture 23) stands at (2, 1) and the way to him runs east along row 13,
through the gym's chevron square (5, 13) — 52 steps, the A* path of the game's own tiles.

## Root cause

`note_hop()` (`shared/src/lib/game/pokemon/runner.py:399`) marks a square as a one-way hop tile when the game moves
the player **exactly opposite the key the runner pressed**: the runner's model of "the game pushed him back the way
he came". The direction it compares with is `self.step_dir`, and `step()` (`runner.py:282`) only recorded that
direction when the press **did** move the player.

A gym's chevron is not a push-back tile. Measured in the emulator on the Viridian gym's chevron at (5, 13):

* from (4, 13), RIGHT puts the player **on** (5, 13) — he stays there;
* on (5, 13), RIGHT and UP are **blocked**, but DOWN and LEFT carry him to (6, 13): the chevron throws the player
  to its landing square whichever key he presses, and the key the runner planned is the one it blocks.

So the key the runner pressed did not move him: `step()` returned False and left the direction of an **earlier**
step in memory. The carry that followed was compared with that stale direction, matched the signature of a
push-back, and the square was closed as a one-way hop tile. The run's log shows it:

```
153.2 hop map 45 at (5, 13) to (6, 13)     the runner pressed LEFT, the game carried him EAST
166.2 hop map 45 at (4, 14) to (5, 14)     the runner pressed LEFT, the game carried him EAST
```

`grid()` (`runner.py:370`) closes every square marked as a hop tile. With the gym's chevrons (5, 13) and (4, 14)
closed, the A* found **no path at all** to the leader or to nine of the gym's eleven people: the player's part of
the map was the pocket around (6, 9), with the two trainers at (2, 7) and (6, 7) left in it. `walk()` then fell
back on `overworld.toward()` — the path to the square **closest** to the unreachable goal — and the runner walked
between two squares for ever: 542 ticks of "walk", no new square, and the stall detector stopped the run with
`no_progress`.

A real push-back is still a push-back: the key that **moved** the player onto the tile is remembered (BUG-0738), so
the game pushing him back the way he came is still learned (the BUG-0718 test is unchanged).

## Fix

`shared/src/lib/game/pokemon/runner.py`:

1. `step()` (`runner.py:282`) — a key that does **not** move the player clears `self.step_dir`. The game may still
   act on that key a moment later (the chevron's carry), and the direction of an older step says nothing about the
   move the game is about to make. A carry is never read as a push-back, so the gym's corridors are never closed.
2. `walk()` (`runner.py:1966`) — when the planned key does not move the player, the runner tries another key. The
   chevrons block the key the A* planned (RIGHT) and carry the player to their landing square on any other key
   (DOWN carries him east to (6, 13)), so with the planned key alone the runner stood on the chevron for ever (the
   `same_spot` stall of run 20261020-175235).

## Verification

* Guard tests `tests/shared/test_pokemon.py::test_a_key_that_does_not_move_the_player_leaves_no_direction_behind`
  and `::test_the_runner_tries_another_key_when_the_planned_one_is_blocked_by_a_hop_tile`: a blocked key leaves no
  direction behind and the carry that follows is not marked as a hop tile; the runner tries another key when the
  planned one is blocked and is not stuck on the chevron. Both fail without the fix.
* `python3 -m pytest -q tests/shared/test_pokemon.py` → 163 passed.
* Local replay of the canonical save (the private folder, 220 s): with the fix the runner leaves the pocket and
  keeps playing; without it the same replay is 542 ticks of "walk" between two squares.
