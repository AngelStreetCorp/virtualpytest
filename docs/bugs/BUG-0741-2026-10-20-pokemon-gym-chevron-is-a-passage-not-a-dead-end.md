# BUG-0741 — The Pokémon runner closes the gym's chevrons for ever and cannot leave the gym

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0741                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed (pending deploy)                                      |
| Severity  | High                                                        |
| Area      | game                                                        |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon Blue long-play runner (TASK-33) won the Earth Badge and then stalled `same_spot` in the Viridian gym
(map 45) at (2, 2): "the same map position for 300 ticks", milestone `hall_of_fame`. The run `20261020-223419`
(host-clone-1) had just beaten Giovanni (`milestone_done: earth_badge`, 8 badges) — the first progress in days — and
then had to **leave** the gym for Route 22.

With no route to the exit, the runner fell back on talking to a guard and picked the **beaten leader**: his sprite
is still in the game, the memo's `walls` are what say he is gone, so the runner pressed A on him three times
(`blocker_talks: 45:2,1: 3`), walled him off and stood on (2, 2) for 300 ticks.

The memo of the stalled save shows what walled the gym in:

```
hops  45: [[13, 16], [13, 17], [18, 2], [19, 1]]     # the gym's chevron squares, closed for ever
walls 45: [[6, 7], [10, 3], [2, 1]]                  # the beaten trainers
```

## Root cause

Two defects, both in `shared/src/lib/game/pokemon/runner.py`.

**1. The chevron squares were closed as dead ends.** `note_hop()` (`runner.py:405`) learns a square as a one-way hop
tile when the game moves the player **exactly opposite the key the runner pressed** — the runner's model of "the
game pushed him back the way he came". A gym's chevron is not that: the game carries the player **one square in the
arrow's direction**, whichever key he presses (measured in the emulator on the Viridian gym's chevron at (5, 13):
from (4, 13) RIGHT puts the player **on** it and he stays; on it, RIGHT and UP are blocked but DOWN and LEFT carry
him to (6, 13)). The runner approached the four chevrons of the gym from the side they carry him to, so every carry
looked like a push-back, and each one was marked. `grid()` (`runner.py:387`) closes every marked square, so the way
out of the gym — over the chevron squares (13, 16), (13, 17), (18, 2) and (19, 1) — was cut, and `go_to_map()`
found no route at all. The mark never said **where** the carry lands, so the runner could not cross the tile the way
the game carries him.

**2. The fallback talked to a trainer who is gone.** `guard_in_reach()` (`runner.py:1843`) picks "the nearest person
standing in the player's part of the map" from `overworld.sprites()`. A beaten trainer's sprite is still in the
game; the memo's `walls` are what mark him as gone. Talking to him does nothing at all: the runner pressed A into
him three times, walled him off and then stood still.

A local replay of the same save with the hop marks dropped (what a cleared stall does) walks out of the gym —
45 → 1 (Viridian City) → 33 (Route 22): the marks, not the gym, were the blocker.

## Fix

`shared/src/lib/game/pokemon/runner.py`:

1. `note_hop()` — the mark now remembers **where the carry landed the player**: `[x, y, landing_x, landing_y]`.
   A mark without a landing (the old format, an old saved memory) keeps the old meaning.
2. `grid()` / `hop_jump()` (new) — a marked square with a landing is a **passage**, not a dead end: the grid jumps
   over it the way it jumps over the ledges. From the square before the tile, the key in the carry's direction moves
   the player onto the tile and the game carries him over to the landing square; from the tile itself, the same key
   carries him on. The tile itself stays closed (the runner must not stop on it), so the way out of the gym stays
   open and the runner does not walk onto the chevrons.
3. `guard_in_reach()` — the people the memo marks as walls (the beaten trainers) are skipped. They are gone;
   talking to one does nothing.

## Verification

* Guard test `tests/shared/test_pokemon.py::test_the_gym_chevron_is_a_passage_and_a_beaten_trainer_is_not_a_guard`:
  the mark of the stalled run opens the passage over the tile (the A* crosses it), a mark without a landing keeps the
  old behaviour, and the beaten leader is not picked as a guard.
* `python3 -m pytest -q tests/shared/test_pokemon.py` → 164 passed.
* No defer flag was involved: `deferred` was empty and no `*_deferred` flag was set — the game needs the Earth Badge
  and the runner simply could not leave the gym.

Diagnosis: `~/vpt-private/pokemon/stalls/stall_latest_20261020-223419.diagnosis.md`.
