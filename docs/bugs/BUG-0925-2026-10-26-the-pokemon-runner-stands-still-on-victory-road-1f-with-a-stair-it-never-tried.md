# BUG-0925 — The Pokémon runner stood still for 300 ticks on Victory Road 1F with a stair it never tried

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0925                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | shared (pokémon long-play runner)                            |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/pokemon-stall`                               |

---

## Symptom

The unattended Pokémon Blue lane (TASK-33) stalled on 2026-10-26 at 02:07 on `host-clone-1`: run
`20261026-020740` wrote `stall_latest_20261026-020740.json` with the reason `same_spot` — the same
map position for 300 ticks — on map 108 (Victory Road 1F) at square (7, 6), with the milestone
`hall_of_fame`. The last events of the run:

```
{"kind":"strategy","source":"llm","plan":"Attaquer immédiatement les encounters de haut niveau des Routes 23 et Victory Road …"}
{"kind":"battle_end","outcome":"won","battle":"trainer","turns":3}
{"kind":"lost","map":108,"next":194}
{"kind":"stalled","reason":"same_spot","milestone":"hall_of_fame","map":108,"pos":[7,6]}
```

`lost {map:108, next:194}` is the runner's note that it could not find a route to the next
milestone map. From that tick on, every tick answered `no route` and the player never moved.

## Root cause

**A door that was never stepped on was marked unusable, and that killed the only way down.**
Victory Road 1F has exactly one way down: the stair at (1, 1) → map 194. The memo of the stalled
save ended with `bad_warps = [[108,1,1]]` *and* `warp_retried = [[108,1,1]]`; in `go_to_map` a warp
that is in both lists is dead for the milestone (BUG-0635), `world.route(108, 194, …)` returns
`None`, and the runner falls through to the guard branch and answers `no route` for ever.

The mark was wrong. It is written by the "warp unusable" escalation in `go_to_map` (six steps that
did not move the player) — but the stair was **never tried**: the player's part of the map is
computed from `grid(sprites_block=False)`, and a boulder is a *sprite*, so the stair square was
inside the part while the walk itself (`grid()`, sprites block) could not reach it — a rock sealed
the one-wide corridor to the stairs. A door that was never stepped on is not unusable. The mark
for that case already exists (`mark_hop_blocked` / the `hop_blocked` event, BUG-0891) and was not
used.

The run that fell into this state is the one whose crash was fixed by BUG-0919 (the cycle
`walk` → `unblock` → `talk_at` → `walk`, which ended every run of the lane with *maximum recursion
depth exceeded*): the deployed code on the host was still that one, so the runner never got past
the guard fallback — and the marks it left behind kept the floor walled in afterwards.

The `deferred` list of the stall report is empty: no `*_deferred` flag is part of this fix — the
game still needs the stair to reach the Hall of Fame.

## Fix

One change in `shared/src/lib/game/pokemon/runner.py`: the "warp unusable" escalation does not
fire when a rock seals the way to the door (`boulder_on_the_way`). The rock is the problem: the hop
is marked blocked (BUG-0891) and the door stays unmarked, so the only way down of the floor is not
dead for the milestone. The guide then walks the runner back to the map it came from, where the
game puts the rocks of the floor back where they were, and the floor can be solved again.

The stale marks of the stalled save are dropped by the lock clear itself
(`stall.forget_on_unlock` clears `bad_warps` and `warp_retried`), so the next run retries the
stair.

## Verification

* `tests/shared/test_pokemon.py::test_a_door_that_a_rock_seals_is_not_marked_unusable` — a door
  that a rock seals stays unmarked and the hop is marked blocked; a door that really fails six
  steps in is still marked unusable (BUG-0635 kept). The test fails without the fix.
* `python3 -m pytest -q tests/shared/test_pokemon.py` — 212 passed.

## Not fixed here

Victory Road 2F (map 194) has no workable plan yet: its own push cannot be set up
(`push_unreachable [10,12] stand [10,13]`) and the hop to Victory Road 3F is marked blocked. That
is the next wall of the `hall_of_fame` milestone and is tracked in the TASK-33 handover.
