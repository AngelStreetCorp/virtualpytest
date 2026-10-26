# BUG-0632 — Pokemon saffron runner cycles Celadon → Route 7 → PATH_ROUTE7 → Route 8 → underground instead of entering the Route 7 gate

Numbering: BUG-0630 and BUG-0631 are taken on main (LoL launcher, Windows/stream tiles), so this fix is BUG-0632.

## Summary

Host run `20261018-160003` (host-clone-1, build `main-2026.10.18-88706`, which already contains BUG-0629)
ended on `milestone=saffron` with 25 milestones done, `drink_bought=true`, 22 `guide_skip` events over
1987 s and no milestone change. The saved memo shows the runner cycling Celadon (6) → Route 7 (18) →
PATH_ROUTE7 (77) → Route 8 (19) → PATH_ROUTE8 (80) → underground (121, 122–126) and back, and never
entering ROUTE7_GATE (76) or SAFFRON (10). The run ended on PATH_ROUTE7 at (3, 7).

## Evidence

Read-only from `host-clone-1`, `/var/lib/vpt-private/pokemon/memory_latest.json`, copied to
`~/vpt-private/pokemon/bug0630/memory_latest.json` (mode 600, outside the repo, not committed).

- `memo.guide_i = 12` on the saffron guide `[..., ROUTE7 (8), CELADON (9), MART_ROOF (10), CELADON (11),
  ROUTE7 (12), SAFFRON (13)]`. On Route 7 the next map is therefore SAFFRON.
- `world['18']` (Route 7) has `edges = {west: 6, east: 10}`. There is no south edge. PATH_ROUTE7 is reached by
  the warp `(5, 13) → 77`. The east connection goes to SAFFRON (10), not to ROUTE7_GATE (76). The gate house
  is entered by warps: west door `(11, 9)` and `(11, 10)` (part 0, the runner's west part), east door `(18, 9)`
  and `(18, 10)` (part 1).
- `world` has no key `76` and no key `10`: the runner has never entered the gate or Saffron.
- `memo.exploring = 76`: the last explore target was ROUTE7_GATE, but `explore` only runs when no route is
  known.
- Offline, with the saved world and the runner's player part 0 on Route 7, `World.route(18, 10)` returns a
  16-hop route whose first hop is `(77, ('warp', (5, 13)))`. `World.route(18, 76)` returns `[(76, ('warp', (11, 9)))]`.

## Root cause

Two decisions, both on the path from Route 7 to SAFFRON:

1. `saffron_step` (`shared/src/lib/game/pokemon/runner.py`, `saffron_maps` at line 797 and the saffron-edge list after it) returns
   `None` on Route 7. Its whitelist `saffron_maps` does not contain SAFFRON (0x0A), so Route 7's east edge
   (dest 10) is not a saffron-edge, and the west edge (dest 6) is not one either. The list is empty and no
   walk is produced. The gate, the only way in, is a warp, not an edge.
2. `go_to_map` → `find_route` (`runner.py` line 1334 onward): with `dest = SAFFRON`, the code calls
   `self.world.route(here, dest, ...)` first. SAFFRON is not a key of `world.maps`, but the BFS accepts any known
   link into it (Route 5's south edge leads to it in the saved world). The shortest known route from Route 7's
   west part is therefore the 16-hop route whose first hop is the warp `(5, 13)` to PATH_ROUTE7, then Route 8 and
   the underground. `explore(ms.area)`, which would have picked ROUTE7_GATE (`76`, one hop through `(11, 9)`), only runs
   when that route is `None`. It never runs.

The BUG-0607 hop filter and the BUG-0629 gate rule cannot help here. Both only act on saffron-edges, and the
gate is not one.

## Fix

In `saffron_step`, after the saffron-edge list is built and before the walk to a saffron-edge: when the runner
is on a saffron-area map (`saffron_maps`), the list is empty, ROUTE7_GATE has not been learned, and the world
has a route to it, return `go_to_map(here, ROUTE7_GATE, info)`. The gate is then the goal of the trip, so
`go_to_map`'s route to it (warp `(11, 9)` from the west part) wins over the known loop to SAFFRON. Once the gate
is learned, the branch no longer fires and the route search can use the gate's own links.

The branch is scoped to `saffron_maps` and to the saffron milestone (`saffron_step` runs only there). Celadon
is not in `saffron_maps`, so the BUG-0589/0596 partition logic is unchanged. When no route to the gate is
known the branch does not fire and the existing behaviour remains.

## Test

`tests/shared/test_pokemon.py::test_saffron_step_on_route_7_walks_to_the_gate_door_while_the_gate_is_unvisited`
uses the Route 7 and PATH_ROUTE7 entries of the saved world (only the maps the decision reads). On Route 7 at
`(0, 3)` with the gate unvisited, `saffron_step` must return `"walk"` toward `(11, 9)`.

- Before the fix (`git show origin/main:shared/src/lib/game/pokemon/runner.py`): `saffron_step` returns `None`,
  assertion `None == 'walk'` fails.
- After the fix: passes. `tests/shared/test_pokemon.py` reports 114 passed (113 before, plus this one).

## Not verified

- No live emulator run. The offline replay uses the saved world and a fake grid (all walkable, runner in
  part 0). It shows the decision, not the crossing into the gate or the guard's answer.
- The known 16-hop route to SAFFRON through Route 5 is not tested beyond the replay. `milestones.py` notes that
  Route 5's gate to Saffron is guarded, so that route may not be usable at all. The fix does not change how the
  route search ranks it once the gate is learned.
- On PATH_ROUTE7 the replay stood on the warp `(3, 7)` and returned an exit-mat step, not a walk to the gate
  door. That is the existing warp-exit path. Confirm on host-clone-1 that the run leaves PATH_ROUTE7, reaches
  ROUTE7_GATE (76) and then SAFFRON (10).
- Other milestones are not affected: the branch only runs inside `saffron_step`, which only runs for the
  saffron milestone.
