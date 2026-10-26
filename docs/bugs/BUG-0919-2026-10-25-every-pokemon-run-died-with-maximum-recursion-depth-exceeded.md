# BUG-0919 — Every Pokémon run died with "maximum recursion depth exceeded"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0919                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / pokemon runner                                       |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

**Not one Pokémon run finished.** Every run of the lane died the same way, about 167 s in:

```
19:20:28.109Z +167.396 ❌ [game_pokemon] Unexpected error: maximum recursion depth exceeded
```

The lane's own row said only `Script execution failed`, so the reason was in the run log. The runs
between 09:19 and 19:17 on 2026-10-25 (host-clone-1, one every ~15 min) all died the same way: the
save never moved, and the lane burned its time without playing.

The owner's report was the symptom: *"I don't see coc pokemon playing with minimax."*

## Root cause

A **cycle of three functions with no guard**, entered from the guard fallback of `go_to_map`:

```
walk(target)            the walk to the guard fails: the boulder in the corridor seals him off
  └─ push_blocking_boulder   the boulder is asked to move; the plan's push is impossible, so none is made
  └─ unblock(start, target)   "a person stands on the way": the guard himself
       └─ talk_at(guard)      talking to him means walking to him
            └─ walk(guard)    ... and the walk starts the whole thing again
```

The numbers come from the run that died: the player stood at **(11, 2)** on **Victory Road 1F**
(map 108), the guard was at **(9, 2)** and the corridor boulder at **(10, 2)**. The guard is in a
pocket with no other way in, so the walk to him could never succeed — and each turn of the cycle
asked the same question again.

Two things had to be true for this to bite, and both did:

- **The guard was chosen as a fallback even though he was out of reach.** `guard_in_reach` picked
  "the nearest person in the player's part", and the part is the **layout's** (the people move or
  fight), so the boulder — a rock on the floor — was not in the way. The runner chased a man it
  could never reach.
- **Nothing broke the cycle.** `unblock` asked `talk_at` to walk to the blocker, `talk_at` asked
  `walk` to walk to him, and `walk` asked `unblock` again. Python's recursion limit ended the run.

Reproduced locally from the canonical save with the same traceback (`walk` → `unblock` →
`talk_at` → `walk` → …), then the fix was checked the same way: **833 ticks, no error**.

## Fix

- `shared/src/lib/game/pokemon/runner.py` — `unblock` does not talk to a person who stands on the
  target square: talking to him means walking to him, which is the caller's own work and has just
  failed. There is no way on; the caller re-plans.
- `shared/src/lib/game/pokemon/runner.py` — `talk_at` does not walk to a man it is already walking
  to. The safety net for the cycle: no walk can ask the same walk the same question twice.
- `shared/src/lib/game/pokemon/runner.py` — `guard_in_reach` skips a person a boulder seals off
  (the layout is passed in, and the boulder on the layout path between the player and him is
  checked). The runner does the boulder puzzle instead of talking to a man it cannot reach.

## Verification

- `python3 -m pytest -q tests/shared/test_pokemon.py` → **211 passed**, three of them new: the
  person on the target square is not talked to through the walk, the same man is not walked to
  twice, and a guard a boulder seals off is not the guard to talk to. All three fail without the fix.
- Replay of the canonical save on the local emulator: **833 ticks, no error** (before: a
  `RecursionError` at ~167 s), the runner won the trainer battle of Victory Road 1F and carried on.
