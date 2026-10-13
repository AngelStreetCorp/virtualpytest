# BUG-0357 — "Wait for image to disappear" failed when any frame of its window still showed the image

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0357                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed                                                        |
| Severity  | High - a correct navigation failed its check (stb_tv `home → live`), and every passing check waited its full timeout |
| Area      | `backend_host/src/controllers/verification/image.py` (`waitForImageToDisappear`) |
| Fixed in  | Unreleased                                                   |
| Commit    | `065b8ae9df`                                                 |

---

## Symptom

On stb4 (vpt-pi3, `stb_tv`) the hop `home → live` (HOME key, then `waitForImageToDisappear(blackscreen)`, 10 s)
failed with "Image still present" although the box was playing live TV (POLAR+). The same check passed on stb3 but
only after the full 10.5 s.

## Root cause

The check walked every frame of its window and succeeded only if the image was in **no** frame. A black frame while
the channel tuned, at the start of the window, failed it even though the image was gone right after. Its KPI branch
("disappeared at frame N", needs an earlier frame with the image) could therefore never run. A passing check also
always scanned the whole window.

## Fix

Frames are checked in capture order. The check succeeds at the first frame without the image, which is also its KPI
frame when an earlier frame had it. It fails only if every frame shows the image ("Image still present"), or
with "No capture to check" if no frame was on disk. Doc: `docs/agent/devices/image.md`.

Tests: `tests/backend_host/test_image_wait_to_disappear.py`.

## Verification

Deployed to vpt-pi1 and vpt-pi3 on 2026-10-04. The stb4 replay of "Live: zap 3 times" passed `home → live` and its
four `verify live` checks (execution `cf1146f6`). The stb3 replay of the same testcase passed in 38 s.
