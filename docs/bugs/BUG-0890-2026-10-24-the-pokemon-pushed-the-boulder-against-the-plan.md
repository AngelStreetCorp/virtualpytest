# BUG-0890 — The Pokémon pushed the boulder against the plan and then shoved it for ever

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0890                                                     |
| Reported  | 2026-10-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | games                                                        |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The `latest` lane of TASK-33 stopped twice in a row on the same floor, **Victory Road 1F** (map 108), and
both stalls wrote the lock that stops the dispatcher from starting any run at all.

* The run `20261024-093928` was written off as `no_progress` after 23 minutes of play and **37 boulder
  pushes**: the corridor boulder of the floor was pushed **north**, against the plan of the floor.
* The run `20261024-102539` — the first run **after BUG-0889 was deployed** — was written off the same
  way 13 minutes in, with the same floor and the same boulder:

```
{"kind": "boulder_push", "map": 108, "boulder": [2, 9], "to": [], "direction": "UP", "steps": 1, "moved": false}
```

  40+ times, every ~8 s, interleaved with wild battles the runner flees. `moved: false` is the game
  saying "the boulder won't budge".

The save was left with the corridor boulder wedged at **(2, 9)**, a square from which the game refuses
to move it at all.

## Root cause

Three faults in the same loop, all in `shared/src/lib/game/pokemon/runner.py`:

1. **The generic push pushes against the plan** (`push_boulder`). The floor's plan wants the corridor
   boulder of Victory Road 1F pushed **south**, out of the one-wide passage to the stairs (1, 1) — but
   the generic "push the boulder out of the way" took the direction of the path and shoved it **north**,
   into the alcove (2, 9), where the game refuses to move it any more. The floor could never be
   finished.
2. **A refused push is tried again for ever** (`push_boulder`). The refusal of the game was never
   remembered: the same impossible push was repeated on every tick, and the run ended with
   `no_progress` — no milestone, no new map, no new square for 5 minutes of game time.
3. **The chain of the floor is read from the memo, not from the floor** (`strength_puzzle_step`). The
   game puts the boulders of a floor back where they were when the player leaves it and comes back, so
   the chain has to start over; the memo's counter (`seafoam_pushes_done`) never says so, and a chain
   that was given up stayed "done" for ever.

Two smaller faults fed the loop: `astar` lets a **blocked goal** be entered (its docstring says so),
so the wall (2, 8) — north of the wedged boulder — was accepted as a square to stand on, and the push
was attempted from a square the player can never reach.

Measured on the stalled save itself (the emulator booted locally from `state_latest.json`):

* (2, 8) is a **wall tile**: the boulder at (2, 9) cannot be pushed north, and it cannot be pushed
  south either (the player would have to stand on (2, 8)).
* The pressure switch is the only tile 45 of the floor, at **(17, 13)**; the chain boulder was gone and
  the barrier on the rocky ridge (the tile-pair collision 32/5 at (5, 8)-(7, 9)) was closed, so the
  stairs (1, 1) were not among the 131 squares the player could reach.

## Fix

* `Runner.plan_push_direction()`: the direction the floor's plan gives for a boulder. `push_boulder`
  refuses every other direction — **the plan has to win**. A boulder the plan does not name (the rocks
  of (7, 17) and (14, 2)) stays free.
* A push the game refuses is written to the memo (`push_refused`) and **never tried again**; the memo
  is cleared when the player moves to another map.
* `strength_puzzle_step` derives the step of the chain from the **live boulders**: when the step the
  memo points at is not on the floor any more, the chain continues from the first square of the plan
  that holds a live boulder. The chain of a floor that was given up starts over by itself.
* A stand square that is not walkable is not a candidate of the generic push any more.

## Verification

* `python3 -m pytest -q tests/shared/test_pokemon.py` → **194 passed** (191 before, three new guards:
  the plan wins over the generic push, a refused push is never tried again, the chain follows the
  boulders of the floor).
* Deployed on `host-clone-1` and `host-clone-2`; the stall lock was cleared and the next run of the
  dispatcher played on (see the handover of TASK-33 for the run).
