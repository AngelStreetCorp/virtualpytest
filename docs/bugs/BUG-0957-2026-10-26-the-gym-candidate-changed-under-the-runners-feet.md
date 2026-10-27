# BUG-0957 — The gym's leader changed under the runner's feet, so it ping-ponged between two squares

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0957                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | shared (pokémon long-play runner)                            |
| Fixed in  | build 90256 |
| Commit    | branch `fix/pokemon-gym-candidate`                           |

---

## Symptom

The unattended Pokémon Blue lane (TASK-33) stalled on 2026-10-26: the run `20261026-163011`
(host-clone-1, the `second` lane) wrote `stall_second_20261026-163011.json` with the reason
`no_progress` — "no milestone, no new map and no new square for 5 min of game time" — on **map 65**
(the Cerulean gym) at square **(5, 11)**, milestone `cascade_badge`, 9 milestones done
(`cerulean`), **no deferral** (`deferred: []`).

The run itself is almost empty: the strategist's plan, and then the stall.

```
{"t": 1793028626.08, "kind": "strategy", "trigger": "resumed after a stop", "source": "llm",
 "plan": ["Soigner HERBIZARRE jusqu'à récupérer tous ses PV avant le combat.",
          "Se rendre au gymnase de Cerulean City et affronter Misty.", …]}
{"t": 1793029020.23, "kind": "stalled", "reason": "no_progress", "milestone": "cascade_badge",
 "map": 65, "pos": [5, 11]}
```

A local replay of the canonical save (booted in the local emulator) reproduces it exactly:
**220 ticks, 220 of them `walk`, no other action at all**; the battle time of the run is `0.0 s`.

## Root cause

**The runner picked the gym's leader again on every tick, and who is on screen depends on where the
player stands.**

`shared/src/lib/game/pokemon/runner.py`, `goal_action()`:

```python
people = overworld.sprite_list(self.read)
leader = self.gym_leader(people)      # BUG-0716: the person standing in the player's room
if leader is None and people:
    alone = [p for p in people if self.is_person(p, people)] or …
    leader = min(alone, key=lambda p: p[1][1]) if alone else None
```

`gym_leader()` keeps the person who is **on screen** (the trainers of the other rooms are hidden,
and one of them can have a picture of his own — the runner then chased a trainer it could never
reach). The visible window is 10 × 9 squares around the player, so the candidate depends on the
player's own square.

Measured on the live save, the Cerulean gym (map 65, 10 × 14 squares, entrance at `(4, 13)` /
`(5, 13)`) holds four people:

| picture | square | who |
|---------|--------|-----|
| 29 | (4, 2) | the leader at the top of the room (Misty) |
| 6 | (2, 3) | a trainer |
| 34 | (8, 7) | a trainer |
| 36 | (7, 10) | a trainer — already in the save's `not_leaders` blacklist |

With the player at **(5, 11)**, the trainer at **(8, 7)** is on screen and is the candidate; the
path to him starts **DOWN**. One square later the player stands at **(5, 12)**, the window moves up,
the trainer goes **off screen**, the fallback (the topmost person of the gym — the leader at
(4, 2)) becomes the candidate, and its path starts **UP**. At (5, 11) the trainer is on screen once
more, and the candidate is the trainer again. The trace of the real runner on the live game:

```
tick 1  pos=(5, 11)  astar (5, 11) -> (8, 7) = ['DOWN','RIGHT','RIGHT','RIGHT','RIGHT','UP','UP','UP','UP','UP','LEFT']
tick 2  pos=(5, 12)  astar (5, 12) -> (4, 2)  = ['UP', …]
tick 3  pos=(5, 11)  astar (5, 11) -> (8, 7) = ['DOWN', …]
tick 4  pos=(5, 12)  astar (5, 12) -> (4, 2)  = ['UP', …]
```

Two candidates, opposite directions: the runner ping-ponged between (5, 11) and (5, 12) until the
detector wrote the stall down.

The save's memory shows how the runner got there: `not_leaders: [[7, 10], [3, 6]]` (the trainer of
(7, 10) was already judged "not the leader") and `leader_talked: [4, 1]` — a person of **Cerulean
City**, because the map id switches to the gym before the player is placed in it, so the runner
once took a citizen of the city for the leader of the gym.

## Fix

`shared/src/lib/game/pokemon/runner.py`: the candidate is **remembered** — `leader_candidate` in the
memo, with the map it was seen in (`[map, x, y]`). It only changes when

* the person is gone (beaten) or is judged not to be the leader,
* the runner is in another gym (the map does not match), or
* he cannot be walked to (`no path` — he is in another room: the next person of the gym is tried
  instead of walking the same unreachable square for ever).

The on-screen rule of BUG-0716 stays: the runner still prefers the person of the player's room — it
just does not change its mind every time it takes a step. The memo keeps the candidate across runs,
so a run that ends on the way to the leader does not restart the ping-pong.

## Verification

- Guard test `test_the_gym_candidate_does_not_change_under_the_runners_feet` in
  `tests/shared/test_pokemon.py` (fails without the fix).
- `python3 -m pytest -q tests/shared/test_pokemon.py` → 218 passed.
- Local replay of the canonical save of the stalled run with the fix: the runner walks to the trainer
  of (8, 7), fights him, then goes up to the leader at (4, 2) — the gym's door is not a dead end
  any more.
- The diagnosis, with the measured geometry of the gym:
  `~/vpt-private/pokemon/stalls/stall_second_20261026-163011.diagnosis.md`.

## Still open (not this bug)

* The map id switches to the gym before the player is placed in it, so for one tick the runner sees
  the people of the city in the gym's map: it can still take a citizen for the leader once. The
  remembered candidate self-heals (the citizen is not in the gym's list, the candidate is dropped).
* The trainer of the gym is fought before the leader is reached: the runner walks to whoever is on
  screen first. It is normal play, but the leader could be reached first if the rule changed.
