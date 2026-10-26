---
title: run_ffmpeg.ps1 in-place ffmpeg restart: `$pid` is PowerShell's read-only auto-var, throws "Impossible de remplacer la variable PID"
area: integrations
severity: blocker
status: resolved
date: 2026-10-17
component: backend_host/scripts/run_ffmpeg.ps1
hosts: [vpt-windows]
device: Mobile_Emulator
related: [BUG-0592]
---

# BUG-0593: run_ffmpeg.ps1 in-place ffmpeg restart — `$pid` is PowerShell's read-only auto-var

## Problem

After BUG-0592 added the in-place ffmpeg restart loop to `run_ffmpeg.ps1`, the
`vpt-stream` wrapper on vpt-windows crashed within seconds of starting ffmpeg. The
dashboard's `Mobile_Emulator` tile showed "Loading stream…" forever; the `vpt-stream`
Scheduled Task eventually got auto-Disabled. The error in `run_ffmpeg.ps1` stderr was:

```
Impossible de remplacer la variable PID, car elle est constante ou en lecture seule.
Au caractSre C:\virtualpytest\virtualpytest\backend_host\scripts\run_ffmpeg.ps1:734 : 9
+         $pid = [int]$state.PID
+         ~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo : WriteError: (PID:String) [], SessionStateUnauthorizedAccessException
```

Translation: "Cannot replace the variable PID, because it is a constant or read-only."

## Root cause

`$pid` is **PowerShell's automatic read-only variable** for the current process's PID
(same as `$PID`; PowerShell variable names are case-insensitive). The BUG-0592 in-place
restart loop, and the older `Restart-StalledGrabbers` stall-detection path, both used
`$pid` as a local variable name:

```powershell
$pid = [int]$state.PID   # ← always errors — $pid is read-only
Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
```

The first call to `Restart-StalledGrabbers` (which runs every second in the monitor loop)
hit the read-only error. The unhandled exception escaped the monitor loop and killed the
script. The Task Scheduler saw a `LastTaskResult: 1` and eventually auto-Disabled the
task. ffmpeg, having died on its own (the image2 demuxer's normal re-open race), was
never restarted in-place — every wrapper run required a manual `Start-ScheduledTask`.

The same bug existed in the original `Restart-StalledGrabbers` (line 611) but went
unnoticed because stalls don't happen in normal operation on vpt-pi4 / vpt-nipogi
(`v4l2` / `x11grab` sources have stable framerates), so the loop never tried to read
the auto-var. vpt-windows' `imagefile` source is the first to routinely stall-and-restart
in the steady state.

## Fix

`backend_host/scripts/run_ffmpeg.ps1`:

- Renamed `$pid` → `$devicePid` in `Restart-StalledGrabbers` (line 614).
- Renamed `$pid` → `$devicePid` in the BUG-0592 in-place restart loop (line 743).

The `$script:FFMPEG_PIDS` array (script-scoped) is unchanged — `Where-Object` filters by
value comparison and the `$_` in the filter expression is PowerShell's automatic `$_`
(not `$pid`). No other `$pid` reassignments remain in the file.

## Verification (live, 2026-10-17 14:10 UTC, vpt-windows)

Pre-fix: ffmpeg would start, the wrapper would die within seconds on the read-only error,
and the dashboard tile would freeze on the cached m3u8 (segments 0-59 missing, all
404s, ENDLIST).

Post-fix: ffmpeg (PID 19328) started 14:09:36, died 14:10:20, the in-place restart loop
kicked in (5s cooldown), killed the dead PID, and started a new ffmpeg (PID 24728) at
14:10:20. The m3u8 now has the live edge with 72 fresh segments (0-71, first
timestamp 14:10:20, last 14:11:17). The dashboard `Mobile_Emulator` tile is playing:
`<video> readyState: 4, currentTime: 114s, 360×640 portrait, 0 errors, 0 404s`. All
subsequent vpt-windows segment requests return 200.

## Files

- `backend_host/scripts/run_ffmpeg.ps1` — `$pid` → `$devicePid` in the two locations
  (BUG-0592 in-place restart loop + the original `Restart-StalledGrabbers`).

## Followup

- A future change could rename `$pid` everywhere in the codebase to a non-reserved name
  (e.g. `$devPid`, `$ffmpegPid`, `$targetPid`) to prevent the same trap. For now,
  `grep -n '\$pid\b' backend_host/scripts/*.ps1` returns no matches other than the BUG
  comment lines.
- The `STREAM_WRAPPER.ps1` bash file already uses `$pid` for the ffmpeg process ID, but
  bash has no reserved `$pid` so it's safe. Document this discrepancy for anyone
  cross-porting between the two.
