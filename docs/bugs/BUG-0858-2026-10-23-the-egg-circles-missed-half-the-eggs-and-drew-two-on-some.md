# BUG-0858 — the egg circles missed half the eggs, and drew two or three circles on some of them

**Found** 2026-10-23, on `vpt-lenovo1` device3 ("Synthetic eggs"), straight after BUG-0848 shipped the
model-backed detector. **Reported by** the owner, on a fixed frame:
*"still not accurate on a fixed frame … we need on this image to get all eggs with right shape"*.

## What was wrong

BUG-0848 shipped the right kind of detector and proved that where the model fires, the box IS the egg
and the fitted ellipse is the right size and shape. What it did not ship is the **input pipeline**
the model needs, and without it the model fires on a fraction of the eggs. On the device3 frame
(one fixed 1280x720 frame, ~200 eggs in it) the shipped profile drew **95 circles, and the frame had
about 200 eggs in it**. Two defects, both visible in the same image:

1. **Half the eggs had no circle at all.** The model was trained on a portrait video of BIG white
   eggs (150-250 px) on yellow rods, in daylight. The device3 feed is a landscape shot of small white
   eggs (20-70 px) on a saturated blue belt. Fed that, the model is looking at the wrong scale, the
   wrong colour and the wrong density, and it drops eggs. The fix is not a better model — it is
   showing the model something like what it saw.
2. **Some eggs had two or three circles on them.** IoU NMS cannot tell "the same egg, seen twice"
   from "two eggs that touch": two boxes on ONE egg are offset by a few pixels, so their IoU lands
   around 0.3-0.5 — some survive the 0.30 threshold, some do not. Two DIFFERENT eggs that touch
   overlap by ~0.04 and their centres are a full diameter apart, so the discriminator has to be
   centre **distance**, not overlap.

## Fix

**`fill: stretch`** — a square 640 tile fills the model's square input with no grey padding to
confuse it, and a square tile stretched is not distorted. (letterbox 89 boxes → stretch 96.)

**`preprocess: [whitebalance, unsharp]`** — `whitebalance` pulls the saturated blue out of the scene,
`unsharp` brings back the edges the belt's blur takes away. Together they move the picture towards
the training distribution: 89 → 226 candidates.

**`flip_tta: true`** — the same tile seen from the other side. A model that was confused by a
neighbour in a crowd often finds the egg in the mirrored crop, because the neighbour that confused it
is now on the other side. This is the single biggest recall lever measured: 89 → 111 unique eggs.

**`color_filter: {mode: belt, max_ratio: 0.35}`** — the answer to "is that really an egg?". The scene
is white eggs on a SATURATED BLUE belt, so a box that lands on bare belt is mostly blue and a real
egg is mostly not. This is what makes the very low `min_conf: 0.01` safe: the detector offers ~220
candidates and the belt filter removes the 28 that are bare belt.

**`dedupe_dist: 0.35` / `dedupe_ratio: 0.8`** — the answer to "why two circles on one egg?": two
boxes whose centres are within 0.35 of a diameter, and whose sizes are within 80 % of each other,
are the same egg, and the more confident one wins.

## Measured, on that one frame

| configuration | forwards | circles | on bare belt | two circles on one egg |
|---|---|---|---|---|
| shipped in BUG-0848 (letterbox 640x360, no preprocessing) | 9 | 95 | some | many |
| square 640 + stretch | 12 | 96 | some | many |
| + whitebalance + unsharp | 12 | 226 | 28 | many |
| + flip TTA | 12 | 238 | 28 | many |
| + belt filter (`max_ratio 0.35`) | 12 | 198 | **0** | 3 |
| + centre-distance dedupe | 12 | **198** | **0** | **0** |

~200 eggs in the frame, ~198 circles, none on bare belt, none doubled. The remaining misses are the
small dim eggs on the far rows, which the model does not fire on at any threshold or zoom tested.

## Two measurements that changed the plan

- **A brightness test is the wrong filter for this scene.** "Bright and unsaturated" (V>140, S<70)
  rejected 84 of the 220 candidates, and most of those 84 were REAL eggs lying in the shadow of the
  pile; the belt boxes it kept were the bright ones. The saturated-blue test keeps the shadowed eggs
  and cuts the belt, which is the opposite of what the brightness test did.
- **Two scales merged is a mess.** A 320 tile is a 2x zoom and finds the small far eggs, but at 30
  forwards it doubles the cost and its boxes disagree with the 640 pass often enough that merging
  the two scales produces doubled circles all over the far rows (240 boxes, 60 forwards). One scale,
  640, wins.

## Verification

- `tests/backend_host/test_yolo_seg_detect.py` — 29 tests, including: the dedupe merges two looks at
  one egg, keeps two eggs that touch, keeps the more confident box, never merges two classes, and is
  off when not asked for; the belt filter drops a bare-belt box and keeps a white egg; the colour
  filter is off by default; the white mode keeps a bright unsaturated box; the shipped profile
  carries the measured configuration.
- The frame above was measured through the SHIPPED code path (the same `detect()` the host runs),
  not through a separate script: the counts in the table are what the device drew.
- A 640-tile pass costs 12 forwards, ~12.4 s on the box (1.03 s per 640x640 forward), so the
  overlay refreshes about every 12 s. The frame-lock (BUG-0836) is what keeps the circles on the
  eggs at that rate.

## Not done

- **Still not video.** ~12 s a frame is a still picture that updates slowly, not a live video. The
  cost is the 640x640 CPU forward: int8 dynamic quantisation is 3.5x SLOWER on that box and that
  OpenCV has no Intel DNN backend, so there is no fast path on this hardware.
- **The far rows and the deep pile still lose a few eggs.** They are small, dim and crowded, which
  is the case every instance segmenter tested here is weakest on. Zooming in (320 tiles) finds them
  but at 2.5x the cost and with circles that disagree with the 640 pass.
- **Good/bad per egg still means nothing on this footage** — no candling, so no evidence of interior
  quality. Unchanged from BUG-0848.
