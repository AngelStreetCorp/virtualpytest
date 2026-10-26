# BUG-0298 — The archiver failed every minute on a black or static picture

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0298                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | backend_host / archive                                       |
| Fixed in  | build 90145 |
| Commit    | `this commit`                                                |

---

## Symptom

`capture_switch1` on vpt-pi1 (device5, nintendo_switch, MS2109 grabber `/dev/video8`) archived
nothing from 2026-10-03 ~17:55 on. Every fast cycle logged:

```
[mpeg @ ...] Format mpeg detected only with low score of 25, misdetection possible!
[concat @ ...] Impossible to open '.../hot/segments/.pin_1min_7.mp4/segment_000198875.ts'
1min MP4 not created (not enough segments yet or merge failed)
```

Hot sat at its 300-segment ceiling, so ffmpeg deleted every minute unarchived. The cold
folder has 10-min chunks for 2026-10-03 15:20-17:55 (3-11 MB each) and none after.

## Root cause

Not a grabber or ffmpeg-input problem. The Switch went to sleep at ~17:55 (the last archived
stills show its dimmed "Notice" screen, then black). Since then the MS2109 delivers a black
1280x720 frame (every capture jpg is the same 7402 bytes). The live tier encodes it at
320x180 / 150k with a 4-frame GOP, so each 0.4 s segment is **1504 bytes = 8 TS packets**
(SDT, PAT, PMT, 5 video packets). The segments are valid MPEG-TS: `ffmpeg -f mpegts` reads them.

The archiver merges a minute with the **concat demuxer** (`merge_video_files`,
`shared/src/lib/utils/video_utils.py:67` before the fix), which probes each file on its own.
ffmpeg's mpegts probe needs at least 10 packets (1880 bytes) to score a file as TS; under that it
scores 2, the MPEG-PS probe scores 25 and wins, and opening the "PS" file fails, so the whole
concat fails. Any static or black picture at the live bitrate makes segments this small, so any
device showing one (a sleeping STB or console, a paused screen, no HDMI) lost its archive.

## Fix

`merge_progressive_batch` passes `ts_inputs=True` for `.ts` batches and `merge_video_files` then
reads the batch as one MPEG-TS byte stream (`-f mpegts -i concat:a.ts|b.ts|...`) instead of the
concat demuxer. HLS segments from one writer are consecutive pieces of one TS stream (continuous
timestamps and continuity counters), so the output is the same; nothing is probed per file.
The 10-min append (MP4 + MP4) still uses the concat demuxer.

## Verification

- 150 real segments copied from `capture_switch1` (1504 B each): concat demuxer fails with the
  error above; the new path writes a 60.0 s MP4, 600 frames. 150 real segments from `capture4`
  (a live STB with audio): both paths give the same 60.0 s, 600 video + 2812 audio frames.
- `tests/backend_host/test_merge_progressive_batch.py`: segments are now made by one HLS writer
  (continuous, like production); `test_tiny_static_segments_merge` (black 320x180, segments under
  1880 bytes) fails before the fix and passes after.
- vpt-pi1, `video_utils.py` + `hot_cold_archiver.py` from main and `vpt-archiver` restarted at
  13:55 CEST: the first `capture_switch1` cycle archived slot 3 and caught up slot 4 (the two
  minutes still in hot), then one minute per cycle; `segments/13/chunk_10min_5.mp4` (13:50-14:00)
  is 300.0 s at 13:59 (13:53-13:57). Its previous chunk was 2026-10-03 17:55. No
  `FFmpeg merge failed` and no `Lost ... minute(s)` on any of the four captures since the restart;
  capture1/3/4 (live STBs with audio) keep merging and writing their MP3s.

## Same class, not changed

`audio_transcription_utils` merges `.ts` with `merge_video_files` (`'ts'` output) and
`capture_monitor.py` / `storage_path_utils.py` build their own concat-demuxer commands. They can
hit the same probe on a black picture; none of them was seen failing.
