# BUG-0285 — Every stream restart emptied the device's captures, and no new frame came for up to 26 s

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0285                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / stream (`run_ffmpeg.sh`)                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Each per-device ffmpeg restart in `vpt-stream` emptied that device's `hot/captures`
folder, and no new capture jpg appeared for several seconds. A restart happens on a live
source switch (`/host/av/loadVideo`, `/host/av/setUrl`), an SD/HD switch, the end of a
looping HLS playlist, and watchdog restarts. During the gap vpt-monitor had no frame to
analyse and the UI lost its latest frames.

Measured on a Pi 5 host, local-video device, `loadVideo` switch, before the fix:

| Switch to | Captures folder | Last old capture → first new capture |
|---|---|---|
| `smoke.mp4` (keyframe every 25 s) | empty for > 26 s | ~30 s |
| `big_buck_bunny_360p.mp4` | empty for ~1 s | ~5 s |

The ffmpeg log showed it encoding the whole time (`time=` advancing), with nothing written
to disk.

## Root cause

Three causes, all in `backend_host/scripts/run_ffmpeg.sh` (line numbers before the fix):

1. **The restart deleted every capture.** `start_grabber` ran
   `find "$output_captures" … -delete` and the same for thumbnails (lines 1039–1040)
   on every start. The comment said it prevented a RAM leak, but the archiver's
   `cleanup_hot_files` already keeps only the newest N captures, so nothing leaks. Counter
   continuity does not need it either: `cap_start = seg_start × captures_per_segment`, and
   the previous run's captures are numbered below it. Only captures at or above `cap_start`
   are a problem, because the new run overwrites them or they sit ahead of it.

2. **The first frame waited for the source's second keyframe.** File and HLS inputs ran with
   `-fflags +nobuffer+genpts+flush_packets` (line 1495). With `+nobuffer`,
   `avformat_find_stream_info` discards the packets it read while probing instead of passing
   them to the decoder. Those packets include the first keyframe, so the H.264 decoder outputs
   nothing until the next one. ffmpeg runs under `-re`, so that wait is in real time: no capture
   and no segment for one GOP, then a burst. Measured with the same command run on its own,
   time to the first capture:

   | Source | With `+nobuffer` | Without |
   |---|---|---|
   | `smoke.mp4` (keyframes at 0 / 25 s) | 26.1 s | 1.1 s |
   | `smoke.mkv` (keyframes at 0 / 8.3 s) | 9.2 s | 0.9 s |
   | HLS bipbop | 4.1–5.3 s | 1.1–1.2 s |
   | `big_buck_bunny_360p.mp4` | 1.2 s | 0.9 s |

   `-stats` showed `dup=250` for the first 25 s of `smoke.mp4`: the output filter had to fill
   the time with copies of a single frame. `+genpts` and `-re` were not involved (dropping
   `+genpts` alone changed nothing). `+nobuffer` gives no latency gain on a file or an HLS
   playlist, because both are read whole and paced by `-re`.

3. **Phantom grabbers killed every device on a source switch.** `get_rtsp_url_state` /
   `get_video_path_state` (lines 98, 113) look up a capture dir with
   `grep -F "${capture_dir},"`. For an unset `DEVICEn_VIDEO_CAPTURE_PATH` that becomes
   `grep -F ","`, which matches the first line of the override conf. Once vpt-stream started
   while `active_video_path.conf` or `active_rtsp_url.conf` had any entry, every unused slot
   5..30 became a grabber with capture dir `""`. On the next `loadVideo`/`setUrl`, each of
   those "changed source", and `kill_all_ffmpeg_for_device ""` ran
   `pkill -9 -f "/captures"`, which killed the ffmpeg of **every** device, including the one
   just restarted. Those devices then waited up to 30 s for the watchdog. If a device was killed
   before it wrote its first segment, it also restarted at `seg_start = 0`: its capture counter
   went back to 0, which breaks the monotonic numbering vpt-monitor relies on.

The restart path also added fixed sleeps on every switch: `sleep 1` in
`kill_all_ffmpeg_for_device` (line 459) and `sleep 2` in `check_source_changes` (line 891).

## Fix

`backend_host/scripts/run_ffmpeg.sh`:

- New `prune_from_number`: on restart, delete only captures and thumbnails numbered
  `>= cap_start`. Older frames stay until the archiver rotates them out. If segments reset
  to 0, then `cap_start` is 0 and everything is deleted, as before. Segments are still
  pruned as before.
- File and HLS inputs use `-fflags +genpts+flush_packets`. RTSP keeps `+nobuffer` (a live
  source, where it cuts latency). The v4l2 MJPEG input is unchanged, since every MJPEG frame
  is a keyframe.
- `get_rtsp_url_state` / `get_video_path_state` return nothing for an empty capture dir, so
  no phantom grabbers are created.
- `kill_all_ffmpeg_for_device` polls for the killed ffmpeg to exit (max 1 s, in 0.1 s
  steps) instead of `sleep 1`. `check_source_changes` drops its `sleep 2`: the kill is already
  confirmed, and file and network sources have no device node to release.

Steady-state ffmpeg arguments and CPU are unchanged. The only change to ffmpeg's arguments
is one fewer `-fflags` bit for file and HLS inputs.

`docs/agent/devices/STREAM.md` §7 was updated to match.

## Verification

Same Pi 5 host, local-video device, `loadVideo` switch, newest capture mtime sampled every
0.25 s, after the fix:

| Switch to | Captures folder (min files) | Last old → first new capture | Numbering |
|---|---|---|---|
| `smoke.mp4` | 401 (never empty) | 1.27 s | `…404` → `405` |
| `big_buck_bunny_360p.mp4` | 485 (never empty) | 1.57 s | `…484` → `485` |

The kill now takes ~0.2 s, and the new ffmpeg writes its first capture ~1 s after it
starts. After the restart vpt-stream lists 5 grabbers (`host`, `device1..4`), down from 31,
and a switch restarts only the target device. The other devices' ffmpeg PIDs are untouched.

To re-check: POST `/host/av/loadVideo` with `{"device_id":"deviceN","url_or_path":"<file>"}`.
Then watch `ls <capture>/hot/captures | wc -l` and the newest file's mtime. In the vpt-stream
journal you should see one `Source change detected` for the target device only, followed by
`Continuous numbering: … captures@<last+1>`.
