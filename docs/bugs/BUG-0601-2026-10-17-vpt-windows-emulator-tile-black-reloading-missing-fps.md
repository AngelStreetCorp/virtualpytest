# BUG-0601 — vpt-windows `Mobile_Emulator` tile black and reloading after the `.env` lost `DEVICE2_VIDEO_FPS`

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0601                                                     |
| Reported  | 2026-10-17                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / Windows pipeline                              |
| Fixed in  | build 90145 |
| Commit    | `shortHash` (or "TBD")                                       |

---

## Symptom

On `/device-control` (server `vpt-pi4`) the `Mobile_Emulator` tile of host
`vpt-windows` showed a black player that reloaded every few seconds. The host
was `online`, the Android emulator was running and awake
(`sys.boot_completed=1`, `mWakefulness=Awake`), and
`C:\virtualpytest\stream\device2\emulator_frames\latest.png` was a fresh, valid
1.25 MB PNG written every 0.2 s. No ffmpeg process existed on the host.

## Root cause

Three layers, each invisible on its own:

1. **The `.env` was rebuilt at 19:37 and lost a key.** `backend_host/src/.env`
   was rewritten after a foreground debugging round (the previous content, in
   fact the untouched `.env.example`, was kept as
   `.env.broken_20261017_193757`: `HOST_NAME=MyHost`, all `XDEVICE*` template
   lines). The rebuilt file had the host and device blocks but no
   `DEVICE2_VIDEO_FPS`.
2. **An empty FPS kills `run_ffmpeg.ps1` before ffmpeg starts.** The
   `imagefile` branch of `Start-Grabber` builds the argument array with
   `-framerate $inputFps` and `-r $inputFps`, where `$inputFps` is
   `DEVICE<n>_VIDEO_FPS`. A missing key makes that element the empty string,
   and `Start-Process -ArgumentList` rejects the whole array:
   `Impossible de valider l'argument sur le paramètre «ArgumentList». L'argument
   est Null ou vide.` The wrapper exits 1 (`vpt-stream` `LastTaskResult: 1`).
3. **A dead ffmpeg leaves a playlist hls.js loops on.** ffmpeg writes
   `output.m3u8` with `-hls_flags delete_segments+program_date_time`. On exit
   the playlist still lists 375 segments and ends with `#EXT-X-ENDLIST`, while
   `+delete_segments` has already removed all but the last handful of `.ts`
   files. The dashboard loads that stale playlist, 404s on the missing
   segments, hits a fatal HLS error and retries — a black tile that reloads.

A fourth trap hid the evidence: the machine-wide `VIRTUALPYTEST_LOGS` was set to
`C:\ProgramData\chocolatey`, so `stream_wrapper.ps1` appended its log there
instead of `C:\virtualpytest\logs`; the expected log looked stale since 09:21.

## Fix

Host (`vpt-windows`):

- `DEVICE2_VIDEO_FPS=5` restored in `backend_host/src/.env` (backup:
  `.env.bak_20261017_blackscreen`), `vpt-stream` restarted.

Repo:

- `backend_host/scripts/run_ffmpeg.ps1` defaults a missing `DEVICE<n>_VIDEO_FPS`
  to `5` and logs a warning, so a lost env key can never pass an empty element
  to `Start-Process` again.

## Verification

- `output.m3u8` advances every ~0.8 s, no `#EXT-X-ENDLIST`, new
  `segment_*.ts` files appear.
- A frame extracted from the newest segment is a real portrait 360×640 Android
  screen (10k+ colours, not black).
- Headless browser on `/device-control?auto_signed=…` (server `vpt-pi4`):
  `<video>` in the `Mobile_Emulator` card reaches `readyState 4`, 360×640,
  `currentTime` advances 2.04 s over 3 s, no HLS 4xx and no failed segment
  request. Tile screenshot shows the Pixel home screen.
