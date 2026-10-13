# BUG-0463 — Archiver rewrites the 10-min chunk on the SD card every minute and stalls the Pi

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0463                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / archiver                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

vpt-pi1 (Raspberry Pi 5, root on SD card) sits at load 10–13 with `wa` up to 73% and 9–15
tasks blocked; the stream UI stutters. Worse when a capture is on HD. `scripts/collect_host_load.sh
vpt-pi1 180` showed SD write latency bursts of 2.5–8.4 s (`aqu` up to 208, `util` ~100%) and
`hot_cold_archiver.py` writing 241 MB in 180 s with all captures on LOW.

## Root cause

`archive_hot_minute()` in `backend_host/scripts/hot_cold_archiver.py` appended each minute to the
current `segments/<hour>/chunk_10min_<i>.mp4` by re-muxing the whole chunk (`merge_video_files`
concat into `.tmp`, then faststart's second pass) on cold storage. Over one chunk that writes ~110x
one minute of video. The 1-min MP4 input was also written to `segments/temp/` on the card, and the
10-min MP3 was copied whole before each append. At HD (1500k, ~11 MB/min) that is ~2 MB/s per
device, which this card stalls under.

## Fix

- The open chunk is built in RAM (`/dev/shm/vpt-archiver/<captureN>/`); its cold path is a
  symlink to it, so the report-video builder, ffprobe and nginx read the same path as before.
  When the next chunk starts (or the device is idle 11 min) it is copied to cold storage once and
  the symlink is replaced by the real file. No room in RAM (checked before every merge against
  `/dev/shm` free space and `MemAvailable`): the chunk is written and appended on cold as before.
- The host stream route (`host_stream_routes.py`) confines files to the stream tree by realpath;
  it also accepts `ARCHIVE_STAGE_ROOT` (`storage_path_utils.py`), or the open chunk is a 404 in
  the archive player. Found on the first vpt-pi1 deploy.
- The 1-min MP4 is built in the same RAM stage.
- The 10-min MP3 is appended in place.
- New host `.env` key `ARCHIVE_VIDEO` (default `true`): `false` turns the 24h review buffer off
  (no cold video at all); the host reports it in `system_stats.archive_video` and the stream
  modal's **Last 24h** button is disabled.
- Trade-off: a host reboot loses the open chunk (up to 10 min), like the hot segments.
  Startup drops the dangling symlinks before rebuilding the manifest.

## Verification

- `tests/backend_host/test_archiver_ram_stage.py` (8 cases: growth behind the symlink, single
  write on the next chunk, no-room and room-lost paths, reboot, idle device, previous-day slot).
- On vpt-pi1 with real ffmpeg and real 1-min MP4s in a scratch dir: chunk duration via the
  symlink 60 → 120 → 180 s; on the next chunk the 180 s file was written to cold in 0.13 s.
- After deploy: `scripts/collect_host_load.sh vpt-pi1 180` — archiver `write_bytes` per window
  should drop several-fold at the same quality, and the SUMMARY line should lose most
  `w_await>100ms` seconds.
