# BUG-0947 — The Pokémon runner marked the door it was standing on as unusable, and the lane froze

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0947                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | shared (pokémon long-play runner)                            |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/pokemon-stair-door`                         |

---

## Symptom

The unattended Pokémon Blue lane (TASK-33) stalled on 2026-10-26 at 12:23 on `host-clone-2`: the
run `20261026-121745` wrote `stall_latest_20261026-121745.json` with the reason `same_spot` — "the
same map position for 300 ticks" — on **map 108** (Victory Road 1F) at square **(1, 1)**, the
milestone `hall_of_fame`, 33 milestones done (`earth_badge`), **no deferral** (`deferred: []`).

Square (1, 1) is the **stair down to Victory Road 2F** — the only way on from that floor. The run's
own events (the last 30) tell the whole story:

```
t=603.17  warp_stuck       map 108 warp [1,1] pos [1,1] in_part true
t=603.65  walk_target      map 108 pos [2,1] target [1,1] branch route
t=649.95  push_unreachable map 108 boulder [5,15] stand [5,14] pos [1,1]
t=649.97  warp_unusable    map 108 warp [1,1]      ← the door is marked unusable
t=650.44  warp_retry       map 108 warp [1,1]      ← BUG-0634's one retry
t=718.26  lost             map 108 next 194        ← "no route": the door is dead
t=3816.03 stalled          reason same_spot map 108 pos [1,1]
```

Between those the player does move: the lane **ping-ponged between Victory Road 1F and 2F** (the
stair does fire — the player lands on map 194 at (0, 8) and pushes the rocks there:
`boulder_push … (5,5) → (5,4) → (5,3)`, then `hop_blocked map 194 next 198 target [1,1]`), and then
the player stood still on (1, 1) of map 108 until the detector wrote `same_spot`.

## Root cause

**The runner marked the door unusable while the player was standing on it.**

`shared/src/lib/game/pokemon/runner.py` — `Runner.go_to_map`, the branch that runs when six ticks
in a row did not move the player:

```python
if self.stuck >= 6:
    if self.boulder_on_the_way(self.pos(), tuple(cands[0])) is not None:
        ... mark_hop_blocked ...          # BUG-0925: a rock seals the corridor to the door
    else:
        self.memo.setdefault("bad_warps", []).append([here, *cands[0]])
        self.event("warp_unusable", ...) # the door itself is broken
```

`self.stuck` counts **ticks in which the player did not move**, not failures of the door. When the
player stands **on** the warp square, the rock test is vacuous: the layout path from (1, 1) to
(1, 1) is empty, so `boulder_on_the_way` answers "no rock in the way" and the code concludes that
the door itself is broken. It is not — the stair fires when the player steps onto it (the same run
landed on map 194 at (0, 8)); what failed was the walk that could not step onto the square from
where the player stood.

The consequence is fatal, and it is the same trap BUG-0925 was about: a door marked unusable is
**dead for the milestone** (BUG-0635). The retry of BUG-0634 un-marks it once (`warp_retry`), the
next failure marks it again, and then no route may start with it at all. `go_to_map` answers
**"no route"** on every tick (`lost map 108 next 194`), the player has nothing left to do, and the
detector writes `same_spot`.

BUG-0925 covers the rock that seals the corridor to the door; this is the other half — the door
the player is **already standing on** — which the handover of 2026-10-26 left open.

## Fix

`shared/src/lib/game/pokemon/runner.py`: when the player stands on the chosen warp square, the door
is **never** marked unusable. The hop is marked **blocked** instead (the BUG-0925 sibling), which
the guide already knows how to use: the waypoint chain (`runner.py`, BUG-0891) then walks the runner
back to the waypoint it came from — Route 23 — the game puts the boulders of Victory Road 1F back
where they were, and the floor's plan (the pressure switch at (17, 13), then the corridor rock at
(2, 10)) can be run from the side it needs.

## Verification

- Guard test `test_the_door_the_player_stands_on_is_not_marked_unusable` in
  `tests/shared/test_pokemon.py`: it fails without the fix (the door is marked unusable:
  `{'bad_warps': [[108, 1, 1]]}`) and passes with it (the hop is marked blocked instead).
- `python3 -m pytest -q tests/shared/test_pokemon.py` → **214 passed**.
- The diagnosis of the stall, with the events of the run:
  `~/vpt-private/pokemon/stalls/stall_latest_20261026-121745.diagnosis.md`.

## Still open (not this bug)

* Victory Road 2F's own plan: the push of the boulder at (10, 12) was given up in the replay (the
  stand (10, 13) is out of reach from the landing square (0, 8)), and the rock at (5, 5) that stands
  in the corridor to the stair (1, 1) is pushed **along** the corridor by the generic push
  (`(5,5) → (5,4) → (5,3)`) instead of out of it, which marks the hop (194, 198) blocked. That
  floor's plan against the live save is a fix of its own.
* The play of a run that dies mid-way is still lost (the state and the memory are written at the
  end of a run).
