# BUG-0891 — The Pokémon walked at a hop no boulder could reach, so the floor was never left

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0891                                                     |
| Reported  | 2026-10-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | games                                                        |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The `latest` lane of TASK-33 stopped on **Victory Road 1F** (map 108) and locked the save.

* The run `20261024-102539` was written off as `no_progress` after 13 minutes: the corridor boulder of
  the floor was pushed against the wall of the alcove and the refusal was repeated for ever (that one
  is **BUG-0890**).
* The run after BUG-0890 was deployed (`20261024-105855`, 33 minutes) wrote **no stall report at all** —
  and made **no progress either**: 42 wild battles, all fled, and not one new square.
* The next run (`20261024-120941`) crossed the 5-minute no-progress clock and wrote the lock, so the
  dispatcher started **no run at all** and the lane went dark.

## Root cause

**The guide walked at a hop the player cannot walk to.**

The save was left with the corridor boulder wedged at (2, 9): (2, 8) is a wall tile, so the one-wide
corridor to the stairs (1, 1) is sealed and the rock cannot be moved at all. Measured on the canonical
save itself:

* `astar` on the grid the walk uses (the sprites block): **(1, 1) is not reachable** — the boulder is
  what stands in the way; on the layout (the sprites ignored) it is.
* The way **back** is open: the warps (8, 17) and (9, 17) lead to Route 23 and are 8 steps away.
* The world graph still routes to Victory Road 2F **through the stairs**: map 108's warps are
  `[[8, 17, 34, 2], [9, 17, 34, 2], [1, 1, 194, 0]]` and its parts are `{"warp": [0, 0, 0], ...,
  "player": 0}` — the stairs are in the player's own part, so the graph sees a route.

In `shared/src/lib/game/pokemon/runner.py`:

1. `go_to_map` turns the first hop of the route into a walk target and walks it. The walk's A\* finds
   **no path** to the stairs.
2. `walk` falls back to `overworld.toward`, a **greedy step that ignores the walls**: it points into
   the boulder, the game refuses it, and the hop-tile fallback (BUG-0740) steps the player **away**,
   into the grass. The player ping-pongs between (2, 10) and (2, 11) — two squares the detector
   already knows — and the floor is never left.
3. `overworld_tick` only falls back to the waypoint the runner came from when the **world graph** has
   no route. The graph has one (the stairs), so the guide kept asking for Victory Road 2F.

The wild battles are a symptom, not the cause: the grass of the floor meets a battle about every tenth
step (24 battles in the 270 steps of a local replay), the flee is quick and costs neither HP nor PP,
and the player does advance one square per step — the ping-pong is what keeps it on the two squares it
already knows. The stall detector did not see it either: `progress_s` counts the seconds of the
**overworld** ticks only, and the battle ticks — 80 % of the run — are excluded.

## Fix

* `Runner.boulder_on_the_way()`: the boulder that stands on the layout path between the player and the
  target — the rock that makes a hop unwalkable.
* `Runner.hop_blocked()` / `mark_hop_blocked()`: a hop the player cannot walk to is remembered
  (`memo["hop_blocked"]`) and reported (`hop_blocked` event).
* `go_to_map`: **a hop that is unwalkable is no route**.
* `overworld_tick`: the guide goes back to the waypoint it came from when the hop to the next waypoint
  is sealed — the fallback BUG-0880 built for a waypoint the graph cannot reach. The player walks out
  of the floor, **the game puts the boulders of the floor back where they were** (the chain boulder
  returns to (5, 15), the corridor boulder to (2, 10)), the runner comes back in and the floor's plan
  runs on a floor that can be solved.
* The marking is dropped when the player moves to another map, like `push_refused` (BUG-0890).

## Verification

* `python3 -m pytest -q tests/shared/test_pokemon.py` → **197 passed** (194 before, three new guards:
  a boulder that seals the way makes the hop unwalkable, a sealed hop sends the runner back to the
  waypoint it came from, the marking is forgotten on the next floor).
* A local replay of the stalled save with the fix: the runner leaves the floor (see the handover of
  TASK-33 for the run on the hosts).
