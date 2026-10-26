# BUG-0870 — The egg overlay missed a quarter of the eggs because the wrong model was looking at the belt

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0870                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend / monitoring                                         |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

On the device3 egg line, the overlay circled **75 %** of the eggs in the picture and the number of circles did not match
the number of eggs on the belt. The ones it did circle were on the right eggs, with the right shape; the ones it missed
were in the crowded bands, where the eggs touch each other.

Measured on one fixed frame (1280x720), against a ground truth of 147 eggs built **without** the model under test:

| detector | eggs circled | circles on an egg | forwards | s/frame |
|---|---|---|---|---|
| `egg_quality_yolo` (the shipped one) | 78.2 % | 99.2 % | 12 | 12.4 |
| `egg_quality_yolo_belt` (this fix) | **98.6 %** | 97.4 % | **1** | **0.36** |

## Root cause

The detector was the wrong model for the scene, and it was the wrong model in a way that cost both accuracy and speed.

`egg_quality_yolo` runs a third-party YOLOv8s **segmentation** model trained on the public Roboflow `egg-seg-1` set. That
dataset is eggs photographed close up on warm rods in daylight; the device3 feed is a landscape shot of small white eggs on a
saturated blue belt. The gap was partly closed with preprocessing (BUG-0858: `whitebalance`, `unsharp`, `flip_tta`), and the
result was 75-78 %.

The remaining gap was **not** a threshold, a tile size or a zoom. It was the training domain. Somebody else has trained a
detector on a conveyor belt of white eggs — `Moein-Talebi/egg-detection-tracking`, file `model/best.pt`, a YOLOv8n
**detection** model with one class, `egg` — and it covers **98.6 %** of the same ground truth.

Two things followed from that model being a *detect* model rather than a *segmentation* model:

- **No mask branch, so no slicing.** The shipped profile had to cut the frame into twelve 640x640 tiles because a single
  640x640 input cannot hold 200 eggs at a size the head will commit to. The belt model is happy with the whole frame at
  960x960: **one forward, 0.36 s**, against twelve forwards and 12.4 s.
- **A different head shape.** A segmentation head is `4 + classes + 32 mask coefficients`; a detection head is
  `4 + classes`. The profile must declare the class count, which the analyzer already does from `classes`.

The accuracy number was only worth something because the ground truth was built **without** the belt model: the union of
four other detectors, merged, filtered to the boxes on a white egg, and then canonicalised to **one box per distinct egg**.
The raw pool counted 18 pairs of the same egg twice, and a denominator that counts an egg twice flatters whoever is being
measured.

## Fix

A third profile, `backend_host/config/monitor/profiles/egg_quality_yolo_belt.yaml`, running the belt model:

- `model_env: MONITOR_YOLO_BELT_MODEL` — a **separate key** from `MONITOR_YOLO_MODEL`, because the two models have different
  heads and the two profiles declare different class counts. One key cannot serve both.
- `input_size: 960`, `fill: letterbox` (measured best: 640 → 98.0 %, 1280 → 97.3 %, **stretch** → 94.5 %), `min_conf: 0.02`
  (the head's scores are already activated, so this is a real 2 % confidence), `nms_iou: 0.60`, `dedupe_dist: 0.35`
  (duplicate pairs: 0 → 49, 0.25 → 18, 0.30 → 6, 0.35 → 1), `min_side: 8`.
- **No `tile`** — one whole-frame pass — and **no `color_filter`**: the model was trained on this kind of belt and its
  boxes are already on eggs, so the belt filter would only throw away real ones.
- `sample_hz: 0.5` and the vote window back to `votes: 3 / min_votes: 2`, which the sliced profile could never reach (an egg
  crossed the belt between two of its passes, so every egg came out `unverified` — measured, 191 of 191).

The model file is **not in git**: the operator fetches `model/best.pt` from the public GitHub repository, checks its
SHA-256 (`c219a234ad9a6ebaf64fed76331e596376f420ee3ee58dc5061769e1113b7767`), exports it to ONNX and puts it on the host
at `/var/lib/vpt_user/models/egg_belt.onnx`. The repository carries no licence file, so the weights are not redistributed
here. The install steps are in `docs/agent/devices/MONITOR_PROFILES.md`, section "Model files (never in git)".

The analyzer itself needed no change: it already reads the class count from the profile when the graph has no mask
prototypes to tell classes from mask coefficients, and it already draws an ellipse fitted to the box.

## Verification

- `tests/backend_host/test_egg_quality_belt_profile.py` — the manifest passes both validators (the shared light one and
  the img service's pydantic one), reads its own model key, and pins every knob the measurement was made with, so the
  numbers in the profile's comment block cannot rot silently. 8 tests.
- `tests/backend_host/test_yolo_seg_detect.py`, `tests/backend_host/test_egg_quality.py`,
  `tests/backend_host/test_monitor_profiles.py` — 109 passed, 1 skipped, no regression.
- End to end on the fixed frame, through the shipped YAML and the shipped decoder (not a script): **194 circles, 98.6 %**
  of the 147-egg independent ground truth, 97.4 % of them on a white egg, 1 duplicated pair, **0.36 s** a frame.
- The four circles that sit on no egg are four eggs the ground truth itself missed (a blurred cluster in the far top-left
  corner), not false positives.
- Live on `vpt-lenovo1`: the profile runs, the frame the overlay is locked to is the frame the boxes were drawn on, and
  the circles sit on the eggs.

**What this does not change: the good/bad grade.** `egg_classify` grades crops of white eggs on a blue belt in daylight,
where the image carries no evidence of interior quality, so it reports ~99 % bad because that is what the model says. The
counters are kept because they are part of the block. A real grade needs candling (the egg against a light).
