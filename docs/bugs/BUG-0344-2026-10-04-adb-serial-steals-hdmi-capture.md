# BUG-0344 — An ADB serial took over a device's HDMI capture, and the ADB grabber never started

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0344                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed                                                        |
| Severity  | High - a device lost all video (stream, captures, thumbnails) after a `vpt-stream` restart |
| Area      | `backend_host/scripts/run_ffmpeg.sh` (grabber selection)    |
| Fixed in  | build 90145 |

---

## Symptom

After the TASK-48 `vpt-stream` restart (2026-10-04 19:04 CEST), vpt-pi3 device1 (FireTv, `android_tv`, HDMI grabber
`/dev/video2`) stopped producing frames. The journal showed `Starting grabber for device1 (source: ADB)`, then
`ERROR: Unknown source type for ADB`, then the watchdog restarting it every ~40 s (`stale ffmpeg log_age=42s`).
Before the restart it had been streaming over HDMI for hours: the `.env` had gained `DEVICE1_ADB_SERIAL` (for ADB
remote control) since the previous `vpt-stream` start, and only a restart reads the `.env`.

## Root cause

Two defects in the grabber table built from the `.env`:

1. `DEVICE<N>_ADB_SERIAL` "took priority over VIDEO": any device with an ADB serial was switched to scrcpy video,
   even an Android TV whose serial exists only for control and whose video comes from an HDMI grabber.
2. The ADB entry was stored as `ADB|<serial>|<path>|<fps>`, but `start_grabber` reads field 1 as the source and
   types it with `detect_source_type`: the source became the literal `ADB`, which is unknown, so the scrcpy branch
   could never run.

## Fix

`DEVICE<N>_VIDEO` now wins; scrcpy is the video source only for a device with no `VIDEO` (emulator, phone on USB).
The ADB entry is stored as `<serial>|null|<path>|<fps>` with `STREAM_TYPE[device<N>]=ADB`, so `start_grabber` takes
the scrcpy branch with the real serial.

Not fixed here: the scrcpy branch writes no `/tmp/ffmpeg_output_device<N>.log`, so the stale-log watchdog may restart
a scrcpy grabber; no host currently uses scrcpy video, so it is unverified.

## Verify

On vpt-pi3 after deploy + `vpt-stream` restart: journal shows device1 started from `/dev/video2`, and
`/var/www/html/stream/capture1/hot/thumbnails/latest.jpg` is less than 1 s old.
