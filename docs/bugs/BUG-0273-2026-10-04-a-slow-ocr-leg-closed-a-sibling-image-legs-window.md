# BUG-0273 — A slow OCR leg closed a sibling image leg's window

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0273                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — a hop failed on a screen that showed its target     |
| Area      | `backend_host/src/services/verifications/verification_executor.py` (`_execute_shared_window`) |
| Fixed in  | build 90145 |
| Commit    | `this commit`                                                |

---

## Symptom

On vpt-pi1 / stb4, `home_tvguide → home_apps` failed with `apps_red.jpg not detected in source:
capture_055520677.jpg. Match score: 0.000`, after 16.9 s in the shared window
(`legs=2 passed=1 condition=all`). That capture is the base frame, taken 11 ms after the key,
before the menu underline is drawn. The frame 0.8 s later matched at 0.949. Reproduced 1 run in
4 on the same hop: the failing run's OCR leg took 17.3 s, the passing runs' 0.4–4.8 s.

## Root cause

Each leg's window was measured in wall time spent checking (`time.time() - window_start`). The
node has an image leg (10 s) and an OCR leg (20 s); both are checked on the base frame first.
The OCR took 17 s on a loaded Pi (load 8.5 on 4 cores; the capture monitor runs tesseract too),
so when the loop reached the newer frames the image leg's 10 s had passed and it was never
checked again.

## Fix

A leg's window is measured in frame time: a frame is eligible for a leg when it was captured
within that leg's timeout of the base frame. Waiting for new frames stops when no pending leg's
window can still be open; a backlog of frames already captured is still checked, under a hard
wall cap of twice the window.

## Verification

`tests/backend_host/test_shared_window_frame_time.py` (fails before the fix), plus a control: a
frame captured after the leg's window is not accepted.
