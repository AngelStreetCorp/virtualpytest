# BUG-0474 — capture_monitor grows ~0.6 GB/day: opencv leaks every image path string

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0474                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host (capture_monitor, verifications) / shared       |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

`capture_monitor.py` only grows: 1,455 MB on vpt-pi1 (3 devices, 2.5 days up), 738 MB on vpt-pi4
(5 devices, 22 h), 3,444 MB on vpt-nipogi (24 devices, 22 h). On vpt-pi1 +2 MB per 9 min,
on vpt-pi4 +4.6 MB per 10 min. A host with little RAM (1–2 GB) runs out within days.

## Root cause

opencv-python's bindings keep a reference to every `str` filename passed to `cv2.imread` and
`cv2.imwrite`: one live object per call, never freed. Measured on Python 3.11 with opencv
4.10.0, 4.11.0 and 4.12.0 (`sys.getallocatedblocks()` +1.00 per call with a new path string;
`cv2.imencode`, `cv2.imdecode`, `np.fromfile`, `ndarray.tofile` +0.00). The detector reads a
capture and its thumbnail every frame (`backend_host/scripts/detector.py`), so the monitor kept
~32 path strings a second. Found by reading the monitor's memory: the two big anonymous regions
(516 MB + 370 MB) held millions of `/var/www/html/stream/captureN/hot/{captures,thumbnails}/…jpg`
str objects with refcount 1 and no pointer to them anywhere, and `detect_issues()` in a loop left
+2.1 blocks per call.

Upstream bug, already fixed: `pyopencv_to()` (`modules/python/src2/cv2_convert.cpp`) called
`obj = PyOS_FSPath(obj)` for path-like arguments and never released the new reference.
[opencv#28047](https://github.com/opencv/opencv/pull/28047) (merged 2025-11-26) adds the
`Py_XDECREF`; first released in 4.13.0. Measured: 4.13.0, 4.14.0 and 5.0.0 do not leak. Every host
runs opencv 4.11.0 with numpy 1.26.4, and opencv 4.13+ requires `numpy>=2` while
`backend_host/requirements.txt` pins `numpy<2.0.0`, so upgrading OpenCV means a numpy 2 migration.

## Fix

`shared/src/lib/utils/cv2_io.py`: `imread(path, flags)` / `imwrite(path, img, params)` with the
same arguments and return values, through `np.fromfile` + `cv2.imdecode` and `cv2.imencode` +
`tofile`. All 116 `cv2.imread` / `cv2.imwrite` calls in long-running code (backend_host/src,
backend_server/src, shared/src, the monitor's scripts, companion) use it. Contract #30;
`tests/backend_host/test_cv2_io.py` fails if runtime code calls `cv2.imread` / `cv2.imwrite` again.

## Verification

- `tests/backend_host/test_cv2_io.py`: same pixels as cv2.imread for COLOR / GRAYSCALE /
  REDUCED_GRAYSCALE_4 / UNCHANGED, None for missing / empty / non-image files, imwrite round trip
  and JPEG params, no leak (cv2.imread 1.00 block/call, cv2_io < 0.1), and the runtime-code guard.
- After deploy: capture_monitor RSS on vpt-pi1 / vpt-pi4 sampled over time stays flat.
