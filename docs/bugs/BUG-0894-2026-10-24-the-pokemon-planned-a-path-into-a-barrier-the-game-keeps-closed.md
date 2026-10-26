# BUG-0894 — The Pokémon planned a path into a barrier the game keeps closed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0894                                                     |
| Reported  | 2026-10-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | games                                                        |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The `latest` lane of TASK-33 stopped on **Victory Road 1F** (map 108) and wrote the lock that
stops the dispatcher from playing at all. The run `20261024-134917` played 662 s and produced
**46 events, every one of them a battle**:

```
{"kind": "battle_choice", "kind_battle": "wild", "enemy_level": 41, "choice": "move4", "choice_name": "COUPE", "by": "MiniMax-M3.1-Flash-Preview", ...}
{"kind": "battle_end", "outcome": "won", "battle": "wild", "turns": 1, ...}
...
{"kind": "stalled", "reason": "no_progress", "milestone": "hall_of_fame", "map": 108, "pos": [5, 9]}
```

22 wild battles (ONIX 36/42, GRAVALANCH 41, MACHOC 24, NOSFERALTO 41, RACAILLOU 26, MACHOPEUR 42),
**no `walk_target`, no `boulder_push`, no event that is not a battle**. The player never left the
grass of the floor: the stall detector wrote `no_progress` after 300 s without a new square
(`progress_s` 300.4, `battle_s` 0.0, `spot` 108:(5, 9)).

## Root cause

**The grid opened a barrier the game keeps closed, and the runner planned its path through it.**

`Runner.grid()` (shared/src/lib/game/pokemon/runner.py) built the floor's grid from the ROM's
tile-pair collisions. The barrier on the rocky ridge of Victory Road 1F is one of them:

```
wall pairs: [((5, 8), (5, 9)), ((6, 8), (6, 9)), ((7, 8), (7, 9)), ...]
```

BUG-0892 removed those three pairs as soon as the runner's **own chain counter** said the boulder
of the pressure switch was on the switch tile (`seafoam_pushes_done` > `strength.switch_step`).
The game does not open that barrier. Measured on the live save, with the emulator booted locally
from the canonical save:

* the boulder the chain pushes onto **(17, 13)** falls into the hole that tile is — right after
  the push the boulder is **gone from the sprite list** (the live boulders are only (2, 10),
  (7, 17) and (14, 2));
* the map's **block table is byte for byte the one of the ROM** (every row of the 10 x 9 block
  table searched in the ROM and compared), so the game changed nothing on the floor;
* the game's own collision keeps (5, 8) and (5, 9) apart — **pressing UP at (5, 9) does not move
  the player** (three presses, the player stays at (5, 9)).

With the barrier removed from the grid, the A\* to the stand square (2, 9) of the corridor push
started with the step UP into that wall. The game refused the step, the runner's fallback stepped
somewhere else and asked again, and the player ping-ponged in the grass of the floor, one wild
battle per step — the exact shape of the stall. The player's part of the floor is 71 squares with
the barrier closed and 176 with it open, and the stand square (2, 9) of the corridor push is among
the 176: the runner was sent to a square the game will never let it stand on.

## Fix

* `Runner.grid()` does not open a barrier any more. The grid follows the game's own collision
  data: when the game opens a barrier, the tiles of the floor change and the wall pairs go with
  them.
* The pressure switch's plan and its tile are unchanged — the chain still pushes the boulder to
  (17, 13).

With the grid honest, the reachability of the stand square (2, 9) is asked of the grid itself
(BUG-0879), the push that cannot be set up gives the floor up (`push_unreachable`) and the guide
takes over: the runner leaves the floor and plays the last mile instead of pacing in the grass.

## Verification

* `python3 -m pytest -q tests/shared/test_pokemon.py` → **199 passed** (the guard
  `test_the_runner_never_opens_a_barrier_the_game_has_not_opened` replaces the guard of BUG-0892,
  which asserted the opposite).
* A local replay of the stalled save with the fix: the chain runs, the corridor push is given up
  and the runner leaves the floor; see the handover of TASK-33 for the runs on the hosts.
