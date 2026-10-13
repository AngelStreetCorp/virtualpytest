# BUG-0469 — Report video loses its tail when the archiver rotates HOT mid-build

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0469                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | shared (report video) / backend_host archiver                |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

A report video for a test longer than the HOT window (~40–60 s) sometimes ends early. On
vpt-pi1 a 150 s window logged `no usable HOT tail` and `known gaps: 21:21:26→21:22:09 (43.0s)`
although 113 in-window HOT segments had been selected; the next run of the same window was
complete. Intermittent: it needs the archiver to archive a minute while the video is built.

## Root cause

`extract_test_video_hybrid()` (`shared/src/lib/utils/storage_path_utils.py`) selected the
in-window HOT segments, then read COLD (several seconds), and only then copied the HOT segments
in `_merge_segments_to_mp4()`. In between, `hot_cold_archiver.py` archived the next minute and
deleted exactly those HOT segments; COLD had been read before that minute was appended, so the
footage was in neither half.

The archiver also deleted the minute's HOT segments right after the 1-min merge
(`merge_progressive_batch(..., delete_source=True)`), before the MP3 and the 10-min append:
1–2 s per minute where that footage was in neither HOT nor the chunk.

## Fix

- `extract_test_video_hybrid()` hard-links the in-window HOT segments into a pin dir
  (`segments/.pin_report_*`) before the COLD read and builds the tail from the pins; a segment
  deleted before its link was archived first, so the COLD read that follows has it. The pin dir
  is removed in a `finally`.
- `archive_hot_minute()` deletes the minute's HOT segments after the 10-min append, in a
  `finally` (a failure cannot leave them to be archived twice). `merge_progressive_batch()`
  gained `merged_batch` to hand the batch back.

## Verification

- `tests/backend_host/test_report_video_hot_pin.py`: the COLD stub deletes every HOT segment
  (the archiver), and the HOT merge still gets all of them readable; fails on the old code.
  Archiver deletion after the append, and on an append error.
