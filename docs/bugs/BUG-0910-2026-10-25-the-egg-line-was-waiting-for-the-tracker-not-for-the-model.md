# BUG-0910 — The egg line was waiting for the tracker, not for the model

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0910                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | backend / monitoring                                         |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The egg line refreshed **29 times a minute** (0.48 analyses/s, median gap 1.81 s) on a host whose
detector can do **1.33 detections a second** (960x960) or **4.2** (640x640). Neither a faster model
(BUG-0910) nor a shorter sampling period (BUG-0907) changed the live rate at all: it stayed at 0.47 →
0.48 analyses/s. The model was not the bottleneck, and neither was the period.

## Root cause

The tracker. On the egg line the monitor matches every detection against every live track, and it did
it in **pure Python, one pair at a time**:

- the assignment cost matrix: ~175 detections × ~250-345 live tracks = **43 000-60 000 pairs**, each
  pair calling `_predict()` (velocity + growth) and `iou()`;
- the assignment itself: the pure-Python shortest-augmenting-path Hungarian solver on that matrix,
  ~0.2 s per analysis on the operator's Mac and roughly 4x that on the box;
- two more O(detections × tracks) passes for the recovery step and the cold-start gate, each with a
  Python call per pair for the "same kind?" test.

A live profile of the running service (`py-spy dump`) put the monitor's analysis thread **inside
`iou()` in `monitor/tracking.py`** — not in the detector. The whole per-cycle cost on the box was
about 2 s, of which the detector was 0.24-0.75 s and the tracker the rest.

## Fix

`backend_host/scripts/monitor/tracking.py`:

- **`iou_matrix()`** — every IoU of a list of boxes against a list of boxes, as one array operation
  (the scalar `iou()` stays, and returns the same numbers).
- **`OcSortTracker._cost_matrix()`** — the assignment cost matrix is built with arrays: the IoU of
  every detection against every track's predicted box, the direction term, and the `big` cost for a
  pair below `min_iou` or of another kind. The "same kind?" test became a comparison of the label
  groups as arrays instead of a Python call per pair.
- **`hungarian()`** now uses `scipy.optimize.linear_sum_assignment` when scipy is installed (it is —
  scikit-learn pulls it in) and keeps the pure-Python solver as the fallback for a host without it.
  Both solve the same problem: the same minimum total cost.
- the recovery step and the cold-start gate keep their exact matching rules, with their distances
  computed as arrays.

**The answers did not change.** The new tracker is compared against the original implementation
(a subclass that keeps the old loops) on a moving-belt sequence: the same pairs are matched, the
same track ids are created, the same number of tracks is alive afterwards. The cost matrix is the
same matrix, cell for cell (to 1e-9). The tests pin both (`tests/backend_host/test_tracking_vectorised.py`).

Measured on the egg line's workload (175 detections against 345 live tracks):

| | cost matrix | whole 6-frame replay |
|---|---|---|
| before | 0.25 s per frame | 1.5 s |
| after | 0.012 s per frame | **0.076 s** |

**~20x faster**, and the tracker is no longer the thing that decides how fast the egg line runs.

## Why this matters beyond the egg line

Every counting profile pays this: `counting_cars` runs the same tracker over the same kind of
scene (a few dozen cars is cheap, but a dense scene is not), and the monitor service runs three
profiles in ONE python process, so a tracker that burns a second of CPU per analysis slows the other
devices' monitoring down as well.

## Verification

- `tests/backend_host/test_tracking_vectorised.py` — the array IoU matches the scalar one; the
  vectorised tracker matches the reference matcher; the cost matrix matches cell for cell; the
  vectorised path is at least 3x faster than the reference (a relative check, so it does not depend
  on the machine); the solver is optimal and agrees with the pure-Python solver on the total cost.
- The existing suites that exercise the tracker (`test_egg_quality.py`, `test_counting_cars.py`,
  `test_trust_just_verified_position.py`) pass as before.
- Live on `vpt-lenovo1`, the analysis rate of the frame metadata measured over a 60 s window (the
  number of times the analysis changed, and the median gap between two analyses):

  | profile | before | after |
  |---|---|---|
  | `egg_quality_yolo_belt` (graded, 960) | 0.45 analyses/s | **0.67 analyses/s** |
  | `egg_count_yolo_belt` (count only, 960) | 0.48 analyses/s | **0.85 analyses/s** |
  | `egg_count_yolo_belt_fast` (count only, 640) | 0.48 analyses/s | **1.57 analyses/s** |
