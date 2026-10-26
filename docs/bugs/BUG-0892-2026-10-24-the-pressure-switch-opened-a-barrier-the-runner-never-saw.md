# BUG-0892 — The pressure switch of Victory Road 1F opened a barrier the runner never saw

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0892                                                     |
| Reported  | 2026-10-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | games                                                        |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The `latest` lane of TASK-33 plays Victory Road 1F (map 108) but never finishes the floor.

With BUG-0891 the runner leaves the floor, comes back in and works the floor's Strength plan — the
chain runs, all seven pushes, and the boulder of the pressure switch lands on the switch at
**(17, 13)**. The next push — the corridor boulder at (2, 10) pushed **south** out of the one-wide
corridor to the stairs — is then given up on every visit:

```
{"kind": "push_unreachable", "map": 108, "boulder": [2, 10], "pos": [16, 13]}
```

The floor's plan is given up, the guide asks for the stairs (1, 1), the hop is sealed, the runner
walks back to Route 23 and comes in again: the same seven pushes, the same give-up, for ever.

## Root cause

**The grid keeps the barrier that the switch opens, for ever.**

The push of the corridor boulder needs the player to stand **north** of the boulder, at (2, 9) — in
the part of the floor that the stairs are in. The only way into that part is the pocket of the rocky
ridge, and the game opens the barrier on the ridge **while the boulder of the chain rests on the
pressure switch** (17, 13).

`Runner.grid()` builds the floor's grid from the ROM's tile-pair collisions, and the barrier of the
ridge is one of them — permanently:

```
wall pairs: [((5, 8), (5, 9)), ((6, 8), (6, 9)), ((7, 8), (7, 9)),
             ((11, 3), (11, 4)), ((12, 3), (12, 4)), ((14, 3), (14, 4)), ((15, 3), (15, 4)), ((16, 3), (16, 4))]
```

Measured on the live save (the emulator booted locally from the canonical save): the player's part of
the floor is **129 squares** with the barrier closed, and **292** with any one of the three ridge
pairs open — and then both the stairs (1, 1) and the stand square (2, 9) of the corridor push are
among them. The grid never opened it, so the push could not be set up.

## Fix

* `strength.PuzzleLayout` learns the switch of a floor (`switch_at`) and the wall pairs it opens
  (`switch_opens`): Victory Road 1F's switch is (17, 13) and it opens the three ridge pairs
  ((5, 8)-(5, 9), (6, 8)-(6, 9), (7, 8)-(7, 9)).
* `Runner.grid()` opens that barrier while a live boulder lies on the switch — the same way the game
  opens it.

## Verification

* `python3 -m pytest -q tests/shared/test_pokemon.py` → **199 passed** (198 before, one new guard:
  the switch opens the barrier on the ridge, both ways).
* A local replay of the stalled save with the fix: the chain runs and the floor is walked; see the
  handover of TASK-33 for the runs on the hosts.
