# BUG-0009 — capture hot tmpfs fills up with OCR debug images the archiver can't see; stream corrupts

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0009                                                     |
| Reported  | 2026-07-21                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / archiver + text verification                  |
| Fixed in  | build 8414                                                   |
| Commit    | `718954808`                                                          |

---

## Symptom

capture2 on host1 (prod) flapped between "stream connection issue" and playing; the
browser threw fatal `bufferAppendError` (audio SourceBuffer). `df` showed the device's hot
tmpfs at **100%** (`/data/stream/capture2/hot`, 200 MB cap) while the other three captures sat
at 38–62%. The archiver ran fine and even reported the oversize —
`captures=17434/300 (151.8MB)` — but its FAST loop for capture2 logged **no `captures:`
cleanup line at all**, cycle after cycle.

## Root cause

Two matching rules disagree:

- The archiver's stats counter (`get_hot_folder_stats`) counts **every** file in
  `hot/captures/`.
- The actual cleanup (`rotate_hot_captures` → `cleanup_hot_files`) only deletes files matching
  **`capture_*[0-9].jpg`**.

`hot/captures/` on capture2 held 17,302 `text_detection_*.png` (oldest from Jul 16) plus 195
orphaned `capture_*.jpg.tmp` — none match the glob, so the cleaner saw ≤300 eligible files and
did nothing while the stats view showed 17k. The PNGs come from
`TextHelpers.detect_text_in_area()` (`text_helpers.py`), which writes per-call OCR
debug/overlay images into the captures dir with **no owner ever deleting them**. Continuous
text verification against that device filled the 200 MB tmpfs in ~5 days; ffmpeg could then no
longer write segments cleanly, producing the corrupt fragments the frontend choked on.

## Fix

Two layers:

1. `backend_host/scripts/hot_cold_archiver.py` — `sweep_stale_hot_files()`: catch-all sweep in
   every FAST cycle that deletes **any** file older than 1 h from the hot subdirs
   (segments/captures/thumbnails/metadata), regardless of filename. A 200 MB tmpfs holding a
   ~60 s buffer must never depend on every producer using the expected naming. Non-recursive,
   so SD-mode hour folders are untouched; capped by `HOT_CLEANUP_BATCH` per cycle.
2. `backend_host/src/controllers/verification/text_helpers.py` —
   `_purge_stale_debug_images()`: `detect_text_in_area()` now purges its own
   `text_detection_*` artifacts older than 10 min before writing new ones.

Immediate operator relief applied on host1:
`find /data/stream/capture2/hot/captures -name 'text_detection_*.png' -mmin +10 -delete`
(plus the `*.jpg.tmp` equivalent).

## Verification

- `py_compile` passes on both files.
- After deploy: archiver journal should show a one-time
  `stale-sweep: deleted N stale files` burst on affected hosts, then
  `df /data/stream/capture*/hot` stays well below 100% and the capture2 player no longer
  cycles through `bufferAppendError`.
- Diagnosis recipe for recurrence: archiver stats show `captures=BIG/300` but the FAST loop
  prints no `captures:` line → files not matching `capture_*[0-9].jpg`; run
  `ls hot/captures | sed -E 's/[0-9]+/N/g' | sort | uniq -c | sort -rn | head` to name them.
