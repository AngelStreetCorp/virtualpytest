# BUG-0888 — The Pokémon stood still on Route 23 for ever while it tried to heal

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0888                                                     |
| Reported  | 2026-10-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The `latest` lane stopped for the seventh time. The run `20261024-085053` (host-clone-1) was written
off as `same_spot` — "the same map position for 300 ticks" — on map **34** (**Route 23**), position
**(4, 32)**, milestone `hall_of_fame`, with 34 milestones done and `deferred: []` (this is **not** a
`deferred_end` stall: nothing was deferred, the Elite Four still needs the real game — there is no
flag to clear). The lock it wrote stopped the lane: the dispatcher starts **no run at all** while
the save is locked, so every minute until the fix was deployed *and* the lock cleared was lost play.

The party was hurt, so the runner had started a **heal trip**, and it never played a step again:

```json
{"kind": "strategy", "trigger": "resumed after a stop", "source": "fallback",
 "plan": "Follow the story: Take Route 22, Route 23 and Victory Road to Indigo Plateau and beat the Elite Four."}
{"kind": "lost", "map": 34, "next": 41}
{"kind": "stalled", "reason": "same_spot", "milestone": "hall_of_fame", "map": 34, "pos": [4, 32]}
```

`next 41` is `0x29` = **Pallet Town's Pokémon Center**: the "lost" event is what `go_to_map()` logs
when it finds no route, so the runner was on its way to a Center and the way was not there.

The game was fine. The runner pressed **no key at all** — the local replay of the stalled save
answers `"no route"` on **every one of 366 ticks**:

```
{"ticks": 366, "counts": {"no route": 366}, "milestone": "hall_of_fame", "map": 34, "pos": [4, 32], "party": 5}
```

## Root cause

**A heal trip was planned to a Pokémon Center that the route cannot start from, and the "no route"
answer was passed straight up, so the tick ended without a key press.**

1. `runner.py:2704` (`heal()`, before the fix) — the candidate Centers were asked of the world
   graph **without the player's part**: `self.world.route(here, m)`. On Route 23 the graph knows the
   way to Pallet Town (`34 --edge south--> 33 (Route 22) --edge east--> 1 (Viridian) --warp--> 41`),
   but Route 23's **south edge lies in another part of the map** than the part the player stands in.
   Measured on the stalled save's own graph:

   ```
   map 34 (Route 23): warps [(7,139)->193, (8,139)->193, (4,31)->108, (14,31)->194]
                       parts: warp [4, 4, 4, 0]   edge: north [0]   south [5, 6]   player: 4
   route(34, 41)               = [(33, edge south), (1, edge east), (41, warp (23,25))]   <- known
   route(34, 41, start_part=4) = None                                                     <- not startable
   ```

   The player's part (4) holds the gate warps and the warp to **Victory Road 1F at (4, 31)** — the
   way on to the Elite Four — but not the south edge; the gate house (193) only leads back to
   Route 23 in the graph.

2. `runner.py:1882-1896` (`go_to_map()`) — the route is looked for with `first_hop_ok`, which asks
   that the **first hop is in the player's own part**. It is not, so the method answers `"no route"`.

3. `runner.py:2715` (`heal()`, before the fix) — the trip's result was returned verbatim. BUG-0877
   had already taught the runner that a heal trip with **no** Center at all must *wait*
   (`"no route to heal"`, and the story goes on) — but only for that case. Here the graph knew a
   Center, and the trip simply could not start.

4. `runner.py:927-929` (`overworld_tick()`) — the heal branch returns the trip's result **unless it
   is exactly `"no route to heal"`**. `"no route"` is not that, so the tick ended there: no key
   pressed, no story played, no battle fought — on every tick, for ever. The stall detector wrote
   `same_spot` after 300 ticks, and the lock it wrote stopped the lane.

`prepare()` (the milestone's own Center trip, `runner.py:2723`) had the same hole, one branch
further down the same method.

## Fix

`shared/src/lib/game/pokemon/runner.py`

- **`Runner.reachable_places()`** (new): the places of a list whose route **can be started** from
  where the player stands — the candidate is filtered with
  `world.route(here, m, start_part=<the player's own part of the map>)`, exactly the part
  `go_to_map()` itself uses to accept a first hop.
- **`Runner.heal()`**: the trip is planned only to a place the route can start from, and a trip that
  is begun and still cannot start (`go_to_map()` answers `"no route"`) **waits** like BUG-0877's
  case instead of ending the tick. The runner goes on playing the story.
- **`Runner.prepare()`**: the same for the milestone's own Center trip.

The runner therefore plays the last mile again: Route 23 → the warp at **(4, 31)** → Victory Road 1F
(its Strength plan for that floor is in the save: `seafoam_plan`, 8 pushes, `seafoam_pushes_done: 0`).

## Tests

`tests/shared/test_pokemon.py::test_a_heal_trip_that_cannot_start_waits_instead_of_freezing_the_tick`
rebuilds the stalled save's own world graph (Route 23 with its parts, Route 22, Viridian, Pallet's
Center) and asserts that the graph knows the way, that the way cannot be started from the player's
part, and that the trip waits instead of freezing the tick. 190 pokemon tests pass.

## In plain words

The Pokémon wanted to heal, set off for the nearest Pokémon Center, and found that the road to it
started on the far side of a gap it could not cross — so it stood on the same square for five
minutes, pressing nothing. The trip is now only planned when it can really start, and when it
cannot, the Pokémon goes back to playing the game instead of standing still.
