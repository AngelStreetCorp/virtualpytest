# BUG-0915 — The egg counter counted the same egg several times

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0915                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | backend / monitoring                                         |
| Fixed in  | build 90145 |
| Commit    | `470bebfb6`                                                  |

---

## Symptom

The egg panel read **1 740 Eggs** for a two-minute window with ~180 eggs on screen. Replayed offline on 72 s of real
captures, the profile counted **1 253 "distinct eggs"**, and fewer seconds of `max_gap_s` made it worse (1 711 at 2 s,
2 157 at 1 s).

## Root cause

`egg_seen` fired once per **track**. The eggs move 8-22 px a sample at 5 Hz (all belts left to right), and about one egg
in twelve has no detection within half a diameter in the next frame. Each such miss can end a track and start a new
one on the same egg, so one egg became several tracks and several events. A long `max_gap_s` (30 s) did not save it —
the dead track's predicted position drifts away — and kept ~700 dead tracks for the tracker to match against.

## Fix

A profile can count at a line: `track.count_line_x` (a fraction of the frame width) and `count_dir` (`right` | `left`).
An object is counted once, when its centre crosses that line in the direction of travel (`pipeline.py`); a track that
broke before the line is counted by the piece that crosses it, a piece born after the line is not counted. Both
validators accept the two keys. `egg_count_yolo_belt_fast` counts at x = 0.5, `max_gap_s: 3`.

## Verification

Reference: the 960 model on all 300 frames of one 30 s pass of the device3 clip at 10 fps (an egg moves 4-11 px a frame).

| setup | eggs across x = 0.5 |
|---|---|
| 960 @ 10 fps (reference) | 380 |
| 640x352 @ 10 fps | 388 (102 %) |
| 640x352 @ 5 fps (the profile) | 369 (97 %) |
| 640x352 @ 5 fps, line at x = 0.7 | 352 (93 %) |

The count at the line does not depend on `max_gap_s` (885 at 30 s, 882 at 3 s on the 72 s clip), and 3 s halves the
tracker (51 → 22 ms a frame). Live on `vpt-lenovo1` at 4.8 analyses/s: 1 072 eggs in 90 s = **357 per pass (94 % of the
reference)** — the live window also crosses the clip's 30 s loop and the 2-minute counter reset, which a continuous belt
does not have. The reference is a stronger model, not a hand count. Tests: `tests/backend_host/test_counting_cars.py`
(counted at the line, nothing born past it; a track broken before the line counted once).
