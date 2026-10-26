# BUG-0913 — The egg overlay draws its circles in the player's space, not on the picture

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0913                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | frontend / monitoring overlay                                 |
| Fixed in  | build 90145 |
| Commit    | `ba4bfb9b0`                                                  |

---

## Symptom

On the device3 egg line, the monitor overlay draws **hundreds of violet circles that are not on the eggs**: a whole
cluster floats in the black band **above** the picture, others sit on bare belt, and some are cut by the panel
edge. The HUD still says *"locked to the analysed frame"*, so the picture and the boxes are supposed to be the same
frame — they are not.

Seen on the owner's screen on 2026-10-25 (the device page, "Egg count (fast)", 881 eggs / 204 detections, 7 fps in /
8 fps out).

## What is NOT the cause (already measured)

The **server** is right. Taking the newest frame metadata of the device and the capture it names (`filename`), and
drawing the observations on that capture:

- **204 observations, 202 of them on a white egg (99.0 %)** — `/tmp/eggone/analysed_overlay.jpg`;
- the JSON's `filename` names the analysed frame, and that capture is served (`GET
  /stream/capture3/captures/capture_XXXX.jpg` → 200).

So the model, the host, the analysis and the frame-lock data are all correct. **The defect is in the client.**

## The two candidates

| # | Candidate | Where | Discriminator |
|---|---|---|---|
| **A** | The boxes are mapped to the **player container** while the picture is `contain`-fitted inside it (`object-fit: contain`). When the container is not 16:9 the picture is letterboxed and the boxes are stretched to the container: the top row lands above the picture, the bottom row below it, the side rows outside it — the radial pattern in the screenshot | `frontend/src/components/monitoring/ProfileOverlay.tsx` (`bboxToPercent` returns percentages of the container) and `frontend/src/components/monitoring/AnalysedFrameLayer.tsx` (the image is `maxWidth/maxHeight: 100%`, `objectFit: 'contain'`) | in the live page, compare `[data-testid="analysed-frame-img"]`'s `getBoundingClientRect()` with the overlay container's rect — **if they differ, it is A** |
| **B** | The analysed-frame image never loads (404, or the capture was already drained from the RAM-mode hot folder), so the **live stream** shows through while the boxes stay where the analysis put them (1-2 s old, drifting along the belt). The "locked to the analysed frame" label is driven by the `frameLocked` state, not by the image having loaded | `frontend/src/components/video/EnhancedHLSPlayer.tsx` (`analysedFrameUrl` from `monitoringAnalysis.filename`) → `AnalysedFrameLayer` (`{frameLocked && url && …}`) | the same page: is `[data-testid="analysed-frame-img"]` present and is its `naturalWidth > 0`? |

## Why it was not caught before

Every number on the server is right, and the headless checks that exist draw the boxes **server-side** (on the
analysed capture) — they never compared what the browser actually paints. The defect only exists in the browser's
geometry.

## Root cause

Candidate A, with one more twist the table above did not have. The boxes were drawn in an SVG covering the whole player
(`viewBox` = `frame_size`, `preserveAspectRatio="xMidYMid meet"`), so they were letterboxed to the **player**. The
picture was a separate `<img>` with `width/height: auto` and `maxWidth/maxHeight: 100%`: an image is never scaled *up*
by those rules, so it stayed at its own pixel size in the middle of the player while the boxes spread over the whole
player. On the owner's screen the picture was ~1329x805 px and the boxes covered ~1585x878: the radial pattern, the
top row in the black band, the side rows off the picture.

## Fix

The picture is no longer a separate element: the overlay draws the capture **inside the boxes' own SVG**, as an
`<image>` of `frame_size` pixels at (0, 0) (`ProfileOverlay.tsx`, `UiBoxes`). One transform letterboxes the picture and
its boxes together, so they cannot land apart whatever the player's shape or the JPEG's size. A new capture is preloaded
off-screen and shown only once it has loaded, **together with the analysis it belongs to**, so a slow image never shows
new boxes on the previous picture; a capture already drained from the hot folder (load error) draws the boxes on the
black backdrop rather than freezing. `AnalysedFrameLayer` keeps only the black backdrop that hides the live stream and
the frame-lock switch. The velocity extrapolation is still not used in frame-lock mode.

## Verification

Live, headless, on the device3 page (vpt-pi4 server, 1600x900): the `<image>` is inside `profile-shapes`, drawn at
1311x738 (the 16:9 fit), **184 ellipses and 0 of them outside the picture**, six different captures in two seconds, the
HUD still "locked to the analysed frame"; the screenshot shows every circle on its egg. Tests:
`tests/frontend/AnalysedFrameLayer.test.tsx` (the picture is in the SVG in frame pixels; the previous picture keeps its
own boxes until the next capture has loaded).
