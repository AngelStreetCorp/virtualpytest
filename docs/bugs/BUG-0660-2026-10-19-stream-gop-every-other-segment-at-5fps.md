# BUG-0660 — 5 fps live streams had a keyframe in every other segment

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0660                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / stream encoder                                |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On `/device-control` filtered on STB, the grid of 4 tiles took several seconds to show
video. The browser console showed, per tile, `fragParsingError: Found no media in
fragment`, then a fatal `bufferAppendError`, `recoverMediaError()`, sometimes
`swapAudioCodec()`, and `play() request was interrupted by a new load request`.

## Root cause

The STB captures on vpt-pi1 and vpt-mf1 run at 5 fps. `run_ffmpeg.sh` set the live
stream GOP to a fixed `4` for any rate ≤ 10 fps (it assumed 10 fps). At 5 fps a 4-frame
GOP is 0.8 s, while HLS segments are 0.4 s (`split_by_time`). So segments alternated:
one ~24 KB with SPS/PPS + keyframe, the next ~4 KB with P-frames only (`ffprobe`:
`non-existing PPS 0 referenced`, `no frame!`). hls.js starts at the live edge; half the
time that is a keyless segment, which it cannot decode, so the tile goes through the
error / recover / reload path before the first frame.

## Fix

`backend_host/scripts/run_ffmpeg.sh`: `stream_gop = round(stream_fps × 0.4)`, at least 1
— 2 at 5 fps, 4 at 10 fps (unchanged), 8 at 20, 12 at 30, 24 at 60 (unchanged).
Every 0.4 s segment now starts on a keyframe.

The VNC (x11grab), scrcpy and network-camera writers computed `fps × 2 / 5` with integer
math, which is `0` at 2 fps (vpt-mf1 host VNC ran `keyint=0`). They now round the same way
and never go below 1.

## Verification

After the host deploy, download the last segments of an STB stream and `ffprobe` each:
every one decodes (320x180, 2 frames), no `non-existing PPS`. The STB grid shows video
without `fragParsingError` / `bufferAppendError` in the console.
