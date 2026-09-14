# BUG-0032 — Report video misses the test: COLD backfill time-shifted, seam gap silent, duration inflated

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0032                                                     |
| Reported  | 2026-07-28                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (report video unusable whenever COLD backfill kicks in) |
| Area      | shared/storage_path_utils — hybrid report-video extraction   |
| Fixed in  | build 8713                                                   |
| Commit    | `4d255ee81`                                                  |

---

## Symptom

A 66.5s `kpi_measurement` run on `host6` (test `13:12:27 → 13:13:33`, 60s lead)
produced a `test_video.mp4` that did **not** contain the test: the expected ~2 min video
aligned with the test end instead showed pre-test footage, and the Disney app launch that the
KPI measured (13:12:50–13:13:02) was nowhere in it. The extraction log looked healthy:
`COLD chunk 13/1: extracted 117.7s at offset 87.8s` … `merging COLD gap (117.7s) + HOT (8.4s)`.

## Root cause

Three independent defects in `extract_test_video_hybrid` / `_extract_from_cold_chunks` /
`_concat_videos` (`shared/src/lib/utils/storage_path_utils.py`):

1. **COLD offsets assumed chunks start on the nominal 10-min boundary.** The archiver's fast
   loop appends "the previous ~60s" once a minute into the chunk selected by the *current*
   wall clock (`hot_cold_archiver.py`), so `chunk_10min_1.mp4` (nominal 13:10–13:20) actually
   begins with footage from ~13:09:xx and its tail trails the wall clock by up to a minute.
   Seeking with `offset = wall − nominal_start` therefore returned footage up to 60s **earlier**
   than requested — the extracted "test window" was mostly lead-in and pre-test UI.
2. **The COLD→HOT seam was spliced blind.** Extraction runs immediately at test end, when the
   chunk hasn't received the last ~minute of footage yet and HOT retention was down to ~8s.
   The footage in between existed on neither side, and the concat glued COLD-end straight to
   HOT-start with no check — a hidden time-jump that swallowed the middle/end of the test.
   The log's `extracted 117.7s` was the *requested* `-t`, never verified against what ffmpeg
   actually produced.
3. **Concat inflated the container duration.** The final merge fed an MP4 COLD piece (track
   timescale from the chunk muxer) and a TS-derived HOT tail (90kHz) to the concat demuxer;
   the timescale mismatch mis-scaled the second input's timestamps, so a ~101s video reported
   a ~888s duration and a garbage player timeline/seek bar.

## Fix

- **Tail-anchored chunk timelines.** Each chunk's media↔wall mapping is now derived from real
  data: `mtime` (stamped when the last 1-min append lands) is the wall time of the last media
  second, `mtime − ffprobe(duration)` the first. Candidate chunks one nominal window either
  side are considered (coverage leaks ~60s across boundaries), stale 24h-rolling files are
  rejected by their real coverage, and overlapping chunks dedupe via a cursor that advances by
  the **ffprobe-verified** extracted duration.
- **Gaps are detected and reported at generation time.** Every piece logs the wall range it
  actually covers; missing ranges (chunk holes, archiver lag, unusable HOT tail) are collected
  and a `SEAM GAP` warning names exactly which seconds of the test will be missing. Every
  success path ends with a `FINAL VIDEO: window HH:MM:SS→HH:MM:SS (Xs wall) | media Ys |
  missing Zs | known gaps: …` line — wall span vs real media duration is the cheap invariant
  that catches a silently-wrong video.
- **Duration-accurate concat.** `_concat_videos` remuxes each piece to MPEG-TS first (uniform
  90kHz timebase, edit lists stripped, `aac_adtstoasc` back into MP4), then concatenates —
  the merged file's duration now matches its content exactly.

## Verification

Local functional tests with synthetic chunks/segments reproducing the host run
(chunk media 13:09:30→13:13:00, HOT = 8×1s at the window tail, window 13:11:27→13:13:33):

- Offset computed 117.0s (old code: 87.8s — 30s of wrong footage) and the piece ffprobed at
  exactly the chunk's real remaining coverage (93.0s), with the 24s shortfall logged as
  `SEAM GAP` + `known gaps` and `missing 25.0s` in the `FINAL VIDEO` line.
- Multi-chunk window spanning two overlapping chunks (13:08→13:12): output 240.0s, zero gaps,
  AAC audio intact.
- Final COLD+HOT merge: 101.0s media → container duration 101.0s (was 887.7s via the old
  concat on the same inputs).
