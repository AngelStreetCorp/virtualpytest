# BUG-0834 — a looping device counts the same clip for ever, and one threshold welds a belt of eggs into one egg

**Found** 2026-10-22 (owner, on `vpt-lenovo1`) · **Status** fixed · **Area** monitor / `egg_quality`, `counting_cars`

Two defects in what the two synthetic devices showed on their cards. Both were invisible from the
UI: the video played, the card looked fine, and the numbers were either frozen or fiction.

## 1. The counters never restart, so they describe a day, not a pass

A `videofile` device plays one clip with `ffmpeg -stream_loop -1`. Nothing marks where a pass ends,
so `count_total` (`window_s: 3600`) and `count_by_colour` (`window_s: 86400`) grew monotonically:
device 4 showed **2 900 cars in the last hour** after 80 minutes of uptime, and the same car was
counted again in every pass.

The loop is also invisible to the pipeline: `ffmpeg` does not restart, the capture filenames and
timestamps continue, and a scene-cut heuristic on track matching does not fire — measured, almost
nothing matches *because the scene is a static intersection* (new-track share 0.11–0.44 at the
boundary, against 0.87 in-clip).

**Fix:** `img.reset_counters` on the profile. `every_s` is the deterministic trigger (the clip is
that long, so every that many seconds the count starts again at 0); `cut_below` is an optional
scene-cut trigger on the correlation of consecutive 32x18 grey descriptors. The pipeline drops the
tracker, calls `ProfileEvents.reset()` and counts the next pass from zero, and publishes
`counting: {restarts, since}` in the frame JSON.

Measured on two passes of the cars clip: **134 without, 38 with** (peak `count_by_colour` total).
Both shipped profiles set `{ every_s: 30 }`, matching their 30 s clips.

`cut_below` is **off** in both profiles on purpose: with it on at 0.86 it fired inside three
existing `counting_cars` tests, whose synthetic frames are not a real scene. A heuristic that
zeroes a counter on ordinary picture changes is not worth a false positive.

## 2. One box per egg: the threshold detector cannot see real eggs

`egg_detect` is a **candling** detector: brightness, Otsu with a floor, open, close, an ellipse per
blob. It needs a bright egg on a dark belt. On real footage it does not work:

| footage | what it found |
|---|---|
| white eggs on a blue belt | 6–11 blobs for ~60 eggs — a touching pile welds into one blob |
| brown eggs on a grey roller | boxes on the rollers and the machine, not the eggs |
| egg packing station | 3 detections, all bright metal panels |
| a row of 7 eggs, touching | **1** "egg" — one track alive for 29 s, the whole clip |

That last row is the real damage: the count was counting blobs, and a stationary blob is one
"egg" that never leaves.

**Fix:** `method: blob` — a LoG blob detector that finds each egg by its own local contrast, so it
never merges two eggs in the first place. On the blue-belt footage every one of 42 boxes lands on a
real egg (recall is partial: ~50-60 % of the eggs in a pile get one). `brightness` stays as the
default and is still what the candling dataset is cropped with.

**A split was tried and removed.** Distance-transform peaks, erosion markers and a Voronoi split
were all implemented and measured; on overlapping eggs they produce wedge-shaped parts that fail
the ellipse-fit filter, and on real footage they made the boxes *worse* (giant ellipses spanning
half the frame). Shipping a `split` flag that cannot keep its promise would be worse than not
having one, so it is gone.

## Honest limits that remain

* **Recall is partial on a pile.** Eggs deep in a cluster are occluded; no classical detector sees
  them. A trained detector is the answer, not a threshold.
* **The good/bad grade is meaningless on this footage.** The classifier is trained on candling
  shots — an egg lit from below on black — so on white eggs on a blue belt in daylight it reads
  almost everything **bad** (738 bad / 6 good in 30 s). The counts are real; the grading is not,
  and it should not be read as quality control on factory footage.
* **The count is not a census you can check by hand.** 744 "eggs" in one 30 s pass is a detector
  figure over a moving pile, stable from pass to pass, not a number of eggs you can count by hand.
* For `counting_cars`, half the tracks still end `unverified` (26 of 52 at 4 Hz): a timelapse
  intersection shows cars for a couple of samples. Slowing the clip 2.2x cut phantom tracks from 77
  to 36 for the same content; the amber `unverified` chip is the display being honest about it.

## Evidence

`scripts/render_egg_overlay.py` (new) runs the shipped profile's own analyzers over a clip and
paints what `ProfileOverlay` paints, so the result can be checked without a host:
`python3 scripts/render_egg_overlay.py --video eggs_loop.mp4 --model egg_good_bad.onnx --out demo.mp4`.