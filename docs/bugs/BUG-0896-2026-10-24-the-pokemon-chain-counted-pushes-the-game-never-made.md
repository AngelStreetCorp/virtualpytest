# BUG-0896 — The Pokémon chain of a floor counted pushes the game never made

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0896                                                     |
| Reported  | 2026-10-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games                                                       |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The `latest` lane stopped on **Victory Road 1F** (map 108) and locked the save. The run
`20261024-225457` ended with `no_progress`: "no milestone, no new map and no new square for 5 min
of game time", at map 108, pos (11, 14), milestone `hall_of_fame`.

The last 30 events of the run are **290 identical `hop_blocked` events** —

```
hop_blocked  map 108  next 194  target [1, 1]
```

— interleaved with two wild battles the strategist fled (`FLORIZARRE` level 68 at 23/234 HP against
`MACHOC` 24 and `NOSFERALTO` 41: `FUITE` every time). The battle ticks do not count towards the
no-progress clock, so the lane locked with the runner walking at the stairs of a floor whose
puzzle it had already given up.

## Root cause

The push of a Strength plan is **not** one press per square of rock: the game plays the dust of a
push (`AnimateBoulderDust` runs eight steps of `Delay3` and `DoBoulderDustAnimation` discards the
button press) and the player cannot step into the square the rock left before the dust is over.
BUG-0895 made the runner press until the rock had really moved — but the loop still counted **one
change of the set of live boulders** as one square of rock:

```python
while moves < steps and presses < PUSH_PRESSES_MAX * steps:
    ...
    if live == before:
        continue                    # the press did not move the rock: press again
    gone = len(live) < len(before)
    before = live
    moves += 1                     # <-- a swallowed press counts as a square of rock
```

So a push that moved the rock two of its four squares ended with `moves == steps`, the event
reported the plan's claim (`to = rock_pos or next_xy`) and the chain advanced
(`self.memo["seafoam_pushes_done"] = done + 1`) — whatever the game did. In the stalled run the
chain lost the rock on its **second** push:

```
boulder_push  boulder [5,16] → [7,16]  RIGHT 4  plan_index 1      ← only 2 of the 4 squares
boulder_push  boulder [9,16] → [9,16]  UP 2    plan_index 2      ← the rock did not move at all
boulder_push  boulder [9,14] → [9,14]  RIGHT 7 plan_index 3      ← air
...                                                          (six pushes against nothing)
push_unreachable  boulder [2,10] stand [2,9] pos [16,13]         ← the floor is given up
```

The rock stood at **(7, 16)** while the chain believed it was on (9, 16), (9, 14), (16, 14),
(16, 12), (17, 12). The pressure switch **(17, 13)** was never pressed, the game never opened the
passage of the floor, the stand square **(2, 9)** of the corridor push stayed out of reach and
`push_unreachable` gave the plan up (`seafoam_pushes_done = 8`). The guide's way on — the stairs at
(1, 1) — stayed sealed, the fallback (BUG-0891) sent the runner to Route 23 and back again, and
the two maps took turns until the detector locked the save.

The chain's state was the runner's own counter, and `strength.py` had no way to say where the chain
really was: the plan is a list of `(square, direction, squares)` and nothing read the floor's
boulders back.

## Fix

- `shared/src/lib/game/pokemon/strength.py` — new `chain_step(plan, live, upto)`: the chain is read
  from the **live boulders**. The rock that stands on the square a step starts from is the step to
  do; a rock that stands *between* two squares of the plan (a push that was cut short) is pushed on
  to the end of that step; the rock may only pull the chain **back** (BUG-0891: a rock that is out
  of sight is not gone, so the chain never jumps to a later push because another rock happens to be
  in sight).
- `shared/src/lib/game/pokemon/runner.py` (`Runner.strength_puzzle_step`) — the push now ends when
  the rock has **really** reached the square the step wants (or the rock is gone), and the chain
  advances only then. A push that moved nothing writes a `push_short` event, does not advance the
  chain and is tried again; a rock that refuses to move is given up after three tries
  (`seafoam_plan_given_up`, cleared when the player comes back — the game puts the boulders of a
  floor back where they were). The `boulder_push` event now says what happened: `reached` (the rock
  is on the square the plan wants) and `moved` (the rock moved at all).
- `Runner.plan_push_direction` — the generic push respects the plan for a rock that stands between
  two squares of the plan too, so the rock is not shoved off the chain's track.
- A rock that moved clears the `hop_blocked` marks of the floor: the hop the rock stood in the way
  of is walkable again (the marks were only dropped when the player left the map, and a floor whose
  every way out is marked blocked is a floor the player cannot leave).
- `Runner.push_rock_aside` — the rock of the pressure switch of Victory Road 1F stood at **(9, 14)**,
  the **doorway** to the pocket with the stairs: the player was **east** of it, in a part of **24
  squares**, and the floor is **159** the other side. The plan's push (east) needs the player *west*
  of the rock, which it could not reach — and the rock was the only way out of the pocket, so the
  runner could not leave the floor at all. The rock is now pushed out of the way when it **seals the
  player in**: the player steps into the square the rock leaves, and the game puts the boulders of
  the floor back where they were when the player leaves it, so the chain runs again from the start.
  The corridor boulder (2, 10) does not seal the player in (it closes the pocket with the stairs,
  which is the big floor's side), so the plan keeps its way there (BUG-0890).

## Verification

- `python3 -m pytest -q tests/shared/test_pokemon.py` → **206 passed** (6 new guard tests: the
  chain follows the rock and not the counter, a push that does not move the rock does not advance
  the chain, the chain pushes a rock that stands between two squares of the plan, the chain pushes
  a rock that was pushed the wrong way, a rock that seals the player in is pushed out of the way,
  and a push that does not open the plan is not done).
- **On the live host** (the run of 2026-10-24, deployed `main-2026.10.24-89958`): the chain found
  the rock of the pressure switch at (9, 14) and the player was pushed out of the pocket with it:
  `boulder_push … boulder [9, 14] → [[8, 14]] direction LEFT moved True aside True`, the player on
  **(9, 14)** — out of the 24-square pocket, on the floor again.
- A local replay of the canonical save with the fix (`pokemon_play_local.py`, 420 s) is reported in
  the TASK-33 handover entry.
