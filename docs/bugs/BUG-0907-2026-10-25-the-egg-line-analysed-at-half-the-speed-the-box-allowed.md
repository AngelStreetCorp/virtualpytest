# BUG-0907 — The egg line analysed at half the speed the box allowed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0907                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed                                                        |
| Severity  | Low                                                          |
| Area      | backend / monitoring                                         |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The egg overlay on `vpt-lenovo1` refreshed **28 times a minute** (0.47 analyses/s, median gap 2.15 s), on a box whose
detector could do **1.33 detections a second**. The circles on the belt were therefore two to three times older than
they needed to be, for no reason: the model was idle more than half of the time.

## Root cause

`egg_quality_yolo_belt` asked for `sample_hz: 0.5`. That number was inherited from the *sliced* profile
(`egg_quality_yolo`), where one pass really did cost 12.4 s and 0.08 Hz was the honest request. The belt profile
replaced twelve 640x640 forwards with **one** 960x960 forward (0.65 – 0.75 s on that host) but kept the sampling
period of the old, slow profile.

The worker takes the **newest** pending frame and analyses it once a period has passed, so the cost of a cycle is
`max(period, analysis time)` and the rate is the smaller of the two limits. At 0.5 Hz the period was 2 s against
~1.0 s of work, so the box spent half its time waiting for permission to look.

## Fix

The sampling period is set from the measured cost of a cycle, not inherited:

| profile | sample_hz | analysis on the box | live rate measured |
|---|---|---|---|
| `egg_quality_yolo_belt` | 0.5 → **1.0** | ~1.0 s (0.75 s detection + 0.25 s grading) | ~0.45 analyses/s |
| `egg_count_yolo_belt` (new, BUG-0906) | **1.2** | ~0.9 s (detection only) | **0.48 analyses/s** (29 updates a minute, median gap 1.81 s) |

Measured on the box (Intel i3-4150T, 4 cores): the belt detection pass is 0.65 – 0.75 s, the same pass through
`onnxruntime` is 0.68 – 0.87 s (no gain, so `cv2.dnn` stays), grading the ~195 crops costs 0.23 – 0.26 s, and the rest
of the pipeline ~0.15 s.

**And the honest part: raising the period alone did not make the box faster.** The live rate barely moved (0.47 →
0.48 analyses/s) because the host was never waiting for permission to look — it was **waiting for CPU**. The host runs
three other device profiles and the archive ffmpegs, and its load average is **8.5 on 4 cores**; the monitor process
itself is scheduled on 1.2 of them. The period was wrong and is fixed, but the lever that actually buys speed on a busy
box is a **smaller input** (BUG-0909).
The capture side writes 5 frames a second, so even 0.48 analyses/s is a tenth of the frames — the circles are a snapshot
of the belt, and the frame-lock (`AnalysedFrameLayer`, BUG-0836) keeps them on the eggs they were measured on.

The numbers are written down where they can be found again: the profiles, §8c of
`docs/agent/devices/MONITOR_PROFILES.md`, and the notes in `monitor_profile.py`.

## Verification

- The profiles load and validate (`load_profile()` + `validate_manifest_light()`).
- Live on `vpt-lenovo1`: the analysis epochs of the frame metadata were measured over a 60 s window before (0.47/s) and
  after (0.48/s) the change — the period was not the binding constraint, which is why BUG-0910 exists. With the tracker
  fixed, the same profiles deliver **0.67 analyses/s** (graded, 960), **0.85** (count only, 960) and **1.57** (count only,
  640) — the period only becomes the limit once the tracker is out of the way, and at 1.2 Hz it is not: the 640 profile
  asks for 2 Hz and reaches 1.57/s.
