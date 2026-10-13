# BUG-0291 — A late archiver cycle lost a whole minute instead of archiving it on the next cycle

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0291                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (live on vpt-pi1 since 2026-10-04 12:16)               |
| Severity  | Medium                                                       |
| Area      | backend_host / archive                                       |
| Fixed in  | Unreleased                                                   |
| Commit    | `this commit`                                                |

---

## Symptom

After the [BUG-0277](BUG-0277-2026-10-04-archiver-wrote-a-minute-slot-twice-and-skipped-the-next.md)
fix, no minute slot was written twice any more, but under load whole minutes were still missing.
On vpt-pi1 (Raspberry Pi 5, load 10-18 on 4 cores), between the BUG-0277 restart at 09:48:20 and
12:16 (~148 min), the `Created 1min MP4 (slot N)` sequence per capture:

| capture  | minutes | repeats | skip events | minutes missing |
|----------|--------:|--------:|------------:|----------------:|
| capture1 | 137     | 0       | 2           | 4               |
| capture3 | 134     | 0       | 4           | 8               |
| capture4 | 132     | 0       | 5           | 9               |

Each lost minute leaves its 10-min chunk a minute short: capture3's `11/chunk_10min_3`, `_4` and
`_5` are ~540 s. The player maps wall time linearly into the chunk, so seeks in it land up to a
minute late.

## Root cause

ffmpeg keeps 300 HLS segments (~120 s) on disk and deletes the oldest past that
(`-hls_list_size 150 -hls_delete_threshold 150`, `backend_host/scripts/run_ffmpeg.sh`). The
archiver merges the oldest 150 (one minute) once 150 exist. So after a minute is complete it has
~60 s, plus whatever was left after the last merge, before ffmpeg starts deleting it. Three things
turned a late cycle into a lost minute:

1. **The next cycle started 30 s after the previous one ended**
   (`hot_storage_loop`, `time.sleep(HOT_THREAD_INTERVAL)` after the work,
   `backend_host/scripts/hot_cold_archiver.py:2300` before the fix). The four captures are
   processed one after the other; one 1-min merge + 10-min append can take 14 s on this Pi, so the
   gap between two cycles of the same capture was 46 s median, 67-73 s p90 and up to 114 s.
2. **Once hot reached 300, the merge failed every time** (`merge_progressive_batch`,
   `shared/src/lib/utils/video_utils.py:286-293` before the fix). At the ceiling ffmpeg deletes the
   oldest segment every 0.4 s, which is exactly the file the concat opens first:
   `Impossible to open '.../segment_000180930.ts'`, then the BUG-0230 retry of the 149 left fails on
   the next one (`segment_000180931.ts`). Each failed cycle let ffmpeg delete another 30-45 s of the
   minute. Every skip in the window above follows cycles logged at `Segments available: 300` with
   `1min MP4 not created`: e.g. capture3 failed at 10:28:18, 10:28:53, 10:29:27 and 10:30:10, then
   archived slot 9 at 10:30:54 (slots 5-8 lost); capture4 failed four cycles from 10:21:39 (slots 8-1
   lost).
3. **One minute per cycle** (`process_hot_storage` ran one merge per call, `hot_cold_archiver.py:1861` before the fix): a cycle that found two
   minutes waiting archived one and left the next at the edge of ffmpeg's ceiling for another cycle.

Nothing logged which minute was lost; it showed only as a slot jump.

## Fix

- `video_utils.merge_progressive_batch`: the batch is hard-linked into a `.pin_<output>/` folder
  next to the segments before the concat, and the concat reads the links. ffmpeg deleting an
  original no longer breaks the merge; the originals are removed after a successful merge, the
  links always. A file already gone before it is linked is skipped (logged as "vanished before the
  merge").
- `hot_cold_archiver.py` `hot_storage_loop`: the next cycle starts `HOT_THREAD_INTERVAL` after this
  one started, at least 5 s after it ended (`hot_cycle_sleep`), instead of 30 s after it ended.
  A light cycle still runs every ~30 s; a loaded one no longer adds its work on top of 30 s.
- `process_hot_storage` calls the new `archive_hot_minute` (the former body: merge, MP3, append)
  until no full minute is left waiting, oldest first, up to `MAX_MINUTES_PER_CYCLE = 3`. Steady
  state is one pass, as before.
- After each merge, a gap since the capture's previous batch minute is logged as a warning that
  names the lost minutes: `[capture3] Lost 2 minute(s) 10:06-10:07: their segments left hot before
  they were archived (or were never recorded)`.
- BUG-0277's naming (slot and chunk from the batch's middle segment mtime) is unchanged.

Limit: a capture whose cycle comes more than ~60-120 s late (depending on what was left after the
previous merge) can still lose part of a minute, and the warning names it. More headroom needs
ffmpeg to keep more segments (`-hls_delete_threshold` in `run_ffmpeg.sh`, a `vpt-stream` restart).

## Verification

- `tests/backend_host/test_merge_progressive_batch.py` (real ffmpeg): the writer deleting the
  oldest original during the concat still yields the full batch in one merge (failed before: the
  minute came out short after a second attempt); a file gone before the pin is skipped.
- `tests/backend_host/test_archiver_minute_slot.py`: the real `process_hot_storage` loop over a
  simulated ffmpeg (300-segment ceiling) for 3 h, with one cycle in eight 40-60 s late: no minute
  lost and slots step by exactly one; the old schedule (30 s after the work, one minute per cycle,
  unpinned merges failing at the ceiling) loses minutes. `lost_minutes` names the gap.
- vpt-pi1, hot-patched (`hot_cold_archiver.py`, `video_utils.py`) and `vpt-archiver` restarted at
  12:16:11, load ~9-10. Same 31-minute length before and after:

  | capture  | 11:45-12:16 (old): minutes / repeats / missing | 12:16-12:47 (fixed): minutes / repeats / missing |
  |----------|-----------------------------------------------:|-------------------------------------------------:|
  | capture1 | 31 / 0 / 0                                     | 32 / 0 / 0                                       |
  | capture3 | 27 / 0 / 4 (12:11-12:14 four failed cycles at 300) | 32 / 0 / 0                                   |
  | capture4 | 31 / 0 / 0                                     | 31 / 0 / 0                                       |

  The case that used to lose minutes happened once: capture1's cycle at 12:37:14 came 67 s after the
  last and found 300 segments. The pinned merge succeeded (slot 5) and the catch-up archived slot 6
  in the same cycle. No `Lost ... minute(s)` warning was logged. `ffprobe` of the chunks closed
  after the restart (`segments/12/chunk_10min_2` and `_3`) is 600.0-600.06 s on capture1, 3 and 4;
  capture3's `12/chunk_10min_1` (12:10-12:20, before the restart) is 420 s.
- `capture_switch1` (not an A/V device: ~1.5 KB segments that ffmpeg detects as `mpeg` with a low
  score) fails every merge before and after the fix. Unrelated to this bug.
