# BUG-0909 — The egg line can run three times faster on the same box, for one egg of accuracy

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0909                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | backend / monitoring                                         |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The egg line refreshed **29 times a minute** (0.48 analyses/s, median gap 1.81 s) on a host whose detector could do
**1.33 detections a second**. The picture is written 5 frames a second, so the circles were five times older than the
feed. For a demo, a count that updates every two seconds on a belt that is moving is not much of a count.

Raising the sampling period (BUG-0907) did not help: the live rate went from 0.47 to 0.48 analyses/s. The host was never
waiting for permission to look — it was **waiting for CPU**. The host runs three other device profiles and the archive
ffmpeg processes, and its **load average is 8.5 on 4 cores**; the monitor process is scheduled on 1.2 of them.

## Root cause

The belt model is run at **960x960**, and that is where it was measured to be most accurate (98.6 % of the eggs against a
ground truth of 147 eggs built without the model). But a fixed-size input means a **fixed price per pass**: the whole
frame is scaled into a 960x960 square and the detector looks at 921 600 pixels whether the eggs are big or small, and
**2.25x more of them than a 640x640 input has**.

So the question is not "which model" — it is the same weights — but "which input size", and that had never been tried on
the belt model. Two things made it a non-trivial export:

- the input size is **baked into the ONNX graph**, so a 640 model is a separate file, not a knob;
- the export of the 640 model with the ONNX simplifier on is the one **OpenCV 4.14 cannot even load** ("total(srcShape) ==
  maskTotal" in the DFL reshape), while the export without the simplifier loads and runs.

## Fix

A third egg profile, `backend_host/config/monitor/profiles/egg_count_yolo_belt_fast.yaml`, with the **same weights**
exported at **640x640**:

| model | pass on the box | detections/s (idle box) | recall (independent GT) | duplicate pairs |
|---|---|---|---|---|
| 960x960 (`egg_count_yolo_belt`) | 0.65 – 0.75 s | 1.33 | 98.6 % | 1 |
| 640x640 (this profile) | **0.19 – 0.30 s** | **4.2** | **98.0 %** | **0** |

- `model_env: MONITOR_YOLO_BELT_FAST_MODEL` — its own key, because the file is a different export with a different
  input shape. The 960 model cannot be fed a 640 blob (OpenCV refuses it), so the two must not be interchanged.
- `input_size: 640`, `sample_hz: 2.0` — a cycle is ~0.4 s (0.24 s of detection plus ~0.15 s of pipeline).
- `dedupe_dist: 0.40`, not 0.35: at 640 the boxes are smaller and the same egg can be found twice a few pixels apart.
  Measured on the fixed frame: 0.35 leaves **3** duplicated pairs, 0.40 leaves **0** — and no pair of neighbouring eggs
  is merged (the recall does not move: 144 of 147 at either value).
- Still **no grader** (BUG-0906): the count is the honest part, and the picture cannot support a grade.

The file is the opset-12 export without the simplifier: 12 238 666 bytes, sha256
`c54d950787f2e29404553ca534dc57bee0002d234262cdba2e5387a3d04c0036`, from the **same** `model/best.pt` as the 960 profile
(sha256 `c219a234ad9a6ebaf64fed76331e596376f420ee3ee58dc5061769e1113b7767`). The upstream repository carries no licence
file, so the weights are fetched and exported by the operator and are not redistributed in git.

## What it costs

One egg of 147: 98.6 % becomes 98.0 %. Both are far above the 95 % the line was asked for, and the count still counts
what the model **saw** — 3 eggs of 147 are missed at this size.

## Verification

- `tests/backend_host/test_egg_count_belt_profile.py` — the fast profile pins its own model key, its 640 input, its
  `sample_hz` and its `dedupe_dist`, and says the grade needs candling.
- Live on `vpt-lenovo1`: **1.57 analyses/s** (median gap 0.63 s), measured over a 60 s window of the
  frame metadata — against 0.48 analyses/s before the tracker fix (BUG-0910), which was the bigger of
  the two gains.
