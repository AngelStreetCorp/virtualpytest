# BUG-0877 — The heal trip never ended: the runner stood still on Victory Road 1F for ever

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0877                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon's long play stopped for good. The run `20261023-173029` (host-clone-2) was written off
as `same_spot` — "the same map position for 300 ticks" — on map **108** (Victory Road 1F), position
**(2, 12)**, milestone `hall_of_fame`. The lock it wrote stopped the lane, so the game lost every
minute until the fix was deployed.

The runner was not stuck on the boulder and the game was not frozen: a local replay of the stalled
save answers with one thing only:

```
{"ticks": 605, "counts": {"no route to heal": 605}, "milestone": "hall_of_fame",
 "map": 108, "pos": [2, 12], "party": 5, "stalled": null, "emulator_gone": false}
```

**605 of 605 ticks** were `no route to heal`: the runner never played a single step. The events of
the run before it show how it got there — it fled a wild battle with a hurt party and started a
heal trip:

```
1792768539  battle_end   outcome=fled
1792768539  heal_start   hp=91 max_hp=454
1792768618  stalled      same_spot  map 108  pos [2, 12]
```

## Root cause

**A heal trip that cannot end is a dead end.**

`shared/src/lib/game/pokemon/runner.py:2506` `heal()` asks the world graph where a Pokémon Center
(or the player's house) is:

```python
places = [m for m in (PLAYERS_HOUSE_1F,) + POKEMON_CENTERS if m == here or self.world.route(here, m)]
if not places:
    return "no route to heal"
```

On Victory Road 1F the learned graph knows **no** way to any of the 12 known Centers or to the
player's house (`world.route(108, <every Center>)` is `None`), so `places` is empty.

`shared/src/lib/game/pokemon/runner.py:906-908` `overworld_tick()` never let the trip go:

```python
if tot and (self.memo.get("healing") or cur / tot < HEAL_BELOW or no_attack):
    ...
    if not asked or self._decide_heal(...) != "push":
        return self.heal(here, cur, tot)          # the story is never reached
```

`memo["healing"]` is only cleared when the party is **fully healed** (`runner.py:2512-2517`). The
party cannot be healed, so the flag stayed set for ever, `overworld_tick()` answered `no route to
heal` on every tick, the position never changed, and the stall detector wrote `same_spot` after 300
ticks.

**The floor behind it** (measured on the live floor): Victory Road 1F's boulder at (2, 10) seals the
one-wide corridor to the stairs at (1, 1), so the square the push starts from — (2, 9) — is out of
reach (`overworld.astar` returns `None` for both (2, 9) and (1, 1)), and the boulder cannot be pushed
from the other side either: pushed north it only goes as far as (2, 9), which seals the corridor just
as well (verified in the emulator: the boulder moves (2, 10) → (2, 9) and then stops).

## Fix

* `shared/src/lib/game/pokemon/runner.py` — `heal()`: a trip with no reachable healing place **waits**
  instead of answering for ever, and `overworld_tick()` goes on playing the story (the new
  `heal_waiting` event says the trip is on hold). The trip is taken up again as soon as the way to a
  Center is known, and it is not restarted (nor logged again) on every tick.
* `shared/src/lib/game/pokemon/runner.py` — `strength_puzzle_step()`: a push whose start square
  cannot be walked to is **given up** for that floor (the `push_unreachable` event says why) and the
  guide walks the runner on, instead of asking for the impossible square on every tick.

No defer flag is involved: the game's memory has no `*_deferred` flag, and the story needs the whole
game — the Elite Four and the Hall of Fame are still ahead.

## Verification

* Guard tests in `tests/shared/test_pokemon.py`
  (`test_the_runner_keeps_playing_when_no_healing_place_is_reachable`,
  `test_a_push_that_cannot_be_set_up_is_given_up_instead_of_asked_for_again`).
* A local replay of the stalled save: 605 ticks of `no route to heal` before, and after the fix the
  runner plays on (it walks, it gives the unreachable push up, it moves off the square).
* Deployed to host-clone-1 and host-clone-2; the lane's lock is cleared and the next run starts with
  `--clear_stall yes`.

Diagnosis: `~/vpt-private/pokemon/stalls/stall_latest_20261023-173029.diagnosis.md`.

## What is still open

The way on from Victory Road 1F is Route 23's second warp, `(14, 31) -> Victory Road 2F (194)` — the
game's own warp table holds it, but the world graph's part model (a warp square splits the map it
stands on) hides it from the part the player stands in. That is the next piece of TASK-33, written
up in the handover.
