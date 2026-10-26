# BUG-0848 — the egg circles did not fit the eggs, and there was no way to see that they did not

**Found** 2026-10-22, on `vpt-lenovo1` device3 ("Synthetic eggs"), after BUG-0836 made the overlay sit
on the eggs at all. **Reported by** the owner, looking at a still frame with the new frame-lock on:
*"but still not good … we suppose to have circle around each eggs perfectly"*.

## What was wrong

Two separate things, and only one of them is a bug.

**1. The circles were the wrong size — that is a real defect.** `egg_quality` detects with
`egg_detect method: blob`, a LoG blob detector, and the box it returns is the **LoG response
diameter**, not the egg. On the device3 frame it draws 45 px circles on eggs that are 55-70 px across:
a circle roughly two-thirds the size of the thing it points at, which reads as "the detector is
guessing" even where it has found the right egg. The positions were fine (101-107 per frame wherever
the parameters were pushed); only the geometry was wrong. This is why the blob path is kept for
tracking and not for drawing.

**2. "every egg" is not reachable with this model — that is a limit, not a defect.** The owner asked
for a circle around every egg rather than around what the detector finds. On this frame (a wide shot
of a belt with eggs shoulder to shoulder, hand-counted at ~220 on a 3x zoom) no configuration of the
best publicly available egg model reaches that:

| configuration | forwards | boxes | boxes / ~220 |
|---|---|---|---|
| whole frame, one pass | 1 | 47 | 21 % |
| 4 tiles 800x450 | 4 | 77 | 35 % |
| 9 tiles 640x360 (shipped) | 9 | 95 | 43 % |
| 16 tiles 480x270 | 16 | 106 | 48 % |

Where the model fires the box **is** the egg: fitted ellipses are the right size and the right shape,
which is the whole of what was wrong before. What it will not do is propose an instance for every egg
in a crowd, and no threshold, tile size, zoom or NMS setting tested changed that (30+ configurations).

For scale: the owner's own reference clip shows `Eggs 253 / Detections 82`, i.e. the reference itself
boxes about a third of what it sees. The shipped profile boxes 95, which is in that range and
slightly above it.

## The model

`best.pt` from `Yossefmohammed/EGGS-counting-Detection-with_YOLOV8-Model` — a YOLOv8s **segmentation**
model trained by a third party on the public Roboflow `egg-seg-1` set. GitHub-hosted, no account, no
key, 23.8 MB. The other candidates were not usable: `afshin-dini/Egg-Detection` on HuggingFace is
gated (401), `enescanerkan/yolov11-egg-counter` commits no weights, and Roboflow Universe needs a key.
No better login-free model exists; the strongest COCO-pretrained YOLOv8s-seg benchmark is slower than
this one and no better at eggs.

## Fix

**A model-backed detector, `yolo_seg_detect`** (`backend_host/scripts/monitor/analyzers/yolo_seg_detect.py`),
through `cv2.dnn` like `coco_detect`, so no torch on the host. It owns the YOLOv8 head: letterbox,
decode, class-aware NMS, and the sliver filter. It fits an **ellipse to the box** for the overlay, so
the circle is the egg rather than a LoG estimate of it.

**Slicing, because one 640x640 input cannot hold 200 eggs.** The same model on a 480x240 crop of the
frame finds 22 of the 26 eggs in it (85 %); on the whole frame it finds 47. It loses the rest to
context, not to blindness — so the frame is cut into overlapping tiles and the tiles are merged. The
ONNX input is a fixed square, so a tile wider than 640 px can only be scaled *down* into it (the
whole-frame failure again); narrower tiles are scaled *up*, which is the scale the model was trained
at, and which is worth 47 boxes to 95.

**A stat row, because a single number cannot say this** (`ui.stats`): `Eggs 253 · Detections 82`.
Eggs is what the profile counted, Detections is how many boxes are in the analysed frame, and a big
Eggs next to a small Detections is the detector missing eggs that are plainly on the belt. This
replaced `ui.headline` on `egg_quality`, which showed the same total on its own.

## What it costs, and the trade

Measured on `vpt-lenovo1` (4 cores; that OpenCV has no Intel DNN backend, so `getAvailableTargets`
returns nothing and it is CPU either way):

| runtime | one 640x640 forward |
|---|---|
| `cv2.dnn` | 1029 ms |
| `onnxruntime` 1.31, 4 threads | 1083 ms |
| int8 dynamic quantisation | **3780 ms** (3.5x slower — this ORT build has no optimised int8 path) |

So the shipped 9-tile profile is **~10 s per frame**, against 41 ms for the blob detector it
replaces. The picture updates about ten times a minute instead of five times a second. That is the
trade, and it is why this is a **separate profile** rather than a replacement: `egg_quality` (blob,
fast, circles too small) and `egg_quality_yolo` (model, circles right, ten seconds a frame) both ship,
and switching the device between them is one field.

At that rate the overlay's frame-lock (BUG-0836) is no longer a nicety: it is what keeps the circles
on the eggs, since a box drawn on a moving live stream would be a full second wrong.

## Three things that silently produced wrong numbers while this was built

Recorded because each one *reported success*:

- **`cv2.dnn.NMSBoxes` takes `(x, y, w, h)`, not xyxy.** Handed xyxy it inflates every overlap and
  deletes most of the boxes: the whole-frame count read 36 instead of 87, and slicing looked like it
  made recall **worse** (62 vs 88) when it in fact doubled it (154 vs 87). The whole first round of
  measurements was wrong because of this. `nms()` in the analyzer converts, so callers cannot repeat
  it, and there is a test that fails if it is removed.
- **A segmentation head is `4 + n_classes + 32 mask coefficients`.** Exporting without the mask
  branch leaves 37 columns with nothing marking where the classes end; reading "attributes - 4" makes
  every coefficient above `min_conf` a class score, and the frame returns **618 boxes instead of 47**.
  The class count is now taken from the prototypes when they exist and from the profile's `classes`
  when they do not, and with neither it refuses to run.
- **`tile_overlap` was being used as the step, not as the overlap.** "0.25" therefore ran a 75 %
  overlap: 240 forwards and 75 s a frame where 12 tiles were meant. Now `step = tile * (1 - overlap)`
  and there is a test that pins the step and the tile count.

## Verification

- `tests/backend_host/test_yolo_seg_detect.py` — 18 tests: NMS keeps a neighbour and drops a
  duplicate, keeps 25 boxes in a frame of 25, the tile grid overlaps and reaches the far edge, the
  overlap is the overlap, head decoding returns frame pixels and applies the tile offset, a box
  entirely off-frame is dropped while one straddling the border is clipped, and both shipped profiles
  load with `tile` no wider than the model input.
- `tests/backend_host/test_egg_quality.py` — the `stats` block is asserted (label, kpi,
  observations), and five bad-`stats` variants are refused by both validators.
- `tests/frontend/ProfileOverlay.test.tsx` — 26 pass, including `Eggs 173 / Detections 3`, 82
  detections from an 82-observation frame, and a dash before the first KPI.
- Reproduced end to end against the shipped decoder on the live device3 capture: the figures in the
  table above, and `proof_shipped.jpg` (95 circles, one per egg, fitted).

## Not done

- **Good/bad per egg is unchanged and still means nothing on this footage.** `egg_classify` runs a
  two-class good/bad model over each egg crop; on a blue belt in daylight there is nothing in the
  image that grades an egg. It reports ~99 % bad because that is what the model says, not because the
  eggs are bad. A real grade needs candling (the egg against a light), which this camera is not doing.
  The counters are left in place and labelled `good` / `bad` / `unverified` so the block still reads
  sensibly, but no number here should be read as a quality measurement.
- **The dense end of the belt stays the weak spot.** The left-hand pile and the far rows are where the
  remaining misses are; they are small and crowded, which is the case every instance segmenter tested
  here is weakest on.