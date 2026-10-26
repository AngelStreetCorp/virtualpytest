# BUG-0948 — The Pokémon runner was sealed in the pocket with the stairs, and the lane ping-ponged between two floors

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0948                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | shared (pokémon long-play runner)                            |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/pokemon-pocket-rock`                        |

---

## Symptom

The unattended Pokémon Blue lane (TASK-33) stalled twice on 2026-10-26 in the same shape: the run
`20261026-121745` (host-clone-2) wrote `stall_latest_20261026-121745.json` with the reason
`same_spot` — "the same map position for 300 ticks" — on **map 108** (Victory Road 1F) at square
**(1, 1)**, milestone `hall_of_fame`, 33 milestones done, **no deferral** (`deferred: []`). The
lock was cleared and the fix of BUG-0947 deployed; the next run (`20261026-125130`, host-clone-1)
stalled **on the same square again** with the same report.

The lane **ping-ponged between Victory Road 1F and 2F** and then stood still:

```
{"kind":"push_unreachable","map":108,"boulder":[5,15],"stand":[5,14],"pos":[1,1]}
{"kind":"warp_unusable","map":108,"warp":[1,1]}
{"kind":"warp_retry","map":108,"warp":[1,1]}
{"kind":"push_unreachable","map":194,"boulder":[10,12],"stand":[10,13],"pos":[0,8]}
{"kind":"boulder_push","map":194,"boulder":[5,5],"to":[[5,4]],"direction":"UP","moved":true}
{"kind":"hop_blocked","map":194,"next":198,"target":[1,1]}
{"kind":"lost","map":108,"next":194}
{"kind":"stalled","reason":"same_spot","milestone":"hall_of_fame","map":108,"pos":[1,1]}
```

## Root cause

Three defects of the same floor, each of them enough to freeze the lane.

**1. The player is sealed in the pocket with the stairs.** Victory Road 1F's plan
(`shared/src/lib/game/pokemon/strength.py`) starts with the rock west of the entrance, **(5, 15)**,
and ends with the rock in the corridor to the stairs, **(2, 10)**. A player who comes down the stair
from Victory Road 2F stands in the **pocket** with the stairs (1, 1): the plan's first push cannot be
set up there (its stand (5, 14) is across the corridor rock), so the floor's plan is given up — and
the pocket has no other way out than the stair back up. `push_rock_aside` (BUG-0896) pushed the
**rock of the plan's push** aside; the rock that actually sealed the player in was the **corridor
rock**, so nothing was pushed and the pocket stayed closed.

**2. The mark of the only way down died in the save.** The stair (1, 1) is the only door to map 194.
When a walk toward it did not move the player, the door was marked unusable (BUG-0635); a marked
door is **dead for the milestone**, the route cannot start with it and every tick answered "no
route" (`lost map 108 next 194`) while the player stood on the stair. The mark stayed in the save
(`bad_warps: [[108, 1, 1]]`, `warp_retried: [[108, 1, 1]]`) and the next run inherited it.

**3. The player who stands on a door was judged by a walk that never happened.** The "six ticks that
did not move" rule counts the ticks in which the **player** did not move; when the player stands
**on** the warp square, the rock test of BUG-0925 is vacuous (the layout path from the square to
itself is empty), so the door was judged broken although the stair fires as soon as the player
steps onto it.

## Fix

`shared/src/lib/game/pokemon/runner.py`:

- **the rock that seals the player in is pushed aside, whichever rock of the floor it is**
  (`push_sealing_rock_aside`): the corridor rock of Victory Road 1F is pushed the way the plan wants
  it pushed, from the pocket side, and the corridor opens — so the plan can be run from the side it
  needs. The push waits for the player to stand behind the rock (the walk moves him one square per
  tick).
- **a door the player stands on is never marked unusable** (BUG-0947): the six ticks that did not
  move are the walk's failure to step onto the square, not the door's failure to fire. The hop is
  marked blocked instead (the BUG-0925 sibling), and the guide walks the runner back to the waypoint
  it came from.
- **the mark of a door the player stands on is dropped** (`warp_revived`): the mark says that a walk
  did not move; the player is standing on the square now, and the door fires when he steps on it.

## Verification

- Guard tests, each of them fails without its fix:
  - `test_the_door_the_player_stands_on_is_not_marked_unusable` (BUG-0947),
  - `test_a_door_that_is_dead_for_the_milestone_is_tried_again` (the revival),
  - `test_the_rock_that_seals_the_player_in_is_pushed_aside` (the pocket).
- `python3 -m pytest -q tests/shared/test_pokemon.py` → **216 passed**.
- The diagnosis of the first stall, with the events of the run:
  `~/vpt-private/pokemon/stalls/stall_latest_20261026-121745.diagnosis.md`.

## Still open (not this bug)

* Victory Road 2F's plan against the live save: the push of the boulder at (10, 12) was given up in
  the replay (the stand (10, 13) is out of reach from the landing square (0, 8)) and the rock at
  (5, 5) that stands in the corridor to the stair (1, 1) is pushed **along** the corridor by the
  generic push (`(5,5) → (5,4) → (5,3)`) instead of out of it, which marks the hop (194, 198)
  blocked. That floor is a fix of its own.
* The play of a run that dies mid-way is still lost (the state and the memory are written at the
  end of a run).
