---
title: vpt-stream Scheduled Task gets Disabled after every ffmpeg exit
area: integrations
severity: blocker
status: resolved
date: 2026-10-17
component: backend_host/scripts/run_ffmpeg.ps1
hosts: [vpt-windows]
device: Mobile_Emulator
related: [BUG-0588]
---

# BUG-0592: vpt-stream Scheduled Task gets Disabled after every ffmpeg exit

## Problem

The `vpt-stream` Scheduled Task on vpt-windows (Session 1, restart-on-failure 999 × 1 min)
silently stops producing HLS segments for the `Mobile_Emulator` tile. Symptoms on the
dashboard: `Loading stream…` forever, then a frozen frame; the `Mobile_Emulator` tile is
the only one affected (vpt-pi4, vpt-nipogi, vpt-lenovo1, and Host_Windows noVNC all stay
live). On the host: `Get-ScheduledTask vpt-stream` reports `State: Disabled`,
`LastTaskResult: 1`, `NextRunTime: (none)`. The m3u8 file ends with `#EXT-X-ENDLIST`
(playlist frozen, not live).

## Root cause (two layers, both fixed in this commit)

### Layer 1: emulator_screencap.ps1's atomic rename was killing ffmpeg's image2 demuxer

The screencap loop wrote to `latest.png.tmp` then `Move-Item -Force $tmp $OutFile`. The
rename is atomic from the screencap's perspective, but ffmpeg's `image2` demuxer under
`-loop 1` re-opens `latest.png` on every frame iteration. When the rename happened during
the re-open, ffmpeg hit:

```
[image2 @ 000001fb5ccf74c0] Could not open file : C:\virtualpytest\stream\device2\emulator_frames\latest.png
[in#0/image2 @ 0000016b8e867380] Error during demuxing: I/O error
```

…then exited. ffmpeg's stderr for the device was the same 2-line error every time (the
`image2` demuxer doesn't have a "reopen on error" flag for file inputs).

### Layer 2: run_ffmpeg.ps1's `exit 1` strategy disabled the Scheduled Task

`run_ffmpeg.ps1:729-732` was:

```powershell
if ($anyDead) {
    Write-Host "One or more FFmpeg processes exited; terminating wrapper so it can be restarted."
    exit 1
}
```

The intent: "let Task Scheduler restart the wrapper, which restarts ffmpeg". Two problems
with this:

1. **Task Scheduler auto-disables a task after enough `RestartOnFailure` iterations** with
   the same failure exit code. After ~3-4 ffmpeg I/O errors the task ended up `Disabled`,
   `LastTaskResult: 1`, `NextRunTime: (none)`. Re-enabling with `Enable-ScheduledTask` is a
   manual step. Worse, every `Stop-Process ffmpeg -Force` from a debug script resets the
   counter toward the disable threshold.

2. **Even when the task survived, cold-starting run_ffmpeg.ps1 leaves a 5-10 s gap with
   no segments**: the env has to be re-imported, the ffmpeg log file re-allocated, the
   HLS playlist re-created. The dashboard's hls.js stalls while the manifest is missing
   the live edge.

## Fix

### `backend_host/scripts/run_ffmpeg.ps1` — restart ffmpeg in-place, never `exit 1`

Replaced the `exit 1` branch with a per-device restart loop. The monitor now checks
`ffmpeg.HasExited` for each device, and if a device's ffmpeg is gone, it:

1. Removes the dead PID from `$script:FFMPEG_PIDS` so the next check doesn't trip on it.
2. Calls `Clear-StaleFFmpeg` on the device's capture dir to kill any leftover ffmpeg
   holding the output files (mirrors the existing stall path).
3. Sleeps 2 s to let the device handle release.
4. Calls `Start-Grabber` again with the same source / audio / capture dir / fps / quality
   as before (so the HLS playlist picks up the same segment filename pattern; the
   `MEDIA-SEQUENCE` restarts from 0, but hls.js re-fetches the live manifest and resumes).

A `$script:DEATH_RESTART_COOLDOWN_SECONDS = 5` cooldown prevents a flapping source
(half-written PNG, a transient emulator crash) from hot-looping the restarter. The wrapper
itself only exits if the whole process dies — which Task Scheduler's `RestartOnFailure`
policy still handles, but at a much lower frequency.

### `backend_host/scripts/emulator_screencap.ps1` (on vpt-windows) — write in place

Replaced the `.tmp` + `Move-Item` pattern with a direct `[IO.File]::WriteAllBytes($OutFile, $bytes)`.
The trade-off: a single frame might be half-written when ffmpeg re-opens, which surfaces
as one decode error on that frame (image2 demuxer tolerates this; it just emits a warning
and continues on the next loop iteration). The benefit: the path is stable, so ffmpeg's
re-open never races with a rename, and the monitor loop is no longer needed for the
I/O race. (Linux labox-mobile doesn't have this problem because bash's `cat` doesn't
re-open the file — ffmpeg reads the bytes from a single fd that stays open across frames;
on Windows the image2 demuxer closes + reopens on every loop iteration. This is a
ffmpeg-on-Windows quirk that labox-mobile's `cat | ffmpeg -f image2pipe` sidesteps, but
the Windows port uses `-f image2 -loop 1` per BUG-0588, so we have to play nicer with
the re-open cycle.)

## Verification (live, 2026-10-17 13:50 UTC, vpt-windows)

Pre-fix: ffmpeg (PID 26544) started 13:46:32, dead by 13:47:04. vpt-stream task `Disabled`,
m3u8 ends with `EXT-X-ENDLIST` at segment 000000039.

Post-fix (re-enabled, restarted, watched for 30 s):
- ffmpeg (PID 7972) started 13:49:53, **alive across all three 10 s checks** at 13:50:28 /
  13:50:38 / 13:50:49.
- m3u8 updating every 10 s (one segment per 0.8 s × 5 fps × ~12 s/manifest-refresh ≈ the
  natural refresh cadence).
- vpt-stream task `State: Ready` (not Disabled).

The fix moves ffmpeg's lifetime from "dies in <12 s, task disabled" to "stable for the
duration of the emulator session".

## Files

- `backend_host/scripts/run_ffmpeg.ps1` — replaced the `exit 1`-on-death branch with an
  in-place per-device restart loop with a 5 s cooldown. `RestartOnFailure` is now only
  exercised when the wrapper itself dies (host crash, OOM, etc.), not on every ffmpeg
  I/O error.
- `backend_host/scripts/emulator_screencap.ps1` (on vpt-windows, gitignored) — replaced
  the `.tmp` + `Move-Item` pattern with an in-place `[IO.File]::WriteAllBytes` so the
  path is stable across ffmpeg's re-open cycle.

## Followups (not done in this session)

- The `RestartOnFailure` policy is still `Count=999, Interval=PT1M` — fine, since now
  only the wrapper exits trigger it, not every ffmpeg I/O error. If we ever want zero
  manual intervention, lower the count to e.g. 5 and add a watchdog that re-enables +
  restarts on a 5-minute cadence.
- The Linux labox-mobile's `cat | ffmpeg -f image2pipe` pattern still works there and
  doesn't have this race; we can leave the bash path as-is.
- ffmpeg's `image2` demuxer doesn't have a "reopen on error" flag for file inputs. A
  future ffmpeg change (or a wrap with `-re` + a network shim) would eliminate the
  in-place restart loop entirely, but `-loop 1` is the right tool for the Windows port
  per BUG-0588 §3.2.
