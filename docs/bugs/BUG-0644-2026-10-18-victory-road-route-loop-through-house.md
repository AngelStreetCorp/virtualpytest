# BUG-0644 — Pokémon route search loops through a house and back past its first-hop filter

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0644                                                     |
| Reported  | 2026-10-18                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | game / pokemon (TASK-33)                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Summary

The Pokémon long-play runner stood on Victory Road's approach for five minutes with no progress
(stall reason `no_progress`, milestone `earth_badge`). The saved trace shows it moving between
map 62 (an 8 x 8 house) and map 3 (the outdoor map that holds the house) with no new event.

## Evidence

- Stall report `stall_latest_20261018-230003.json` (host-clone-1, read-only): last events
  `blocked_by` at (27,12) toward (27,11) on map 3, then the stall on map 62 at (2,7). Stall state:
  `maps: [62, 3]`, `spot: [62, [2, 7]]`.
- Saved world: map 62 has three warps. (2,7) and (3,7) lead to map 3 warp 0 (landing (27,11)).
  (3,0) leads to map 3 warp 7 (landing (27,9)). Map 3's parts put both landings in part 0.
- Memory `lost` is `[15, 118]`, so no "no route" branch ran on map 62: a route always existed there.

## Root cause

`World.route` (`shared/src/lib/game/pokemon/world.py`) searches over (map, part) nodes. The first hop
is filtered by `first_hop_ok` (`runner.py` `go_to_map`: reachable from the player, not a dead door,
not a closed exit). The filter is applied to the start node's hops only. A hop out through another map
that lands back in the start part is an ordinary node afterwards, so its hops are not filtered.

Replayed offline from the saved world, with the first hop limited to the house door (27,11) that
the runner came in by: the route is `[(62, warp (27,11)), (3, warp (2,7)), (15, edge west), (99, ...)]`.
That is map 3 to the house, through the house back into map 3's start part, then the west edge the
filter had excluded. On map 62 the route's first hop is the door under the player, (2,7), whose
landing is the same pocket. `go_to_map` then keeps the door under the player (same destination warp
index, `runner.py` twins logic), and `step_off_warp` (`runner.py`) steps out through it. The loop
repeats with no stuck count and no mark on the door, so the stall detector is the only exit.

What is not verified: the saved state does not include the walk grid at the moment of the stall, so
the exact first-hop filter that was active on map 3 cannot be reconstructed. The loop shown above is
the logic error; whether it was the only thing holding the runner is a live question.

## Fix

`World.route` no longer re-enters the start node through another map: the start map at the player's
part (or at an unknown part, as before) is a dead end for a route that started elsewhere. The
existing rule for an unknown part is kept and widened to the known part.

## Test

`tests/shared/test_pokemon.py::test_a_route_does_not_leave_the_start_part_and_come_back_past_its_first_hop_filter`.
Map 3 (start part 0) has the house warp and a west edge to map 15 (part 0); the house's other door
lands back in map 3 part 0.

- Unfiltered route to an unknown map: `[15, 99]` (before and after).
- Route with the first hop limited to the house door: before the fix `[62, 3, 15, 99]`; after the fix `None`.

Before/after was checked by replaying `World.route` from the original `origin/main` file and the
fixed file on the same data. `python3 -m pytest tests/shared/test_pokemon.py -q`: 122 passed.

## Verification

Live: the next long-play run from Victory Road's approach should not show `maps: [62, 3]` in the stall
state. Not verified live. A live run is needed to confirm the runner gets past the house and out of
the no-route path (`lost` event, then `unvisited_door` / `retreat`), which this fix does not change.
