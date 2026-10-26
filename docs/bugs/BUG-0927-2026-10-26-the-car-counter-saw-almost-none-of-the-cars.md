# BUG-0927 — The car counter saw almost none of the cars, and its count was not traffic

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0927                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | backend / monitoring                                         |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The `Synthetic cars` device (counting_cars, now on `vpt-lenovo4`) boxed **7.7 vehicles a frame** on a junction with
~150 in view, and its headline "cars in the last hour" changed with the sampling rate: 40 / 70 / 113 verified tracks for
one 30 s pass at 2 / 5 / 10 Hz.

## Root cause

1. **The frame was too small for the model.** YOLOX-nano takes a 416x416 input; a 1280x720 frame letterboxed into it
   shrinks every vehicle to a third, and 20-60 px vehicles fall below what the model finds (0 on the reference frame).
2. **The scene cannot support a count at the box's rate.** A moving vehicle covers about its own length per frame at
   10 fps; at 2 Hz it moves five lengths between samples, no tracker follows it, and parked cars dominate any count of
   tracks.

## Fix

- `coco_detect` takes `tiles: [nx, ny]` (+ `tile_overlap`): one forward per overlapping crop, one NMS over all of them.
  `counting_cars` uses 2x2 at `min_conf: 0.25`: **~57 vehicles boxed a frame** (from 7.7), 0.47 s a frame on the box, so
  2 Hz stays.
- The overlay's headline is **Vehicles in view** (the boxes on screen), not "cars in the last hour".
- The device opens with its overlay on (`monitor_overlay_on`, same change as the egg line).

## Verification

Offline on the 302 frames of the clip and on the box (timings), against a hand count of the vehicles crossing x = 0.5
(~100, slit-scan): line counting finds 91 at 10 Hz, 43 at 5 Hz, 11 at 2 Hz — so no count is shown. Details and the
table: `docs/agent/devices/MONITOR_PROFILES.md` §14. Tests: `tests/backend_host/test_counting_cars.py` (a vehicle in the
overlap of two tiles is one box, in frame pixels), `test_egg_quality.py` (the cars ui).
