# BUG-0230 — 24 h archive chunks lose whole minutes (ffmpeg deletes segments mid-merge)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0230                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed (live on vpt-pi1, vpt-pi3 since 2026-10-02 05:50)      |
| Severity  | Medium                                                       |
| Area      | backend_host / archive                                       |
| Fixed in  | Unreleased                                                   |
| Commit    | `4d1c5cd18`                                                  |

---

## Symptom

On the A/V quality page (and any 24 h archive playback), clicking a moment on the timeline played
black, or showed a later moment than the one clicked, while the FRAMES tab showed the right still.
The 10-minute archive chunks are shorter than the wall time they cover, always by whole minutes:
on vpt-pi3, capture4 hour 19 chunk 1 spans 19:10:00–19:19:31 (571 s) but the file is 360 s, its
frame at 240 s shows the box clock at 19:17; chunk 5 (19:50–19:59) is 300 s. Every chunk length is
an exact multiple of 60 s at a steady 10 fps. capture3 lost more (e.g. 180 s kept of ~528 s). In
one hour capture4 appended 32 minutes and logged 36 failed merges; capture3 21 and 58. Not specific
to a device or to static screens: every device on this pipeline.

## Root cause

- The live stream writes 0.4 s HLS segments and ffmpeg keeps exactly the playlist on disk:
  `-hls_list_size 150 -hls_flags delete_segments` (`backend_host/scripts/run_ffmpeg.sh`), so
  150 × 0.4 s = 60 s, and with the default `-hls_delete_threshold 1` the oldest file is deleted as
  soon as it leaves the playlist.
- Every ~30 s the archiver merges "the oldest 150 segments" into a 1-minute MP4
  (`backend_host/scripts/hot_cold_archiver.py` → `merge_progressive_batch` in
  `shared/src/lib/utils/video_utils.py`). It only fires once 150 exist, which is also ffmpeg's
  ceiling, so ffmpeg is deleting the oldest file while the concat reads it:
  `[concat] Impossible to open '.../hot/segments/segment_000864438.ts'` → `1min MP4 not created`.
  The whole minute is never appended to the 10-minute chunk.
- The concat is a stream copy, so the chunk has no gap in its timestamps: the player maps wall
  time linearly into the file, a seek late in a chunk lands past its end (black), an earlier one
  shows a later moment.
- The archiver's own safety cap (`HOT_LIMITS['segments'] = 200`) would have become the next limiter
  once ffmpeg kept more.

Separate from [BUG-0032](BUG-0032-2026-07-28-report-video-cold-chunk-time-shift.md) (minutes filed by the current clock, up to 60 s shift at a
chunk's start), which remains.

## Fix

- `run_ffmpeg.sh`: every HLS writer passes `-hls_delete_threshold` equal to its list size, so ffmpeg
  keeps one more playlist's worth of segments (~120 s) before deleting. The playlist (live window)
  is unchanged. Cost: ~17 MB of the 400 MB hot tmpfs per device at the measured 58 KB/segment.
- `hot_cold_archiver.py`: `HOT_LIMITS['segments']` 200 → 400 (above ffmpeg's 300 on disk).
- `video_utils.merge_progressive_batch`: files that vanish between the listing and the stat are
  skipped, and if the concat fails while some of the batch is gone, the remaining files are merged
  instead of dropping the whole minute.

## Verification

- `tests/backend_host/test_merge_progressive_batch.py` (real ffmpeg): a segment deleted mid-merge
  still yields a 1-min MP4 of the rest (fails on the old code), the batch is the oldest N in order,
  too few segments is not a merge.
- ffmpeg 5.1.8 (the Pi hosts' version) supports the option; locally, `-hls_list_size 5
  -hls_delete_threshold 5` leaves 10 segments on disk and 5 in the playlist (threshold 1: 6).
- After a host deploy: `grep -c "Impossible to open" ` in the archiver log drops to ~0, and the
  closed chunks' `ffprobe` duration matches their manifest span (~600 s, `segments/<HH>/chunk_10min_*.mp4`
  vs `archive_manifest.json` start/end); an AVQ timeline click late in a chunk shows the right moment.

Verified live 2026-10-02 on vpt-pi1 and vpt-pi3. The deploy alone changed the files but not the running
processes: `vpt-stream` and `vpt-archiver` had to be restarted (05:50:21). After the restart:
ffmpeg runs with `-hls_list_size 150 -hls_delete_threshold 150`, the archiver logged 0
`Impossible to open` (60 and 40 successful 1-min merges in the first 20 min, against 51-74
failures per 30 min before), and the first full chunk after it (06:00-06:10) is 600.0 s on every
active device (vpt-pi1 capture1/3/4, vpt-pi3 capture3/4), where the same devices wrote 120-360 s
chunks the day before. Hot segments stay well under the cap (~90-225): the archiver now drains the
oldest 150 before ffmpeg would delete them.
