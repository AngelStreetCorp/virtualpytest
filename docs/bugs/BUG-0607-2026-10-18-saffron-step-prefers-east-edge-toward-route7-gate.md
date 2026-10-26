# BUG-0607 — `saffron_step` picked the saffron-edge closest by Manhattan distance, walking the runner into PATH_ROUTE7 / PATH_ROUTE8 and back to Celadon instead of east into Saffron

## Summary

Post-deploy to host-clone-1 (version `main-2026.10.17-88517`, BUG-0589 + BUG-0594 + BUG-0595 +
BUG-0596 + BUG-0597 fixed), the saffron scheduler on host-clone-1 successfully crossed Celadon east
onto Route 7 — but immediately walked **south** into PATH_ROUTE7 (0x4D) instead of east into
ROUTE7_GATE (0x4C). The runner then took a 5-map detour through PATH_ROUTE7 → Route 8 west →
PATH_ROUTE8 → Route 7 east → ROUTE7_GATE and ended up back on Celadon's east side at `(48, 11)`
(host run 20261017-194505: `lost: [77, 18]` = PATH_ROUTE7 (0x4D = 77) at y=18, then re-entry to
Celadon at `(48, 11)`). Without a fix, the saffron milestone stalls in an infinite loop every run.

The previous `saffron_step` logic was: "pick the saffron-edge closest to the runner by Manhattan
distance". On Route 7 (0x12) at position `(0, 3)` — the west edge where Celadon's east exit lands
the runner (host run 20261017-174506) — the south-edge strip `x in [0, 10)` to PATH_ROUTE7 was
closer than the east-edge strip `y in [10, 11)` at `x=29` to ROUTE7_GATE. The runner walked south
into PATH_ROUTE7 instead of east toward Saffron.

## Why this regression appeared

`overworld_tick`'s `go_to_map` A* routed the runner onto Route 7 east (BUG-0596 made the saffron
guide's first hop CELADON → ROUTE7 work). But once on Route 7, the runner still had to pick the
NEXT hop. The saffron milestone's guide is `[..., CELADON, ROUTE7, SAFFRON]` — the saffron-edge
picked on Route 7 is the "first hop" the rest of the journey starts from. Two saffron-area dests
are reachable from Route 7:

  - east → ROUTE7_GATE (0x4C): 1 hop to SAFFRON.
  - south → PATH_ROUTE7 (0x4D): 5 hops to SAFFRON (PATH_ROUTE7 → Route 8 west → PATH_ROUTE8 →
    Route 7 east → ROUTE7_GATE → SAFFRON).

The closest-by-Manhattan heuristic picks the south edge (PATH_ROUTE7) because the runner lands at
the west edge `(0, 3)` — closer to `x in [0, 10), y = 19` (the south-edge strip) than to
`x = 29, y in [10, 11)` (the east-edge strip). The runner walks south into the underground tunnel
and gets routed through PATH_ROUTE7 → Route 8 west → PATH_ROUTE8 → Route 7 east → ROUTE7_GATE,
back into Saffron from the wrong side. The host run confirms this is exactly what happened.

## Local repro (2026-10-18)

- The runner is on Route 7 (0x12) at `(0, 3)`, saffron milestone active, drink in bag.
- `info = {"spans": {"east": [10, 11], "south": [0, 10]}, "edges": {"east": 0x4C, "south": 0x4D}}`.
- The runner's part includes both the east and south saffron-edge squares.

Without the fix: `saffron_step` returns `walk(min(saffron_edges, key=manhattan))` — the south edge
wins because `(0, 19)` is 16 squares away vs `(29, 10)` at 36 squares. The runner walks south.

With the fix: `saffron_step` first groups saffron-edges by destination, then filters to the dest
with the minimum hop-distance to SAFFRON. ROUTE7_GATE (1 hop) wins over PATH_ROUTE7 (5 hops). The
runner walks east to `(29, 10)` and crosses onto ROUTE7_GATE on the next observe.

## Fix

In `saffron_step` (file `shared/src/lib/game/pokemon/runner.py`, around line 800), group
saffron-edge squares by destination map (`saffron_edges_by_dest: Dict[int, List[Tuple]]`). When
the runner is on a saffron-area map OTHER than Celadon, filter the saffron-edges to those whose
destination has the minimum hop-distance to SAFFRON:

```python
if here != CELADON and saffron_edges_by_dest:
    world = getattr(self, "world", None)
    if world is not None and hasattr(world, "route"):
        def dist_to_saffron(d: int) -> int:
            if d == SAFFRON:
                return 0
            r = world.route(d, SAFFRON)
            return len(r) if r else 10 ** 6   # unknown route: treat as far
        best_dist = min(dist_to_saffron(d) for d in saffron_edges_by_dest)
        saffron_edges = [sq for d, sqs in saffron_edges_by_dest.items()
                         if dist_to_saffron(d) == best_dist for sq in sqs]
    else:
        saffron_edges = [sq for sqs in saffron_edges_by_dest.values() for sq in sqs]
else:
    saffron_edges = [sq for sqs in saffron_edges_by_dest.values() for sq in sqs]
```

The Celadon case is unchanged: on Celadon the runner might be in the wrong partition (BUG-0589/
0596) and must walk to ANY saffron-edge to satisfy `first_hop_ok` — the BUG-0589/0596 path is
preserved. The hop-distance filter only fires once the runner is past Celadon, when the saffron
commitment is locked in.

A small `SAFFRON` constant import is added to the existing milestones import line so the function
can name the goal map (`from .milestones import (..., CELADON, SAFFRON)`).

## Why `world.route` rather than a fixed allow-list

The bug only needs "the edge leading to ROUTE7_GATE" on Route 7, but the same logic also helps on
PATH_ROUTE8 (0x50), PATH_WEST_EAST (0x79), PATH_ROUTE7 (0x4D), etc. — any saffron-area map the
runner might cross into where multiple saffron-edge dests exist. Computing hop-distance to SAFFRON
generalises: ROUTE7_GATE (1 hop) wins on Route 7; PATH_WEST_EAST (1 hop) wins on PATH_ROUTE8 if
both north and east are saffron-edges.

When the world graph doesn't yet know a route (the runner has not visited SAFFRON itself yet),
`world.route` returns `None`; we treat that as "distance 10⁶" so the filter never accidentally
picks an unknown route over a known shorter one. If ALL routes are unknown, all dests are at 10⁶
and the runner falls back to closest-by-Manhattan (BUG-0589/0596 behaviour).

## Tests

Three new tests in `tests/shared/test_pokemon.py`:

- `test_saffron_step_on_route_7_prefers_east_edge_over_south_edge` — runner at `(0, 3)` on Route 7
  with east edge to ROUTE7_GATE and south edge to PATH_ROUTE7. Asserts `saffron_step` walks to
  `(29, 10)` (east, 1 hop to SAFFRON) not `(0, 19)` (south, 5 hops). Uses `_SaffronWorld` to give
  the runner a world graph that knows the saffron-area hop distances.
- `test_saffron_step_on_path_route_8_walks_north_not_south` — runner on PATH_ROUTE8 (0x50) with
  north → Route 7, south → Route 8 (not in saffron_maps), east → PATH_WEST_EAST. The south edge
  is filtered by the saffron_maps tuple; BUG-0607 then picks east (PATH_WEST_EAST, 1 hop to
  SAFFRON) over north (Route 7, 2 hops). Demonstrates the hop filter is non-trivial even when the
  Route 8 south edge is already excluded.
- `test_saffron_step_on_celadon_uses_part_logic_not_hop_filter` — runner on Celadon with a world
  that returns None for every route. The hop filter is bypassed (the existing BUG-0589/0596 logic
  takes over) and the runner walks to the saffron-edge by Manhattan distance. Confirms the
  Celadon path is unchanged.

All 109 pre-existing tests still pass; with the 3 new tests, `python3 -m pytest
tests/shared/test_pokemon.py` reports **112/112 passed**.

## Deploy

1. Local: commit on the `pokemon-bug-0598-saffron-routing` branch (commit hash in the handover).
2. **DO NOT push, DO NOT merge**: report the commit hash back to the parent session so the
   deploy step (CLAIM lease, `update_core.sh`, scheduler resume) is decided by the parent.
3. Expected next host run: the runner crosses Celadon east, lands on Route 7, walks east into
   ROUTE7_GATE (1 hop to SAFFRON), talks to the gate guard, and the saffron predicate fires
   (`map == SAFFRON`). Memo should advance `done` from `["…", "strength"]` to include `saffron`
   and the next milestone `seafoam` becomes active.