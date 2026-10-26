# BUG-0534 — Pokémon Blue long play sat on the Lift Key for nine days

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0534                                                     |
| Reported  | 2026-10-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | game / pokemon runner                                        |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The `pokemon-long-play-jev` deployment on host-clone-1 ended every run with "no progress in this run" from 5 Oct. The runner stood on Rocket Hideout B4F at (10, 3), pressing up + A, and nobody was told.

## Root cause

`Runner.fetch_lift_key` talked to the Rocket next to the key ball at most `BLOCKER_TALKS_MAX` (3) times, counted in `memo["key_guard_talks"]` for good, then switched to the ball. The ball is a sprite hidden (image `0xFF`) until the Rocket's talk reveals it, and `overworld.sprites` drops hidden on-screen sprites. With the counter used up before the ball showed, the runner pressed A on an empty-looking square for ever. Nothing noticed the lack of progress.

## Fix

`fetch_lift_key` follows what is on screen: ball visible → take it, else talk to the Rocket (no cap), else walk there. The new stuck detector (`shared/src/lib/game/pokemon/stall.py`) stops a run that gets nowhere, writes a report, fails the run with `STALLED:` (the existing *Script failing repeatedly* alert) and locks the save until `--clear_stall yes`.

## Verification

Host state and memory (`key_guard_talks = 3`) copied to codebox: the old code stays on (10, 3); the fixed runner takes the key (item `0x4A`) and `lift_key` completes, then the run goes on to `silph_scope`. Unit tests in `tests/shared/test_pokemon.py` (83 pass), including a simulated stall that writes the report and the lock.
