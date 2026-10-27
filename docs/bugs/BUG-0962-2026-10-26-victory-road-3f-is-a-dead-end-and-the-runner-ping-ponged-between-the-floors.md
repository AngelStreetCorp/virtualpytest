# BUG-0962 — Victory Road 3F is a dead end, so the runner ping-ponged between the two floors of Victory Road

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0962                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | shared (pokémon long-play runner)                            |
| Fixed in  | build 90256 |
| Commit    | branch `fix/pokemon-vr3f-hop`                                |

---

## Symptom

The unattended Pokémon Blue lane (TASK-33) stalled on 2026-10-26: the run `20261026-193346`
(host-clone-2, the `latest` lane) wrote `stall_latest_20261026-193346.json` with the reason
`no_progress` — "no milestone, no new map and no new square for 5 min of game time" — on **map 194**
(Victory Road 2F) at square **(6, 8)**, milestone `hall_of_fame`, 33 milestones done (`earth_badge`),
**no deferral** (`deferred: []`).

The run solved the floor's puzzle and then went the wrong way — **up** into Victory Road 3F, from
where the way out is behind a boulder, back **down** to Victory Road 2F, where the milestone sent it
up again:

```
boulder_push map 194 boulder [4,14] to [3,14] direction LEFT  steps 1 plan_index 0 reached true moved true
boulder_push map 194 boulder [3,14] to [3,16] direction DOWN  steps 2 plan_index 1 reached true moved true
boulder_push map 194 boulder [3,16] to [1,16] direction LEFT  steps 2 plan_index 2 reached true moved true
walk_target    map 194 pos [3,16] target [23,7] branch route          ← the stair UP to Victory Road 3F
push_unreachable map 198 boulder [5,8] stand [5,7] pos [23,6]          ← on Victory Road 3F
walk_target      map 198 pos [23,6] target [26,8] branch route
boulder_push     map 198 boulder [13,12] to [[13,13]] direction DOWN steps 1 moved true
boulder_push     map 198 boulder [13,13] to []        direction DOWN steps 1 moved false
hop_blocked      map 198 next 9 target [26,8]                         ← the way out is sealed
walk_target      map 198 pos [13,11] target [23,7] branch route       ← back down to Victory Road 2F
stalled          reason no_progress milestone hall_of_fame map 194 pos [6,8]
```

The diagnosis is in `~/vpt-private/pokemon/stalls/stall_latest_20261026-193346.diagnosis.md`.

## Root cause

**The waypoints of the `hall_of_fame` milestone sent the runner from Victory Road 2F into Victory
Road 3F — a floor whose four exits all lead back to Victory Road 2F.**

Measured on the live save (the world graph of the run):

| map | what it is | its exits (the game's own warp table) |
|-----|------------|--------------------------------------------|
| 198 | Victory Road 3F | `(23,7) → 194`, `(26,8) → 194`, `(27,15) → 194`, `(2,0) → 194`, **no edge exit** |
| 194 | Victory Road 2F | `(0,8) → 108`, `(29,7)/(29,8) → 34` (Route 23), `(23,7)/(25,14)/(27,7)/(1,1) → 198` |
| 108 | Victory Road 1F | `(8,17)/(9,17) → 34` (Route 23), `(1,1) → 194` |
| 34 | Route 23 | north edge → **9 (Indigo Plateau)**, south edge → 33, `(4,31) → 108`, `(14,31) → 194` |

Victory Road 3F is a dead end, and the way to the Elite Four is Route 23's north edge (map 34 → map
9, Indigo Plateau).

The runner takes the waypoint **after** the one it stands on
(`shared/src/lib/game/pokemon/runner.py`, `j = min(i + 1, len(maps) - 1)`), and the waypoints of the
milestone (`shared/src/lib/game/pokemon/milestones.py`) read
`[… ROUTE_23, VICTORY_ROAD_1F, VICTORY_ROAD_2F, VICTORY_ROAD_3F, INDIGO_PLATEAU …]`:

* on Victory Road 2F the next waypoint was **Victory Road 3F** — the runner climbed up;
* on Victory Road 3F the plan of the floor could not be set up (its boulder at (5, 8) is sealed in
  by the boulder at (13, 12)), the floor's plan was given up, and the only hop that leads to the way
  out (the warp `(26, 8)`, the one that lands next to Route 23) was behind that boulder — the hop
  was marked blocked and the guide sent the runner **back** to the waypoint it came from
  (`waypoint_unreachable = [198, 9, 194]`);
* on Victory Road 2F the next waypoint was Victory Road 3F again — the two floors swapped the
  runner for ever, until the detector wrote `no_progress`.

The boulder at (13, 12) is not the cause of the stall: it was pushed (to (13, 13), then into the
hole) and the corridor opened. The runner still ping-ponged, because the milestone asked for the
dead end on both floors.

## The fix

The floors of Victory Road above 1F are no waypoints of the last mile:

```
[VIRIDIAN_GYM, VIRIDIAN, ROUTE_22, ROUTE22_GATE, ROUTE_23,
 VICTORY_ROAD_1F, INDIGO_PLATEAU, INDIGO_PLATEAU_LOBBY, HALL_OF_FAME]
```

The floors stay in the milestone's **area** (the runner stands in one of them and has to get out)
and Victory Road 1F stays a waypoint (the runner comes through the Route 22 gate and crosses it).
The way to the Elite Four is Route 23's north edge, and the runner reaches it from Victory Road 1F
((8, 17)/(9, 17)) or from Victory Road 2F's east side ((29, 7)/(29, 8)).

The two protections of the last mile keep working: the guide still asks for Victory Road 1F from
Route 23 (BUG-0880) and still walks back to Route 23 when the waypoint cannot be reached (BUG-0891);
the waypoint it asks for on Victory Road 1F is Indigo Plateau now.

Guard test `test_the_way_to_the_elite_four_does_not_go_through_the_dead_end_of_victory_road` (fails
without the fix) — it pins the measured topology (3F's four exits all lead to 2F, the route to Indigo
Plateau goes over Route 23) and the waypoint list.
`python3 -m pytest -q tests/shared/test_pokemon.py` → **219 passed**.

## In plain words

The runner solved Victory Road's puzzle and then walked up into the floor above, where every exit
leads back down — and the milestone told it to go up again, so it bounced between the two floors
until the run was written off as "no progress". Victory Road's upper floors are a dead end on the
way to the Elite Four (the way is Route 23's north edge), so they are no longer on the list of
places to go: the runner now leaves Victory Road and walks north to Indigo Plateau.
