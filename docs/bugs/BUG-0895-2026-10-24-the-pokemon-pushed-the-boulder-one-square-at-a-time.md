# BUG-0895 — The Pokémon pushed the boulder one square at a time and lost the chain of the floor

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0895                                                     |
| Reported  | 2026-10-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | games                                                        |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The `latest` lane of TASK-33 stopped on **Victory Road 1F** (map 108) and wrote the lock that stops
the dispatcher from playing at all. The run `20261024-152049` played 390 ticks and wrote the events
of a chain of pushes that never reached its goal:

```
{"kind": "boulder_push", "map": 108, "boulder": [5, 16], "to": [9, 16], "direction": "RIGHT", "steps": 4, "plan_index": 1}
{"kind": "boulder_push", "map": 108, "boulder": [9, 16], "to": [9, 14], "direction": "UP", "steps": 2, "plan_index": 2}
...
{"kind": "boulder_push", "map": 108, "boulder": [17, 12], "to": [17, 13], "direction": "DOWN", "steps": 1, "plan_index": 6}
{"kind": "push_unreachable", "map": 108, "boulder": [2, 10], "stand": [2, 9], "pos": [16, 13]}
{"kind": "walk_target", "map": 108, "pos": [16, 13], "target": [1, 1], "branch": "route", "edge": null}
```

The seven pushes of the floor's plan ran, the pressure switch was "reached", and the corridor push
was given up anyway: the stand square (2, 9) of the corridor push is out of reach, the runner left
the floor for Route 23, the game put the boulders back where they were, and the chain started over —
twice, for ever. The stall detector wrote `no_progress` ("no milestone, no new map and no new square
for 5 min of game time", `progress_s` 307.9, 44 cells). `deferred` was empty: the lane was not
waiting for a deferred goal.

## Root cause

**A push of the plan was one press per square of rock — the game needs one press for the rock and
about three more presses for the player to step into the square the rock left.**

`Runner.strength_puzzle_step()` (shared/src/lib/game/pokemon/runner.py:1405-1407) pushed like this:

```python
# Push: each `step` slides the boulder one square and the player follows onto its old tile.
for _ in range(steps):
    self.step(direction)
```

The game does not answer every press. pokered — the disassembly of the very game this ROM is — says
why (`engine/overworld/push_boulder.asm`): the dust of a push is played by `AnimateBoulderDust`
(eight steps of `Delay3`) and `DoBoulderDustAnimation` then calls `DiscardButtonPresses` and
`ResetBoulderPushFlags`. While the dust plays, the game ignores the button **and** the player cannot
step into the square the rock left. Measured on the stalled save with the emulator booted locally
from the canonical save (the rock of the corridor at (2, 10), the player at (2, 11), Strength in use):

```
press 1: player (2,11)  boulders [(2,9), …]   <-- the rock moved one square
press 2: player (2,11)  boulders [(2,9), …]   <-- swallowed by the dust of the push
press 3: player (2,11)  boulders [(2,9), …]   <-- swallowed
press 4: player (2,10)  boulders [(2,9), …]   <-- the player steps into the square the rock left
```

So **four presses moved the rock one square**, and the plan's second push ("RIGHT 4" from (5, 16))
left the rock at (6, 16). The replay of the stalled save proves it: the runner's own generic push
found the rock at **(7, 16)** and pushed it to (7, 17) — the chain's rock, one square and not four
along its track.

From there the chain lost its track: the next step names (9, 16), no rock is there, and the runner
pushed air six times while its `boulder_push` events reported the plan's claim
(`runner.py:1423-1426` computes `boulder_xy + step * steps`) instead of what the game did. The rock
never lay on the pressure switch **(17, 13)**, so the game never opened the passage of the floor
(pokered's `scripts/VictoryRoad1F.asm`: the map script of the floor runs every frame, checks with
`CheckBoulderCoords` whether a rock lies on `dbmapcoord 17, 13` and then replaces the tile block at
(6, 4)), the stand square (2, 9) of the corridor push stayed out of reach, and the runner paced the
floor until the lane locked.

**This also corrects the reading of BUG-0894**: the boulder did not fall into a hole at (17, 13) —
it never got there. The chain lost its track one push earlier, on the way.

## Fix

`Runner.strength_puzzle_step()` watches the rock while it pushes:

* the live rocks are read before the first press and after every press;
* a press that moves no rock is a press the game swallowed: the runner presses again;
* the push ends when the rock has moved the number of squares the plan asks for, or when the rock is
  gone (it fell into a hole or it lies on the switch);
* a budget of `PUSH_PRESSES_MAX` (6) presses per square of the plan keeps a push the game refuses
  from running for ever;
* the field move is asked for once per push, after the press that faces the boulder — a press that
  finds the rock in front of the player moves it too when the field move of the last push is still
  in use, and the rock is watched from that press on.

The plan of the floor, the pressure switch and the grid are unchanged: the chain still pushes the
boulder to (17, 13), and the game opens the passage itself.

## Verification

* `python3 -m pytest -q tests/shared/test_pokemon.py` → **200 passed** (the guard
  `test_the_push_of_a_plan_presses_until_the_rock_has_really_moved` is the new one; the guard of
  BUG-0894 still holds).
* A local replay of the stalled save with the fix: the chain of the floor runs to its end, the rock
  lands on the pressure switch and the game opens the passage — see the handover of TASK-33 for the
  runs on the hosts.
