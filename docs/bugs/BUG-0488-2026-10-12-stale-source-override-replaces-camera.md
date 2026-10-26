# BUG-0488 — A leftover source override replaced a camera's stream with an old video file

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0488                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / vpt-stream                                    |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On vpt-pi4 the camera tile (`DEVICE1_MODEL=camera`, `DEVICE1_VIDEO=/dev/video0`, capture dir
`capture1`) played `big_buck_bunny` instead of the camera. ffmpeg was started on the video file,
not on `/dev/video0`.

## Root cause

TASK-31 runtime source switches persist in `/var/www/html/stream/active_video_path.conf`
(written by `VideoFileStreamController.load_or_download`, route `/host/av/loadVideo`) and
`active_rtsp_url.conf` (`RTSPStreamController.set_url`, route `/host/av/setUrl`). Both files are
keyed by capture dir only and survive `.env` edits. `capture1` had once belonged to a
`local_video` device; after the `.env` gave `capture1` to the camera, `run_ffmpeg.sh` still
applied the old `capture1,…big_buck_bunny…` line to whatever device owned that dir — at startup
and in the 1 s source watcher (`source_spec_for` / `check_source_changes`). The host (VNC) slot
had the same exposure.

## Fix

`backend_host/scripts/run_ffmpeg.sh`: each device honours only the override its model's
controller writes — `active_rtsp_url.conf` for `rtsp_video` / `tello` (rtsp_stream),
`active_video_path.conf` for `local_video` (video_stream). Any other model (camera, HDMI STB,
android_tv, …) and the host slot ignore both files; a leftover line is logged at startup
("ignoring leftover source override") and never replaces the source. The watcher uses the same
per-device rule (`OVERRIDE_KIND`).

## Verification

On vpt-pi4: add `/var/www/html/stream/capture1,<some .mp4>` to `active_video_path.conf`, restart
`vpt-stream`; the log shows the "ignoring leftover" line and the capture1 ffmpeg still reads
`/dev/video0`. Touching the file again does not restart capture1.
