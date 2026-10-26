# BUG-0908 — The poster and splash checks named game and video frames, on devices they were never written for

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0908                                                          |
| Reported  | 2026-10-25                                                        |
| Status    | Fixed                                                             |
| Severity  | Medium                                                            |
| Area      | backend_server (auto-classify, screen label worker) / ai          |
| Fixed in  | build 90145 |
| Related   | [TASK-159](../tasks/TASK-159-screen-registry-single-writer.md), [BUG-0849](BUG-0849-2026-10-23-no-menu-poster-rule-named-photos-of-a-wall.md) |

---

## Symptom

The screen registry review of TASK-159 (2026-10-25) found 116 rows on `vpt-pi1/device1` (an Android phone running
Clash of Clans) named `Full-screen poster`, and two rows on `vpt-mf1/device1` (an Apple TV) named `Splash screen` and
`Full-screen poster`. The stored pictures are the game's village and a foggy Golden Gate frame from the Apple TV
screensaver. Six rows of the Samsung TV on `vpt-pi4/device1` were named `Splash screen` the same way.

Because a name is written once and never replaced (TASK-159 G4), every one of these wrong names was permanent.

## Root cause

`auto_classify_unknowns.STATE_HINTS` asks two yes/no questions first: "a full-screen splash?" and "a menu bar?",
`NOMENU` → `Full-screen poster`. Both are written for the operator set-top box ("This is a TV screen", its
full-screen poster, its welcome splash). TASK-159 G6 rightly stopped guessing an interface from the row, and from then
on the checks were asked of **every** unnamed row on **every** device. A game screen has no menu bar, so it answered
`NOMENU`. The hourly `auto-classify.timer` on the server named 51, 48 and 17 rows on 23, 24 and 25 October.
BUG-0849 had added a "screen or photo?" gate to the TASK-162 worker, but a game or a screensaver *is* a screen, so
that gate let them through, and the old hourly job did not have the gate anyway.

## Fix

The state checks are asked only of rows whose device model is in `STATE_HINT_MODELS` (`stb`). The model comes from
the device's latest `system_device_metrics` row (`device_model_of`, cached per run). Every other row goes straight to
open-set naming. Both namers use the same `state_hints_for(row)`: `auto_classify_unknowns.py` and
`screen_label_worker.py`.

The 124 wrongly named rows (`vpt-pi1/device1` 116, `vpt-pi4/device1` 6, `vpt-mf1/device1` 2; never a human name)
were given back a fresh `unknown_N` from the scope counter, with their attempts reset so the fixed job names them
again. The ids and old labels are in `docs/tasks/TASK-159-evidence/bug0908-reset-snapshot-2026-10-25.csv`.

## Tests

`tests/scripts/test_auto_classify_unknowns.py`: `test_state_checks_are_asked_only_of_an_operator_stb`,
`test_a_game_frame_is_never_named_a_poster`, `test_device_model_lookup_reads_the_latest_metrics_row`.
