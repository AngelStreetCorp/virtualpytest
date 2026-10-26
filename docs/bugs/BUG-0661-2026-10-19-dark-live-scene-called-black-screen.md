# BUG-0661 — A dark live scene is badged "Black Screen · 100 %"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0661 |
| Reported  | 2026-10-19 |
| Status    | Fixed (pending deploy) |
| Severity  | Medium |
| Area      | backend_host / monitoring / localize |
| Fixed in  | build 90145 |
| Commit    | TBD |

---

## Symptom

Localize badged "Black Screen · 100 %" on a live but dark picture (Mezzo Live: dark stage, logo top-left,
a lit dancer, a bright textured floor in the bottom quarter). The wrong verdict hides the real one and
could make agents wake a box that is not asleep.

## Root cause

The incident detector (`backend_host/scripts/detector.py`) counted dark pixels only in the 5-70 % band
of the frame and called it black at >= 80 % dark. The bright floor sits in the bottom quarter, outside
the band, so the frame passed. `monitor_localize.py` trusts the detector state over everything else.
`classify_special_state` (mean/std only) had the same blind spot for a small lit area.

## Fix

Black now also requires a uniformly dark FULL frame: at most 2 % of pixels above level 80
(`BLACKSCREEN_LIT_*` in `detector.py`, `FP_BLACK_LIT_*` in `image_helpers.py`). Real black/standby frames
sit at uniform level 7-16, so they are unchanged; a dark scene with a lit region falls through to the
normal path (live / node / unknown).

## Verification

Real frames (vpt-mf1 captures, 2026-10-19), added to the Localize bench on vpt-pi1 (`signal_fixed.json`;
`bench.py build` keeps them):

| frame | detector band dark % / full-frame lit % | old | new |
|---|---|---|---|
| Mezzo Live dark stage (owner's case, mf1 capture3) | 93.9 / 5.7 | black | **not black** |
| stbv1+ standby, uniform level 16 (mf1 capture1) | 100 / 0.0 | black | black |
| black, uniform level 7 (pi1 capture_switch1) | 100 / 0.0 | black | black |

The Localize classifier (`classify_special_state`) never named the Mezzo frame black (mean 26.1, std 23.7):
the false badge came from the detector state. The lit-pixel guard there is defence in depth.

Bench on vpt-pi1, before (2026-10-19 03:52) vs after (same set, new code deployed): 96.4 % of 418, every
kind identical (signal 4/4, live 11/12, node 231/244, overlay 71/71, known_screen 11/12, unknown 75/75).
With the 3 new samples: 96.4 % of 421; signal 6/6 (both real standby frames still `signal`), unknown 76/76
(the Mezzo frame is `unknown`, not `signal`). No kind dropped.
