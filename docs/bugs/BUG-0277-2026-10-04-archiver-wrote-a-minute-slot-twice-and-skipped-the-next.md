# BUG-0277 — Under load the archiver wrote a minute slot twice and skipped the next, and 10-min chunks held 9 or 11 minutes

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0277                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / archive, transcript                           |
| Fixed in  | build 90145 |
| Commit    | `this commit`                                                |

---

## Symptom

On vpt-pi1 (load 10-18 on 4 cores) the archiver sometimes wrote the same rotating minute slot
twice and never wrote the next one: at 07:56 and 07:57 on 2026-10-04 capture3 wrote `1min_6.mp4`
/ `1min_6.mp3` twice and no slot 7. The transcript service re-ran 121 of 636 minutes (19 %) on a
slot it had already done, and the transcript got repeated text.

The archive is affected the same way. In 6 h of the `vpt-archiver` journal (02:37-08:26):

| capture  | 1-min merges | slot written twice | slots skipped | chunks with 9 / 11 minutes |
|----------|-------------:|-------------------:|--------------:|---------------------------:|
| capture3 | 347          | 80 (23 %, ~14/h)   | 82            | 8 / 6 of 36                |
| capture4 | 339          | 55 (16 %, ~9/h)    | 66            | 11 / 4 of 36               |
| capture1 | 342          | 16 (5 %, ~3/h)     | 24            | 3 / 3 of 36                |

`ffprobe` of capture3's chunks in hours 3, 4, 6 and 7: 11 of 24 are 540 s or 660 s instead of
600 s (e.g. `3/chunk_10min_1` 540.0 s, `3/chunk_10min_2` 660.1 s). Each duration is exactly
60 s × the number of appends the journal shows for that chunk. No footage is lost: a minute
recorded in one chunk's window is appended to the next chunk. But the player maps wall time
linearly into the file, so a seek in a 540 s or 660 s chunk lands up to a minute off.

## Root cause

`process_hot_storage` (`backend_host/scripts/hot_cold_archiver.py`) named each 1-minute batch
after the clock at merge time:

```python
current_minute = datetime.now().minute
minute_slot = current_minute % 10            # 1min_<slot>.mp4 / .mp3
...
now = datetime.now()
hour, chunk_index = calculate_chunk_location(now)   # chunk_10min_<k>.mp4 / .mp3
```

The batch itself is the oldest 150 HLS segments (60 s), merged whenever 150 exist
(`merge_progressive_batch`). The fast loop runs every 30 s plus the cycle's own work, which on
vpt-pi1 is 2-25 s across the four captures, so merges happen at cycle times 32-55 s apart:
about one every 60 s on average (342 in 5.8 h), but in steps of one or two cycles. Two merges
can fall in the same clock minute (capture3 at 07:56:15 and 07:56:59 → slot 6 twice) and none in
the next (slot 7 never written). The chunk index comes from the same clock, so
a chunk gets 11 batches when the extra merge falls in its window and the next gets 9. The
transcript service files each `1min_N.mp3` by the clock too
(`transcript_accumulator.py` `_handle_mp3_event`), with N as the minute offset in the chunk.

This is not [BUG-0230](BUG-0230-2026-10-02-archive-chunks-lose-whole-minutes.md): that fix (ffmpeg
deleting segments mid-merge) is in place and the merges now all succeed. With every merge
succeeding, the clock naming became the visible defect. It is the root of
[BUG-0032](BUG-0032-2026-07-28-report-video-cold-chunk-time-shift.md)'s up-to-60 s shift at a
chunk's start too.

## Fix

- `hot_cold_archiver.py`: new `batch_minute(segment_mtimes, count)` gives the minute the batch
  was recorded in: the minute of its middle segment's mtime (the batch is the oldest `count`
  segments by mtime, as `merge_progressive_batch` picks them). Consecutive batches are 60 s of
  media apart, so their middles advance exactly one minute each. The slot and the chunk
  (hour, index) both come from that minute, not from `datetime.now()`.
- Both 24 h "is this yesterday's chunk?" checks (MP4 and MP3) now use only the file's age (written
  in the last 10 min = this window, since the path already names hour and chunk). Before, they
  also required the file's mtime to fall in the chunk's window, which the last minute of a chunk
  no longer does (it is appended after the clock left the window): the chunk would have been
  overwritten.
- `transcript_accumulator.py` `_handle_mp3_event`: `1min_N.mp3` is filed under the latest minute up to now with
  `minute % 10 == N`, instead of the current clock's chunk. Otherwise slot 9, which arrives after
  the chunk ended, would land in the next chunk.

## Verification

- `tests/backend_host/test_archiver_minute_slot.py` simulates ffmpeg (0.4 s segments) and a fast
  loop with 30 s + 2-25 s cycles for 3 h: the batch minute advances one slot per merge, every
  closed chunk gets exactly 10 batches, and the old merge-clock naming repeats and skips slots
  for the same schedule.
- After a host deploy (`vpt-archiver` and `vpt-transcript` restart): in the journal, each
  capture's `Created 1min MP4 (slot N)` sequence goes 0..9 without a repeat or skip, and the first
  chunks closed after the restart are 600 s by `ffprobe`
  (`/var/www/html/stream/captureN/segments/<HH>/chunk_10min_*.mp4`).

## Follow-up

The duplicates are gone, but under load whole minutes were still lost (no repeat, a slot jump):
a late cycle found hot at ffmpeg's 300-segment ceiling, where every unpinned merge failed. Fixed in
[BUG-0291](BUG-0291-2026-10-04-a-late-archiver-cycle-lost-a-whole-minute.md).
