# BUG-0629 — Pokemon saffron runner loops Celadon → Route 7 → Underground Path → Route 8 → Celadon while no route to Saffron is known

## Summary

Host run `20261018-143002` (host-clone-1, after BUG-0607 deployed) ended on `milestone=saffron` with
25 milestones done, `drink_bought=true`, and 23 `kind=guide_skip` events over 1986 s, all on Celadon
(map 6) at roughly 85-second intervals. The handover read the events as "runner pinned on Celadon,
no walk, no entry". That reading is wrong: `walk` and map changes are not logged as events, and the
host's stall trace shows the runner completing a loop through the Underground Path (maps 19, 80, 121,
77, 18, 6) on every lap. Each lap returns to Celadon and the drink-detour skip fires again.

The loop is caused by BUG-0607's hop-distance filter. It cannot rank saffron-edges while SAFFRON is
not yet in the world graph (`world.route(d, SAFFRON)` returns `None` for every destination). With every
distance tied at "unknown", the tie-break is Manhattan distance, and from Route 7's west entry the
south edge into PATH_ROUTE7 (0x4D) is closer than the east edge into ROUTE7_GATE (0x4C).

## Evidence

Read-only from `host-clone-1`, `/var/lib/vpt-private/pokemon/`. Copy kept outside the repo at
`~/vpt-private/pokemon/bug0608/memory_latest.json` (mode 600, not committed).

- `runs/20261018-143002.json`: `summary` = `start_milestone: saffron`, `end_milestone: saffron`,
  `badges: 5`, `leader: FLORIZARRE L49`. `events` = 1 `strategy` + 23 `guide_skip`, every one
  `from_: 9, to: 11, map: 6`. Interval between events is about 82–90 s.
- `memory_latest.json` memo: `guide_i: 7`, `drink_bought: true`, `entry: {from: 6, side: east,
  exit: [49, 11], map: 18, landing: [0, 3]}`, `lost: [77, 18]`, `bad_warps` includes `[6, 39, 19]`.
- `memo.stall.maps` is the set of maps first seen since the last milestone progress (append-only,
  so it shows first-visit order, not a full trace): `..., 4, 19, 80, 121, 77, 18, 6, 122, ...`.
  That is Route 8 (0x13 = 19) → PATH_ROUTE8 (0x50 = 80) → PATH_WEST_EAST (0x79 = 121) →
  PATH_ROUTE7 (0x4D = 77) → Route 7 (0x12 = 18) → Celadon (6).
- `memo.stall.spot` at save = `[80, [3, 7]]`: the runner was on PATH_ROUTE8 when the run ended, not on Celadon.
- The world graph has SAFFRON (0x0A) and ROUTE7_GATE (0x4C) absent (handover, same snapshot).

## Root cause

`shared/src/lib/game/pokemon/runner.py`, `saffron_step`, the `dist_to_saffron` helper (was lines
816–820). When the runner is on a saffron-area map other than Celadon, BUG-0607 keeps only the
saffron-edges whose destination is closest to SAFFRON by hop count. The helper returned `10 ** 6` for
any destination whose route is unknown. Before the runner has ever been in Saffron, that is every
destination, so the filter keeps all of them and the code falls through to the Manhattan-nearest edge.

On Route 7 entered at `(0, 3)`, the nearest saffron-edge is the south strip into PATH_ROUTE7
(about 16 squares) rather than the east strip into ROUTE7_GATE (about 36 squares). The runner
therefore goes through the Underground Path and Route 8 and comes back to Celadon. Each return to
Celadon hits `overworld_tick`'s GUIDE update: Route 8 is index 7 of the saffron guide, so `GUIDE`
regresses to 7 there. The next Celadon observe moves it forward to 9, and `_saffron_skip_drink_detour`
logs `guide_skip 9 → 11`. That accounts for the 9 → 11 event and the roughly 85 s period.

The earlier BUG-0607 tests missed this because `_SaffronWorld` always knows the hop distances. The real
`World` does not know them until the runner reaches Saffron.

## Fix

In `dist_to_saffron`, an unknown route no longer counts as far for `ROUTE7_GATE`. The gate is the
single edge that leads to Saffron from Route 7's east end, so when no route is known it is treated as
1 hop. Every other unknown destination stays at `10 ** 6`, and known routes are unchanged. Celadon's
partition logic (BUG-0589/0596/0597) is not touched, and `saffron_step` runs only for the saffron
milestone, so no other milestone changes behaviour.

## Test

`tests/shared/test_pokemon.py::test_saffron_step_on_route_7_takes_the_gate_while_saffron_is_unknown`.
A `_NoRouteWorld` (every `route()` returns `None`) on Route 7 at `(0, 3)`, with an east edge to
ROUTE7_GATE and a south edge to PATH_ROUTE7. Asserts `saffron_step` walks to `(29, 10)`. Before the
fix the walk goes to the south edge `(0, 19)` (Manhattan 16 against 36 for the east edge), so the
test fails. After the fix it passes.

## Not verified

- No live emulator run. The loop is inferred from the host's run file and memo, and the offline test
  reproduces only the target choice, not the full A* and crossing.
- After the fix the runner walks to `(29, 10)` and then `go_to_map(ROUTE7 → SAFFRON)` picks the next
  hop. With SAFFRON unknown that is `explore` over the saffron area, and it could still choose the
  south edge from the east strip. Confirm on host-clone-1 that the run reaches ROUTE7_GATE (76) and
  then SAFFRON (10).
- PATH_ROUTE8 and PATH_ROUTE7 still choose by Manhattan distance while no route is known. This fix
  does not cover loops that start there.
