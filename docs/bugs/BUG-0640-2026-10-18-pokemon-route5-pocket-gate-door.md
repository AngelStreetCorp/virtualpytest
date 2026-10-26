# BUG-0640 — Pokémon runner got lost in Route 5's south pocket instead of using the gate house door

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0640                                                     |
| Reported  | 2026-10-18                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | game / pokemon (TASK-33)                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Host run `20261018-211502` (`seafoam` milestone) stalled at Saffron (map 10) (18, 1): `no_progress` for 30 min,
`stall_counters.maps = [16, 10]`. The runner went back and forth between Saffron and Route 5 (map 16).
[BUG-0639](BUG-0639-2026-10-18-saffron-to-seafoam-stall.md) stopped the back-and-forth, but replaying the host save on the
emulator with that fix gave a new stall:

```
{'kind': 'dead_end', 'map': 10, 'came_from': 16, 'exits_dropped': 10}
{'kind': 'exit_blocked', 'map': 16, 'at': [12, 35]}   ... up to [17, 35]
{'kind': 'lost', 'map': 16, 'next': 64, ...}
{"ticks": 1389, "counts": {"walk": 28, "no path": 1, "no route": 1360}, "map": 16, "pos": [17, 35]}
```

## Root cause

Route 5's south strip (part 8) sits between Saffron's north edge and the Route 5 gate house: its one way north is the
door at (10, 33) to map 70, which the runner has never entered, so the world graph has no hops out of it. The route to
the Cerulean Pokémon Center (`prepare()` for `seafoam`) therefore read the pocket as a dead end. Before BUG-0639 it walked
back to Saffron and north again. With BUG-0639 (`runner.py` `go_to_map`, the `entry` check, and the no-route `retreat()`),
it marked the edge exits as bad and ended with no route at all (`lost`). Neither path ever tried the unvisited door.

## Fix

`shared/src/lib/game/pokemon/runner.py`: new `Runner.unvisited_door()`, the one-hop route through a door or edge of the
player's part into a map never visited (`World.explore` over `ANY_MAP`). `go_to_map` takes it (1) before BUG-0639's
dead-end retreat, and (2) when no route to the destination is known, before `retreat()`, a guard talk or `lost`.
Entering the map teaches its links, so the next tick routes normally.

## Verification

- `tests/shared/test_pokemon.py::test_a_pocket_entered_by_an_edge_takes_its_unvisited_door_before_going_back`: fails on
  main (the pocket retreats south), passes with the fix, also once the pocket's exits are already marked bad.
- `python3 -m pytest -q tests/shared/test_pokemon.py`: 119 passed.
- Emulator replay of the host save and memory (`pokemon_play_local.py`, 300 s): see TASK-33-handover.md, 2026-10-18 entry.
