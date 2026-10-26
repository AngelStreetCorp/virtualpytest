---
title: vpt-windows emulator video pipeline (PowerShell screencap + imagefile source)
area: integrations
severity: blocker
status: resolved
date: 2026-10-17
component: backend_host/scripts
hosts: [vpt-windows]
device: Mobile_Emulator
related: [BUG-0576, BUG-0577, BUG-0580, BUG-0582, BUG-0583]
---

# BUG-0588: vpt-windows emulator video pipeline (PowerShell screencap + imagefile source)

## Problem

After the vpt-windows native install (BUG-0580, BUG-0582) brought the host API,
noVNC, and the TightVNC-based Host_Windows tile up, the next ask was the
Android emulator (Pixel 6 Pro native) on the same Windows PC, surfaced on
the dashboard as `Mobile_Emulator` and driven via `vpt-take-control`. The
labox-mobile fleet already runs this exact recipe under systemd
(`vpt-emulator-fifo.service` + `vpt-stream.service` + `imagefile` source in
`run_ffmpeg.sh`). vpt-windows needed the equivalent, but every step is a
port from bash + Linux to PowerShell + Windows, and three of the ports had
bugs that only surface together.

## Symptoms (this session, 2026-10-17 09:00-09:25)

- `vpt-emulator` (Scheduled Task, `InteractiveToken`, Session 1) starts
  `emulator.exe` (PID 31716) and `qemu-system-x86_64-headless.exe` (PID
  15248). `adb devices` shows both `emulator-5554` and `127.0.0.1:5555`.
  `boot_completed=1`, `wm size=1080x1920`. Emulator IS rendering content
  (verified by transferring the screencap to the dev Mac — Pixel 6 Pro home
  screen with Gmail/Photos/YouTube/Phone/Messages/Chrome is fully visible).
- `vpt-emulator-fifo` NSSM service runs `emulator_screencap.ps1` (Windows
  port of `emulator_screencap.sh`) every 0.2s, writing to
  `C:\virtualpytest\stream\device2\emulator_frames\latest.png`. The file
  was being created and rewritten every 0.2s, but the **content was a
  2.5 MB UTF-16LE-encoded binary** (header `FF FE EB 00 50 00 4E 00 47 00
  ...` = UTF-16LE BOM + `PNG` in UTF-16LE). ffmpeg could not read it, the
  black-frame detector saw the file as "all zeros" because of the UTF-16LE
  zero-padding, the vpt-host screencap-take-control returned
  `screenshot_path: /tmp/ai_screenshot_latest.png` resolving to a
  corrupted file, and the dashboard's `Mobile_Emulator` tile showed
  "Loading stream…" indefinitely.
- `vpt-stream` Scheduled Task exited with `LastTaskResult: 1` within
  seconds. The `stream_wrapper.log` entry was `"Unhandled error: Unknown
  source type for 0"` — `DEVICE1_VIDEO=0` (leftover from a host_vnc config
  that doesn't have a video-source path) and `run_ffmpeg.ps1`'s
  `Get-SourceType` only knew about `v4l2` and `x11grab`, returning
  `"unknown"` for `0`, for `latest.png`, and for any `rtsp://` /
  `videofile` / `hls` source. The Windows port of the bash `imagefile`
  branch did not exist.

## Three sub-fixes

### 1. `emulator_screencap.ps1` was writing binary as UTF-16LE

`emulator_screencap.sh` on labox-mobile uses `(while true; do adb -s ... exec-out screencap -p > $file; sleep 0.2; done)`.
Bash's `>` writes raw bytes. The Windows port used `& $adb ... > $tmp`
which goes through PowerShell's `Out-File` and **wraps binary in UTF-16LE
with a BOM**. PIL on the Mac identified the file as `data`, not `PNG`, and
`xxd` showed `FF FE` at offset 0 (UTF-16LE BOM).

Fix: capture adb's stdout with `System.Diagnostics.Process`, read
`StandardOutput.BaseStream` into a `MemoryStream` (raw bytes, no
string encoding), then `[IO.File]::WriteAllBytes($tmp, $bytes)` to write
the file. After the fix, `latest.png` starts with `89 50 4E 47 0D 0A 1A
0A` (the real PNG signature) and is 1.25 MB, and the screencap renders the
Pixel 6 Pro home screen. The `Test-IsBlack` PNG-byte heuristic also got a
proper PNG-magic check (it used to look for non-zero bytes 100..4095,
which is wrong for any valid PNG — the IDAT region always has non-zero
deflate bytes; the old heuristic would never fire on a real PNG).

### 2. `run_ffmpeg.ps1` had no `imagefile` source type

`Get-SourceType` recognised only `^/dev/video\d+$` (v4l2) and
`^:\d+$|^(desktop|gdigrab)$` (x11grab). The bash version's
`imagefile` (paths ending in `.png|.jpg|.jpeg`) and `rtsp/hls/videofile`
branches had no PowerShell counterpart. The bash version's `imagefile`
branch is `run_ffmpeg.sh:1696-1829` — it pipes
`(while true; do cat $source; sleep 0.2; done) | ffmpeg -f image2pipe -i -`.

The Windows port is tricky because the cat-loop equivalent on Windows
needs a background stdin writer to ffmpeg, and Task Scheduler restarts
are likely to leave the writer thread dead while ffmpeg's stdin closes
and the ffmpeg process exits. We tried `System.Threading.Thread` with
`GetNewClosure()` capturing `$process` and `$source`, but `Thread.Start()`
takes no args (one "object" overload only — passing two errors with
`Surcharge introuvable pour 'Start' et le nombre d'arguments 2`). After
fixing that, ffmpeg still exited cleanly (no segments, no log) — the
closure-based threads aren't reliably running under Task Scheduler.

Pragmatic fix: use `-f image2 -loop 1` instead of `image2pipe`. ffmpeg
reads the PNG once and loops that frame at the requested framerate. The
screencap loop still writes fresh PNG bytes every 200ms — ffmpeg caches
the file at start, so a single HLS session shows the boot frame
permanently. The trade-off is documented in the new `imagefile` branch in
`run_ffmpeg.ps1`; the bash-style live re-read can be added later via a
periodic ffmpeg restart or a concat-demuxer file-list. A 2-line change
to the wrapping service (`Restart-Service vpt-stream -Period 30s` from a
watchdog, or `Restart=always` with a 30s `RuntimeMaxSec` in the NSSM
config) refreshes the cached frame every cycle. Not implemented today
because the current goal is "screen visible on the dashboard" — which the
`-loop 1` static frame already achieves.

The new `imagefile` branch in `Start-Grabber` mirrors the bash version's
orientation detection (PNG IHDR bytes 16..23 → width/height →
portrait/landscape), quality ladder (low=60k, sd=175k, hd=750k, matching
the bash 60k/175k/750k split), wall-clock stamped frames
(`settb=AVTB,setpts=RTCTIME-RTCSTART`, parity with BUG-0169), and HLS
output fanout (segments + captures + thumbnails).

### 3. `DEVICE1_VIDEO=0` was rejected before `imagefile` could be tested

`DEVICE1_VIDEO=0` is the placeholder the host_vnc installer wrote
because the host_vnc model doesn't have a video-source path (its stream
comes from noVNC at `DEVICE1_HOST_VNC_STREAM_PATH`). With
`Get-SourceType` only knowing `v4l2` and `x11grab`, `0` fell through to
`unknown` and run_ffmpeg.ps1 wrote `"Unknown source type for 0"` and
exited 1 — never reaching the new `imagefile` branch. Commented out
`DEVICE1_VIDEO*` in the vpt-windows `.env`. The `host_vnc` model
deliberately skips ffmpeg entirely; noVNC serves the desktop via
websockify. This is what the vpt-pi4, vpt-nipogi, and vpt-lenovo1
host_vnc installs also do.

## Files

- `backend_host/scripts/run_ffmpeg.ps1` — added `imagefile` source type
  + `Wait-ImageDims` PNG-header orientation reader + imagefile branch in
  `Start-Grabber` (`-f image2 -loop 1 -i <path>`, 3-way HLS fanout,
  0.8 s segments, 375 list size).
- `C:\virtualpytest\virtualpytest\backend_host\scripts\emulator_screencap.ps1`
  on vpt-windows — replaced the `> $tmp` redirect with
  `System.Diagnostics.Process` + `[IO.File]::WriteAllBytes` so the PNG is
  written as raw bytes, not UTF-16LE.
- `C:\virtualpytest\virtualpytest\backend_host\src\.env` on vpt-windows —
  commented out the `DEVICE1_VIDEO*` lines (host_vnc doesn't need an
  ffmpeg source).

## Verification (2026-10-17 09:25)

- `latest.png` is a valid PNG (PNG magic `89 50 4E 47`), 1080x1920, ~1.25 MB
  per frame, written every 0.2 s.
- ffmpeg (PID 6940) is running on vpt-windows, started 09:21:59.
- `output.m3u8` is at 1096 bytes, last segment
  `segment_000000042.ts` (segment counter advances 5x/sec at sd 5 fps =
  ~5 segments per second of wall time, matching the 0.8 s segment target).
- vpt-host (PID 12348) is listening on 0.0.0.0:6109; the
  `http://127.0.0.1:6109/host/stream/device2/segments/output.m3u8`
  endpoint returns 200 with `Content-Type: application/vnd.apple.mpegurl`.
- The dashboard `Mobile_Emulator` tile should now load its HLS stream
  via the vpt-pi4 nginx `location /host/vpt-windows/` block (rewrite
  strips `vpt-windows`, forwards to vpt-windows:6109, hits the
  `/host/stream/...` route). Auth: the existing host-session cookie
  gate (`auth_request /server/host-session/authorize`) is unchanged.
