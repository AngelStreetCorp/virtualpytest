# BUG-0887 — The Pokémon walked into the boulder that seals the corridor to Victory Road 2F, for ever

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0887                                                     |
| Reported  | 2026-10-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon's long play stopped for the sixth time on the same floor. The run `20261024-072503`
(host-clone-1, the `latest` lane) was written off as `no_progress` — "no milestone, no new map and
no new square for 5 min of game time" — on map **108** (Victory Road 1F), position **(2, 12)**,
milestone `hall_of_fame`, with 34 milestones done and `deferred: []` (this is **not** a
`deferred_end` stall: nothing was deferred, the Elite Four still needs the real game). The lock it
wrote stopped the lane: the dispatcher starts no run at all while the save is locked, so every
minute until the fix was deployed *and* the lock cleared was lost play.

The floor's own puzzle had been solved first — the pressure switch's seven pushes all ran and the
boulder ended on the switch at (17, 13) — and then the corridor boulder was given up:

```json
{"kind": "boulder_push", "map": 108, "boulder": [17, 12], "to": [17, 13], "direction": "DOWN", "steps": 1, "plan_index": 6}
{"kind": "push_unreachable", "map": 108, "boulder": [2, 10], "stand": [2, 9], "pos": [16, 13]}
{"kind": "walk_target", "map": 108, "pos": [16, 13], "target": [1, 1], "branch": "route", "edge": null}
```

After that the run log has **nothing but wild battles** — 48 of them in the 18 minutes that
followed — and then the stall:

```json
{"kind": "battle_choice", "kind_battle": "wild", "enemy_level": 39, "choice": "move2", "choice_name": "TRANCH'HERBE"}
{"kind": "battle_end", "outcome": "won", "battle": "wild", "turns": 1}
… 48 wild battles, no walk, no push, no milestone …
{"kind": "stalled", "reason": "no_progress", "milestone": "hall_of_fame", "map": 108, "pos": [2, 12]}
```

The player never got past (2, 11)/(2, 12) — the two squares are the grass of the floor, and every
step between them is a wild battle.

## Root cause

**A boulder that stands in the way was walked into, never pushed.**

1. `runner.py:2128` — the walk to the stairs is planned with A* on `self.grid()`, and the grid
   blocks the sprites. The boulder at (2, 10) stands in the one-wide corridor that is the only link
   between the player's part of Victory Road 1F and the stairs' part (measured on the stalled save:
   with its square walled the player's part drops from 190 squares to 129 and the stairs (1, 1) are
   out of reach). **A* finds no path** and the walk falls through to its fallback.
2. `runner.py:2142` — the fallback is `overworld.toward(...)`: a greedy step that ignores the walls,
   i.e. straight into the boulder.
3. The game refuses the step (a boulder is a solid object), `self.step()` returns False, and
   `runner.py:2160` — BUG-0740's hop-tile workaround, which presses another direction when the
   planned one does not move the player — then presses a direction that *does* move him: back to
   (2, 12). The next tick the greedy step is north again, the game refuses it, the workaround steps
   south again. **The player ping-pongs between (2, 11) and (2, 12) for ever**, and the grass of the
   floor gives a wild battle on every step.
4. Nothing ever pushed the rock. The only code that pushes a boulder is the floor's plan
   (`strength_puzzle_step`, `runner.py:1251`), and that plan had been closed by `push_unreachable`
   (`runner.py:1330`): the push the plan asks for — the corridor boulder pushed *south* out of the
   corridor — needs the player north of the boulder at (2, 9), behind the pocket the switch opens,
   which the runner's grid still walls off (the cave's jump tiles are not modelled, see BUG-0886).
   `unblock()` and `blocker_on_the_way()` deliberately do **not** name a boulder as a person to talk
   to (BUG-0881) — so the runner had no way left to move the rock at all: it was an obstacle to walk
   into.

## Fix

A boulder is a rock, not a person: it is **pushed with Strength**, the way the game wants it.

- `runner.py:2243` — `push_blocking_boulder(start, target)`: the boulder that blocks the way is
  found on the **layout** path (the path the map allows when the sprites are ignored — that path
  runs through the boulder's square, the sprite path does not). The player stands on the square
  before it and pushes it on.
- `runner.py:2277` — `push_boulder(boulder, path_stand, path_dir)`: the push is *face + Strength +
  step*, exactly like the plan's push. **The game decides** what happens: the boulder may slide, fall
  into a hole or drop to the floor below. A push the game refuses is tried from the next side of the
  boulder. The boulder is never talked to (the game answers "the boulder won't budge").
- `runner.py:2135` — the walk calls the push when its A* finds no path.

The corridor boulder is exactly the push the floor's plan could not set up: the runner cannot stand
north of it, so it pushes it from the side it *can* reach and lets the game resolve it.

## Verification

- `python3 -m pytest -q tests/shared/test_pokemon.py` → **189 passed**, two of them new guards:
  - `test_a_boulder_that_blocks_the_way_is_pushed_with_strength_and_not_walked_into` — the corridor
    of Victory Road 1F, the boulder at (2, 10), the player south of it: the walk pushes the boulder
    north with Strength (the game slides it) instead of walking into it.
  - `test_a_boulder_that_cannot_be_pushed_is_not_talked_to_either` — a boulder the game refuses is
    given up, and it is never talked to.
- Deployed on both Pokémon hosts (`host-clone-1`, `host-clone-2`) and the stall lock cleared with
  `python3 scripts/agent/pokemon_dispatch.py clear-stall`; the next dispatcher tick starts a run
  with `--clear_stall yes`.

## What is still missing

The push of the corridor boulder that the floor's *plan* asks for (south, from the north side at
(2, 9)) still cannot be set up: the pocket the pressure switch opens is walled off in the runner's
grid, because the cave's jump tiles are not modelled (BUG-0886: the ROM's tile pairs
(0x20,0x05), (0x41,0x05), (0x2A,0x05), (0x05,0x21) cut the pocket (5, 8)-(7, 9) off, and the ROM's
ledge table at 0x1A6D4 only holds the outdoor tileset). With this fix the boulder is pushed from the
side the runner can reach instead; if the game refuses that push too, the floor is still unwinnable
for the runner and the next measurement is the cave's jump tiles.
