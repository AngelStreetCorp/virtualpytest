# BUG-0604 — vpt-windows desktop audio: capture stalled, ffmpeg restarted every 65 s, 425 MB `raw.pcm`, and no audible sound

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0604                                                     |
| Reported  | 2026-10-17                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / Windows audio                                 |
| Fixed in  | build 90145 |
| Commit    | `shortHash` (or "TBD")                                       |

---

## Symptom

The `Host_Windows` audio track (the chip on the VNC tile, `device1_audio`) was
effectively dead while the task reported `Running`:

- `C:\virtualpytest\stream\device1_audio\raw.pcm` was frozen at **425 492 480
  bytes**, last written at 20:48:50, while its writer process was still alive.
- `vpt-windows-audio.log` showed `starting ffmpeg` every **~65 s**.
- The audio HLS playlist kept being rewritten (segment numbering reset to 0), so
  a client saw a discontinuity and re-fetched.
- Extracting the segments showed **silence**: `mean_volume: -90.3 dB`,
  `max_volume: -80.8 dB`, even while `C:\Windows\Media\Alarm01.wav` was played
  in session 1.

## Root cause

Four independent faults in the BUG-0597 pipeline, each hidden by the others:

1. **The task ran as SYSTEM in session 0.** `vpt-windows-audio` was registered
   with `/ru SYSTEM`. A session-0 service has no audio rendering endpoint;
   PortAudio could open `Mixage stéréo` but the endpoint produced digital
   silence. Also, because the task ran as SYSTEM, the pidfile in
   `C:\ProgramData\virtualpytest\logs` was SYSTEM-owned; the later attempt to run
   it as the console user died silently with `UnauthorizedAccessException` on
   `Set-Content` (exit 1, no log line).
2. **Stereo Mix only loops the Realtek analog mix.** The machine's default output
   is *Realtek Digital Output*, and a USB wireless headset is also present.
   `Mixage stéréo (Realtek HD Audio Stereo input)` therefore records nothing
   audible for anything played on the default endpoint.
3. **A rolling file is read from byte 0 after every restart.** `ffmpeg -re -i
   raw.pcm` replays the whole history each time it starts; combined with
   `-use_wallclock_as_timestamps 1` (which gives `-re` nothing to pace against)
   ffmpeg consumed the file at disk speed, reached EOF in ~65 s and was
   restarted in a loop. The file also grows ~14 GB/day and is never truncated
   (truncating it under a live writer produces a sparse file with a hole).
4. **The wrapper only checked process liveness.** When PortAudio stopped calling
   its callback (device disappeared, sound service restarted), the Python
   process stayed alive and silent, so nothing ever restarted the capture.

## Fix

`backend_host/scripts/run_audio_stereo_mix.ps1` (rewritten) and
`backend_host/scripts/capture_audio_stereo_mix.py` (new default capture mode):

- **One OS pipe, no file.** The wrapper writes a small `audio_pipeline.cmd`
  (`python capture | ffmpeg -f s16le -i -`) and starts it with `cmd /c`. No
  `raw.pcm`, no replay, no growth, no `-re` (a pipe is paced by the producer).
  `%` in the HLS template is written `%%09d` because the line lives in a `.cmd`.
- **WASAPI loopback of the default speaker** via `soundcard`
  (`VPT_AUDIO_CAPTURE_MODE=loopback|stereo_mix|auto`, default `auto`). It follows
  whatever the session plays, on any endpoint (Realtek analog or digital, HDMI,
  USB headset). The Stereo Mix/sounddevice path is kept as a fallback.
- **Stall watchdog.** The loop watches the playlist's `LastWriteTimeUtc`/size and
  restarts the pair (with `taskkill /T`) after `VPT_AUDIO_STALL_SECONDS`
  (default 20 s) without an update — the case liveness checks miss.
- **Session 1, console user.** The task runs as the logged-on user with an
  interactive token, which WASAPI loopback requires.
- **Logs and pidfile in `C:\virtualpytest\logs`** (`%VIRTUALPYTEST_LOGS%`), not
  `C:\ProgramData\virtualpytest\logs` (SYSTEM-owned). A pidfile that cannot be
  written is now a warning, never a fatal error.
- **Pidfile stores `pid|start-ticks`** so a recycled PID (a stale file whose
  number now belongs to the new process) is not mistaken for a live sibling.

`setup/local/windows/backend_host/install_host_windows.ps1` registers the task
from an **XML definition** (LogonTrigger + InteractiveToken for the console user,
`Enabled=true`): `schtasks /create /ru <user> /it` left the task in the Disabled
state on Win11. `soundcard` is now in `backend_host/requirements.txt`.

## Verification

- `vpt-windows-audio` is `Running`, principal `joach` / `Interactive`, all
  processes in session 1 (`powershell` → `cmd` → `python` → `ffmpeg`).
- Playlist mtime advances every ~2 s; segment numbers increase; no `raw.pcm` in
  the folder (the 425 MB file was removed).
- `C:\Windows\Media\Alarm01.wav` played in session 1 →
  `mean_volume: -26.4 dB`, `max_volume: -13.4 dB` on the segments produced at
  that moment (was ‑90.3 dB / ‑80.8 dB before).
- The audio playlist still answers `200` on
  `http://127.0.0.1:6109/host/stream/device1_audio/segments/output.m3u8`.
- No `starting ffmpeg` repeats in the log after the switch (the old log filled
  with one per minute).
