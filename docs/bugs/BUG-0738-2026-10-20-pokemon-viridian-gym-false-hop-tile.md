# BUG-0738 — The Pokémon runner reads its own step as the game pushing it back, and seals itself in

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0738                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed (pending deploy)                                      |
| Severity  | High                                                        |
| Area      | game                                                        |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon Blue long-play runner (TASK-33) stalls on the `earth_badge` milestone with the reason `same_spot`:
the player stands on the same square for 300 ticks. In run `20261020-175235` (host-clone-1) he was at (9, 4) in
the Viridian gym (map 45) and the runner produced **945 "no path" ticks in a row**: the log's `walk_stuck` event
reports `part_size: 5`, the size of the pocket the player was left in.

Nothing about the game was wrong: the player could have walked out of the pocket, one square to the right.

## Root cause

A gym leader looks down at the square in front of him, so the runner walks onto that square and, when it already
stands there, steps aside and comes back (`challenge()` in `shared/src/lib/game/pokemon/runner.py`). The step
aside is a press the runner makes himself.

`note_hop()` (`runner.py:379`) concluded from the position delta alone that "the game pushed the player back the
way he came", and marked the square the player had come from as a one-way hop tile. It had no evidence that the
game had moved him: it compared the player's position with the direction of the last step **as the runner had
recorded it**, and only `walk()` recorded that direction (`runner.py:1940`). Every other press that moved the
player — the "step aside" above all — left the *previous* direction in place. The runner's own step was therefore
compared with a stale direction, matched the signature of a push-back, and the square was marked as a hop tile.

`grid()` (`runner.py:371`) closes every square marked as a hop tile. In the Viridian gym the square marked by
mistake, (10, 4), was the **only** walkable neighbour of the pocket the player was standing in. Closing it sealed
the player in: A* found no path on every tick and the stall detector stopped the run with `same_spot`.

The mark was wrong: (10, 4) is plain floor (tile 0x11, shared by 218 squares of the map), and pressing RIGHT by
hand at (9, 4) walks the player onto it and leaves him there. A real hop tile of that gym is (16, 10), tile 0x4c.

Two things made the wrong mark outlive the run: `CLEARED_ON_UNLOCK` (`shared/src/lib/game/pokemon/stall.py:189`)
did not drop the hop marks, so a cleared stall carried the sealed pocket into the next run, and nothing checked
the mark against the map's tiles.

## Fix

`shared/src/lib/game/pokemon/runner.py` and `shared/src/lib/game/pokemon/stall.py`:

1. `step()` records the direction of the move it caused (`self.step_dir = direction`). The press the runner made
   is the direction the game pushes the player back **from**, so a move the runner made himself can never be read
   as a push-back — while a real hop is still learned, the game pushing the player back opposite to the press.
2. `note_hop()` ignores a hop that changes map: the square the player came from is on the map he left.
3. `grid()` trusts a hop mark only when the square does not carry the plain floor of the map (the tile most of its
   walkable squares share). A one-way hop tile is never the plain floor, so a wrong mark can no longer close a
   square — the wrong mark already in a saved memory is inert without editing the save.
4. `CLEARED_ON_UNLOCK` drops the hop marks with the other way-marks of a cleared stall. The runner relearns the
   real ones by walking on them.

## Verification

* Guard test `tests/shared/test_pokemon.py::test_the_gym_leaders_step_aside_is_not_a_game_push_back_and_does_not_seal_the_square`:
  the "step aside" is not a hop, the real hop is still learned, a hop that changes map is not a hop, a hop mark on
  the plain floor does not close the square, and a cleared stall forgets the hop marks. It fails without the fix.
* `python3 -m pytest -q tests/shared/test_pokemon.py` → 161 passed.
* Local replay of the canonical save with the wrong hop mark still in the memory (240 s): the runner leaves the
  pocket and keeps playing instead of 945 "no path" ticks.
