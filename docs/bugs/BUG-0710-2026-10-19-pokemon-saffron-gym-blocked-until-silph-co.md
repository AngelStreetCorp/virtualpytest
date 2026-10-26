# BUG-0710 — Pokémon runner circles Route 6's gate: Saffron's gym is blocked until Silph Co. is freed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0710                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon runner (TASK-33)                              |
| Fixed in  | build 90145 |
| Commit    | see the merge `pokemon-route6-gate`                          |

---

## Symptom

Run `20261019-213934` (host-clone-1) stalled `no_progress` on `marsh_badge` on Route 6 (17) at (10, 1): for 5 min the
runner went `walk_target 17 (10,0) -> (10,1)` into Route 6's gate (73), `73 (2,0) -> (3,0)` out of its north door and
`17 (3,0) -> (3,-1) north` again.

## Root cause

Two things in `shared/src/lib/game/pokemon/milestones.py` (`marsh_badge`, added by BUG-0708):

1. Rocket grunts stand on the squares below Saffron's doors until Giovanni is beaten on Silph Co. 11F. The memo had
   learned them as walls: (7, 6), (34, 4) below the gym door (34, 3), and (13, 12). The story had no Silph Co. step, so
   the gym could not be reached and Saffron was a dead end (`dead_end 10`, `exit_blocked`).
2. The guide went `ROUTE6, ROUTE6_GATE, SAFFRON`, but the gate stands inside Route 6: its north door lands on Route 6's
   north strip, and the edge to Saffron belongs to Route 6. Back on that strip, the guide pointer fell back to Route 6,
   whose next map was the gate again. `earth_badge` had the same leg in reverse.

## Fix

A new `silph_co` milestone before `marsh_badge`: Route 6, Saffron, then Silph Co. 1F to 11F by the stairs. The map ids
come from the ROM's map header table: 0xB5, 0xCF-0xD5, 0xE9-0xEB. It is done when the president's Master Ball is in the
bag. `marsh_badge` now starts on 11F and goes down to Saffron's gym. Route 6's gate is an `area` map of `silph_co` and
`earth_badge`, no longer a guide map. Guard test: `test_route6_gate_is_no_guide_map_and_silph_co_comes_before_sabrina`.

## Verification

`tests/shared/test_pokemon.py` passes (150). Local replay of the stalled save, 240 s: Route 6, a heal in Vermilion,
Saffron, Silph Co. 1F, then every floor by the stairs up to 11F (0xEB). It stood at (7, 2) there with the milestone still
open. **Next expected stall:** Giovanni's room on 11F is behind a Card Key door (the Card Key is on 5F) or the 7F
teleporter.
