# BUG-0297 — Hot kept only two minutes of live segments, so a late archiver cycle could still lose part of a minute

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0297                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed                                                        |
| Severity  | Low                                                          |
| Area      | backend_host / stream / archive                              |
| Fixed in  | Unreleased                                                   |
| Commit    | `this commit`                                                |

---

## Symptom

Follow-up to [BUG-0291](BUG-0291-2026-10-04-a-late-archiver-cycle-lost-a-whole-minute.md). Its
fix (pinned merge, fixed 30 s schedule, catch-up) left one limit: a capture whose archiver cycle
comes more than ~60-120 s late can still lose part of a minute, now logged as
`[captureN] Lost K minute(s)`. vpt-pi1's longest gap between two cycles of one capture was 114 s.

## Root cause

The v4l2 (HDMI grabber) writer in `backend_host/scripts/run_ffmpeg.sh` kept
`-hls_list_size 150 -hls_delete_threshold 150`: 300 segments x 0.4 s = **120 s** on disk
(`run_ffmpeg.sh:1140` and `:1240` before the fix; HD+ 30 + 30 x 2 s, also 120 s). The archiver merges once a
full minute (150 segments) exists, so a finished minute stayed in hot only 60-120 s before
ffmpeg deleted it. The 1 s writers (VNC, ADB, imagefile, file/HLS/RTSP/YouTube) already keep
150 + 150 x 1 s = 300 s.

## Fix

- `run_ffmpeg.sh` v4l2 live tiers (low/sd/hd): `-hls_list_size` and `-hls_delete_threshold`
  150 -> **300**: 300 listed + 300 past the playlist = 600 segments = **240 s** on disk. A finished
  minute now survives ~3-4 min.
- Raising the threshold alone does nothing. ffmpeg 5.1's `hls_delete_old_segments` keeps past the
  playlist at most the playlist's own duration, whatever the threshold. Measured: list 10 +
  threshold 30 leaves 22 segments on disk, list 150 + threshold 450 leaves 302, list 300 +
  threshold 300 leaves 600. So the playlist grows too: the live window is now 120 s (300 x 0.4 s);
  the frontend's live slider already caps at 150 s (`EnhancedHLSPlayer.tsx`).
- HD+ (2 s segments, 12 Mbit/s) is **not** changed: a segment is ~3 MB, so 60 more would be
  ~180 MB of hot tmpfs. It still keeps 30 + 30 x 2 s = 120 s. No host runs it today (it needs
  VAAPI; vpt-pi1/vpt-pi3 fall back to `hd`).
- `hot_cold_archiver.py` `HOT_LIMITS['segments']` 400 -> **700**. It is the archiver's own
  safety cleanup and must stay above what ffmpeg keeps; at 400 it would delete the oldest 200 of
  the 600 itself, before the merge reads them.

## Consumers checked

- **Archiver:** merges the oldest `round(60 / EXTINF)` segments and deletes them, catch-up up to
  `MAX_MINUTES_PER_CYCLE = 3` per cycle: unchanged, it simply finds more waiting after a stall.
  Because it deletes what it merges, hot normally holds 150-300 segments (`segments=66/400` in
  its inventory line) whatever ffmpeg's ceiling is; the ceiling is only reached while the
  archiver is behind or its merges fail.
- **Live player / playlist:** `output.m3u8` now lists 300 segments (~12 KB instead of ~6 KB,
  reloaded every segment by each viewer). hls.js starts at the live edge (`HLSVideoPlayer.tsx`
  `liveSyncDuration`), and the live slider caps at 150 s, so 120 s fits. As before, segments the
  archiver already merged are gone from disk while still listed; seeking back more than ~60 s in
  the live window could already hit them.
- **video_utils / monitor / transcript:** read the newest segments or the playlist; none assumes
  a 300-segment ceiling.
- **RAM:** a 0.4 s segment is ~85 KB on vpt-pi1's busiest STB stream (capture4: 151 segments,
  12.6 MB), so the worst case is +300 x 85 KB = ~25 MB per device, only while the archiver is
  behind. Hot tmpfs is 400-512 MB per device; `df -t tmpfs` on 2026-10-04: vpt-pi1 36-116 MB used
  per mount (16 GB RAM), vpt-pi3 90-93 MB (8 GB). Only vpt-pi1 and vpt-pi3 run v4l2 writers;
  vpt-pi4, vpt-nipogi, host-clone-1 (4 GB) and the labox hosts run 1 s writers only and are
  unaffected (labox-dongle's 200 MB mount included).

## Verification

- `tests/backend_host/test_archiver_minute_slot.py`: the real `process_hot_storage` loop over a
  simulated ffmpeg with one cycle in eight 100-150 s late loses minutes at a 300-segment ceiling
  and none at 600; a guard parses every HLS writer in `run_ffmpeg.sh`, computes
  list + min(threshold, list) and asserts `HOT_LIMITS['segments']` stays above the largest (600).
- Local ffmpeg 5.1, 400 s of 0.4 s segments: list 300 / threshold 300 -> 600 on disk, 300 listed.
  The first version of this fix (list 150 / threshold 450) -> 302: it would have changed nothing.
- vpt-pi3 (2 HDMI STBs, `low`), `vpt-stream` restarted under a lease at 14:23 CEST: ffmpeg runs
  `-hls_list_size 300 -hls_delete_threshold 300`; the playlist served by vpt-host
  (`/host/stream/capture4/segments/output.m3u8`) is 300 entries, 11.8 KB, and its newest
  segment and one 40 s back both return 200. Steady state hot: 75-98 segments, tmpfs 49-72 MB of
  400 MB. Then `vpt-archiver` was stopped for 3 min (14:26:19-14:29:19): capture4's hot grew to
  548 segments (9 MB of segments, tmpfs 147 MB); under the old 300 ceiling ~100 s of it would have
  been deleted. On start the first cycle archived slots 6, 7 and 8 (552 -> 407 -> 265 segments,
  catch-up), then 9 and 0; no `Lost ... minute(s)`, no failed merge, hot back to ~50-170
  segments. (capture3's grabber stalled at 14:26 and the stream watchdog restarted it, as it did
  twice at 14:20-14:22 under the old ffmpeg: an MS2109 stall, unrelated.)
- vpt-pi1 (the other v4l2 host) was **not** restarted: `vpt-pi1/stb4` was leased by another
  agent. Its `run_ffmpeg.sh` is on disk; the change applies at its next `vpt-stream` restart.
  The other hosts run only 1 s writers, whose command did not change, so they were not restarted.
