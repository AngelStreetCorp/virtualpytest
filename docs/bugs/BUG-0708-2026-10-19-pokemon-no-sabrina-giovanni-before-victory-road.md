# BUG-0708 — Pokémon runner lost in Blaine's gym: no Sabrina or Giovanni milestone before Victory Road

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0708                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon runner (TASK-33)                              |
| Fixed in  | build 90145 |
| Commit    | see the merge `pokemon-earth-route`                          |

---

## Symptom

Run `20261019-212631` (host-clone-1) marked `volcano_badge` done (6 badges) in Cinnabar Gym (166) and started
`earth_badge`. It walked to each of Blaine's nine quiz machines (`npc_walled guard`, 3 talks each), logged `lost` toward
the Hall of Fame (118) and stood 300 ticks on (16, 14): `same_spot`.

## Root cause

`shared/src/lib/game/pokemon/milestones.py`: `earth_badge` was the Hall of Fame goal, with a guide starting on Victory
Road 1F, which no route reaches from Cinnabar. The story also had no Sabrina and no Giovanni milestone: Route 23's guards
want every badge up to the Earth Badge and Giovanni's gym opens on 7 badges, so Victory Road was out of reach anyway.

## Fix

Three milestones after `volcano_badge`: `marsh_badge` (back by Route 21, Pallet, Diglett's Cave, Vermilion and Route 6's
gate to the Saffron Gym; Marsh bit 0x20), `earth_badge` (the Viridian Gym; Earth bit 0x80) and `hall_of_fame` (the old
goal, its guide now starting at the Viridian Gym by Route 22, its gate and Route 23). Guard test:
`test_sabrina_and_giovanni_come_before_victory_road`.

## Verification

`tests/shared/test_pokemon.py` passes. Local replay of the stalled save: see TASK-33-handover.md (BUG-0708 entry).
