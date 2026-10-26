# BUG-0707 — Pokémon runner stands by Blaine after winning: the Volcano Badge was counted as the 7th

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0707                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon runner (TASK-33)                              |
| Fixed in  | build 90145 |
| Commit    | see the merge `pokemon-volcano-badge`                        |

---

## Symptom

Run `20261019-210519` (host-clone-1) beat Blaine in Cinnabar Gym (166): `battle_end outcome won` after CANINOS 42, PONYTA 40,
GALOPA 42 and ARCANIN 47. The milestone stayed `volcano_badge`: the runner healed at Cinnabar's Center (171), walked back
into the gym and stood next to Blaine at (2, 3) until `same_spot` (300 ticks).

## Root cause

`volcano_badge` (and `secret_key`) in `shared/src/lib/game/pokemon/milestones.py` were done at `badges(r) >= 7`, a count of
badge bits. The story skips Sabrina (the `saffron` milestone only enters Saffron City), so the save holds Boulder, Cascade,
Thunder, Rainbow, Soul and now Volcano: 6 badges. The count of 7 never came.

## Fix

`has_badge(read, VOLCANO_BADGE)` checks the Volcano bit (0x40) itself. Guard test:
`test_volcano_badge_is_done_on_its_own_bit_without_the_marsh_badge`.

## Verification

Local replay of the stalled save: `milestone_done volcano_badge` with `badges: 6` on the first ticks, next milestone
`earth_badge`. Next expected stall: Route 23's gates want all eight badges (Marsh and Earth are missing: Sabrina and
Giovanni are not milestones yet).
