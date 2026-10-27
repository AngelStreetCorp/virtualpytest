# BUG-0968 — The runner walked back to Route 14 instead of through the gate house of Route 15

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0968                                                     |
| Reported  | 2026-10-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | shared (pokémon long-play runner)                            |
| Fixed in  | build 90256 |
| Commit    | branch `fix/pokemon-route15-gate`                             |

---

## Symptom

The unattended Pokémon Blue lane (TASK-33) stalled on 2026-10-27: the run `20261027-052520`
(host-clone-1, the `second` lane) wrote `stall_second_20261027-052520.json` with the reason
`no_progress` — "no milestone, no new map and no new square for 5 min of game time" — on **map 25**
(Route 14) at square **(0, 42)**, milestone `fuchsia`, 21 milestones done (`poke_flute`), **no
deferral** (`deferred: []`).

The player stood at the east end of Route 15 and stepped across the border with Route 14, in both
directions, every half second, for the whole stall window:

```
walk_target  map 26  pos [59, 6]  target [60, 6]  branch route  edge east
walk_target  map 25  pos [0, 42]  target [-1, 42]  branch route  edge west
walk_target  map 26  pos [59, 6]  target [60, 6]  branch route  edge east
... (29 times) ...
stalled      reason no_progress  milestone fuchsia  map 25  pos [0, 42]
```

`battle_s: 0.0` — the runner never fought, never reached Fuchsia, never changed square. The local
replay of the pulled save reproduces it exactly: 508 ticks, 2261 `walk_target` events, every one of
them one of those two squares.

## Root cause

The `fuchsia` milestone (`shared/src/lib/game/pokemon/milestones.py:197`) guides the runner through
`[Lavender, Route 12, Route 13, Route 14, Route 15, Fuchsia]` and lists the maps of its stretch as
its area: `(ROUTE12_GATE,)` — the gate house across Route 12, where the Snorlax sleeps.

The road to Fuchsia passes through a **second** gate house, the one across **Route 15** (map 184):
its two doors are on the route itself, `(7, 8)` and `(14, 8)`, and the route is cut in two without
them. Measured on the live save's world graph and on the ROM's tiles:

| map | id | size | edges | warps |
|---|---|---|---|---|
| Route 13 | 24 | 60 × 18 | north → Route 12, west → Route 14 | — |
| Route 14 | 25 | 20 × 54 | west → Route 15, east → Route 13 | — |
| Route 15 | 26 | 60 × 18 | **west → Fuchsia**, east → Route 14 | **4 doors → 184** |

The player lands on the upper strip of Route 15 (**part 1**) at `(59, 6)`; a row of 44 ledge jumps
(`(16,6)…(59,6)` → `(x,8)`) takes him down to **part 3**, the lower strip east of the gate house.
From there the only way west is the gate house's east door `(14, 8)`, the building, and its west door
`(7, 8)` on **part 2** — the strip that runs on to the west edge, where Fuchsia is. The layout says
so: from `(59, 6)` the A\* reaches **no** square of the west edge.

The world graph learns a map's links only when the runner has been **inside** it, and the gate house
of Route 15 had never been visited. The graph knew the door led to an unknown map, so it knew no way
on to Fuchsia:

```python
>>> world.route(26, 7, start_part=1)     # Route 15 -> Fuchsia, from the player's part
None
>>> world.hops((26, 1))                  # the hops out of the player's part
[((25, None), ('edge', 'east')), ((184, None), ('warp', (14, 8))), ((184, None), ('warp', (14, 9)))]
```

The route search walks into the unknown gate house and stops there: the hops of a map the graph has
never seen are empty, so the search never comes out of it.

The guide therefore took the BUG-0880 branch
(`shared/src/lib/game/pokemon/runner.py:1019-1045`): no route to the next waypoint → walk back to
the waypoint the runner came from → **Route 14**. On Route 14 the guide's next waypoint is Route 15
again (it is the next entry of the milestone's map list), and that route *is* known, so the runner
walked straight back. The two maps swapped the runner for ever. The memo of the stalled save holds
the loop: `waypoint_unreachable = [26, 7, 25]`, `entry = {'from': 25, 'side': 'west', …,
'landing': [59, 6]}`.

The BUG-0963 branch that keeps the waypoint when the milestone's **area** holds the way on never
fired, because the area did not name the gate house of Route 15.

## Fix

The area of a milestone is the list of the maps its stretch passes through — the way on when the
guide's next waypoint cannot be reached yet. The `fuchsia` milestone named the gate house of
**Route 12** but not the one of **Route 15**, which is exactly the map the road to Fuchsia goes
through.

- `shared/src/lib/game/pokemon/milestones.py:197` — the `fuchsia` milestone's area is now
  `(ROUTE12_GATE, ROUTE15_GATE)`.

With the gate house in the area, `Runner.way_on_in_area()` sees the way on and the guide keeps the
goal (Fuchsia) instead of walking back to Route 14; `Runner.find_route()` then finds the gate house
as the exploring hop, the runner steps on the door `(14, 8)`, the game warps it into the gate house
(map 184), the graph learns the gate house's doors, and the way west to Fuchsia is known.

## Verification

- Guard test `test_the_way_to_fuchsia_goes_through_the_gate_house_of_route_15_and_not_back_to_route_14`
  (`tests/shared/test_pokemon.py`): it builds the world graph measured on the stalled save and fails
  without the fix (`AssertionError: BUG-0968: the area holds the way on (the gate house of Route 15)`).
- `python3 -m pytest -q tests/shared/test_pokemon.py` → **225 passed**.
- **Verified on the emulator**: the local replay of the canonical `second` save
  (`test_scripts/game/local/pokemon_play_local.py`) walks on instead of pacing: the runner explores
  the gate house of Route 15, comes out of its west door and walks to Fuchsia City.
- The diagnosis of the stall is in
  `~/vpt-private/pokemon/stalls/stall_second_20261027-052520.diagnosis.md` (private, never
  committed).
