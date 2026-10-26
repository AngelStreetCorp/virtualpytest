# BUG-0675 — Localize badge shows an old verdict (a Redis push froze the Localize worker)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0675 |
| Reported  | 2026-10-19 |
| Status    | Fixed |
| Severity  | Medium |
| Area      | backend_host / monitor / localize |
| Fixed in  | build 90145 |
| Commit    | see merge |

## Symptom

stbv1 (vpt-mf1/device2) back from a reboot, on Home with a moving picture-in-picture, still showed "Black Screen" on
the video for over a minute.

## Evidence

Per-frame JSON of capture2 (`hot/metadata`): from 12:12:06 the motion state was `ui`, `blackscreen: false`, yet `localize` stayed
the signal verdict until 12:13:18. The monitor journal showed the matcher naming `home` at 12:12:52, 26 s earlier. Frames
from that window are plainly Home (mean 76, 34 % of pixels above 80), so the matcher side was right.

## Root cause

`localize_frame` pushes every matcher run to the match_runs Redis queue before it returns, and the worker publishes
`_last_localize` only after it returns. vpt-mf1 has no local Redis: `push()` blocks on the connect timeout, measured
26.16 s. The one Localize worker thread (all devices) therefore froze about 26 s after every matcher run, and every
frame written meanwhile carried the pre-run verdict. Not the frontend (it re-reads and replaces the verdict each poll),
not the black rule (detector and matcher agree), not the gate cache.

## Fix

`MonitorLocalizer._enqueue_match_run_async`: the push runs on its own daemon thread behind a 32-slot queue (full: dropped).
The verdict is returned to the worker at once.

## Note

`_enqueue_match_run` compares against `_last_match`, which is already overwritten with the same run, so its `change`
channel never fires. Left as is (separate defect).
