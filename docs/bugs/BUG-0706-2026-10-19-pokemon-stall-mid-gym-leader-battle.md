# BUG-0706 — Pokémon runner's stall detector stops the run in the middle of Blaine's battle

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0706                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon runner (TASK-33)                              |
| Fixed in  | build 90145 |
| Commit    | see the merge `pokemon-blaine-battle`                        |

---

## Symptom

Run `20261019-205254` (host-clone-1), the run cleared after BUG-0705, answered the quiz and reached Blaine in Cinnabar Gym
(166). It stalled `no_progress` on `volcano_badge` at (3, 4) while still in the battle: the last 30 events are all
`battle_choice` against Blaine's CANINOS 42, PONYTA 40, GALOPA 42 and ARCANIN 47 (118/149 HP when it stopped).

## Root cause

`stall.StallDetector.observe` (`shared/src/lib/game/pokemon/stall.py`) added every tick's game time to `progress_s` unless
the activity was `guarded` (training, Surf hunt). A battle has no new square, map or milestone, so the leader's fight
(about 28 turns, 4.7 min) used up the whole 5-minute budget. Battle ticks were already exempt from `same_spot`, not from
`no_progress`.

## Fix

The first `BATTLE_GRACE_MIN` (15) minutes of one battle (consecutive `battle*` ticks) add nothing to `progress_s`; past
them a wedged fight still counts. Guard test:
`test_stall_detector_does_not_count_a_long_gym_leader_battle_but_counts_a_wedged_one`.

## Verification

`tests/shared/test_pokemon.py` passes. On the host: the cleared run plays the Blaine battle to its end.
