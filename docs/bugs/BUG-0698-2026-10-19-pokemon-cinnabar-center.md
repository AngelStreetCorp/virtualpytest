# BUG-0698 — Pokémon runner walks back to Viridian to heal before the Mansion

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0698                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon (TASK-33)                                     |
| Fixed in  | build 90145 |
| Commit    | see `git log -- shared/src/lib/game/pokemon/runner.py`       |

---

## Symptom

Run `20261019-190740` (host-clone-1) stalled `no_progress` on milestone `secret_key`. From Cinnabar Island it walked Route 21,
Pallet and Route 1 to Viridian's Pokémon Center, healed (`prepared secret_key`), then explored Viridian's houses and its
locked gym for 5 min.

## Root cause

`runner.py` `POKEMON_CENTERS` listed no Center on Cinnabar (0xAB) or Saffron (0xB6). `Runner.prepare` (once per `prepare`
milestone) picks the nearest known Center, so for `secret_key` it was Viridian's. Back in Viridian the way on is back over
Route 1, the edge the player came in by, which the BUG-0639 dead-end check reads as a dead end: it explored instead.

## Fix

`CINNABAR_CENTER` and `SAFFRON_CENTER` are in `POKEMON_CENTERS`. Local replay of the Cinnabar save: healed at Cinnabar's
Center (171), then the Mansion (1F, 3F switch, hole, B1F). Guard test:
`test_prepare_for_the_mansion_heals_at_cinnabar_not_back_in_viridian` in `tests/shared/test_pokemon.py`.
