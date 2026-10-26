---
bug_id: BUG-0575
title: stream-stats overlay — "FPS: in" should be the ffmpeg-configured rate, not the measured one
summary: The overlay's "FPS: in" used to show the rate the monitor computed from capture sequence deltas, which read as "—" the moment the monitor had nothing yet (e.g. counting_cars, model still loading, monitor down) — even when ffmpeg was happily running at 5 fps. The user expects "in" to be the rate ffmpeg was *told* to capture at, distinct from the rate we actually observe. Fixed by parsing the live ffmpeg process cmdline on the host (`-framerate N`) and publishing `system_stats.stream_capture_fps[device_id]`; the overlay now shows the configured value as the primary "in" and tucks the measured value behind an `(≈ …)` suffix when the two differ.
tags: [frontend, backend_host, monitoring, ffmpeg, fps, overlay]
keywords: [stream_capture_fps, fpsInConfigured, get_configured_capture_fps, FpsLine, run_ffmpeg, framerate, BUG-0575]
created: 2026-10-16
---

# BUG-0575

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0575                                                     |
| Reported  | 2026-10-16                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / backend_host / monitoring                         |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

## Symptom

Open a `counting_cars` device in the rec stream modal:

```
FPS: in — · out 10
```

The "in" reads "—" (the monitor hasn't produced a measurement yet), but
ffmpeg on the host is running and capturing at e.g. 5 fps. The user
expects "FPS: in" to be the rate ffmpeg was *told* to capture at, not
the rate we just happened to measure. The two are different things:

- **Configured**: `-framerate N` in the ffmpeg cmdline (set by
  `run_ffmpeg.sh` from `DEVICE${i}_VIDEO_FPS` / `HOST_VIDEO_FPS` env vars,
  default 5 or 10 per source).
- **Measured**: the rate the monitor computes from capture sequence
  deltas (`useMonitoring.fpsInAnchorRef` / `setCaptureFps`). Depends on
  host load, monitor health, scene motion.

On a healthy device both numbers match. On a stuck monitor, or a profile
that hasn't run yet, or a model still loading, the measured value goes
null while the configured one stays put — and the operator has no way
to tell "ffmpeg is fine, monitor is the bottleneck" from "ffmpeg is
fine, captures are landing, but I'm looking at the wrong field".

## Root cause

`useMonitoring.ts:71` keeps `captureFps` in state, updated from capture
sequence deltas. `RecStreamContainer` / `EnhancedHLSPlayer` pass it as
`fpsIn` to `MonitoringOverlay`. The overlay (both default branch and
`ProfileOverlay.GenericOverlay` / `UiOverlay`) renders the value next
to "FPS: in", with no separate slot for the configured rate. The host
never publishes the configured rate: `system_info_utils.get_host_system_stats`
calls `check_ffmpeg_status` and `get_per_device_metrics`, but neither
introspects the live ffmpeg process for its `-framerate` argument.

## Fix

### Backend (`system_info_utils.py`)

New function `get_configured_capture_fps() -> Dict[str, int]`:

- Iterates running ffmpeg processes via `psutil.process_iter`.
- For each, regex-extracts the first `-framerate N` from the cmdline
  (the input rate; output `-r` is a different concern and not what the
  operator expects to see here).
- Matches the cmdline against the configured capture base
  directories (from `shared.storage_path_utils.get_capture_base_directories`)
  to derive the device id (folder basename).
- Returns `{device_id: fps}`; one ffmpeg per device is enough (the same
  `input_fps` is reused for the HLS / capture_*.jpg branch).

Wired into `get_host_system_stats` as `stats['stream_capture_fps']`, next
to `monitor_profiles` (same shape: a per-device map on the host's
`system_stats`).

### Frontend

- `SystemStats.stream_capture_fps?: Record<string, number>` (declared
  on `Dashboard_Types.ts`).
- `MonitoringOverlay` and `ProfileOverlay` (both `FpsLine` and the
  inline `UiOverlay` line) gain a `fpsInConfigured` prop.
- New display rule in `FpsLine`:
  - Primary "in" = `fpsInConfigured ?? fpsIn` (the configured value wins).
  - When `fpsInConfigured != null && fpsIn != null && fpsIn !== fpsInConfigured`,
    show the measured value as a dim `(≈ N)` suffix — so the operator
    can see "ffmpeg is set to 5 but only 3 are landing per second".
  - When `fpsInConfigured` is missing (e.g. legacy host), fall back to
    the old `fpsIn` behaviour so nothing regresses.
- `RecStreamContainer` and `EnhancedHLSPlayer` read
  `host.system_stats.stream_capture_fps[device_id]` and pass it down.
- Same rule applied in the default (tv_app) branch of `MonitoringOverlay`
  so the simpler overlay gets the same treatment.

## Verification

- `vite build` ✓
- `tsc --noEmit` clean on the changed files (the pre-existing
  `navItems.tsx` error is on `main` and unrelated).
- ESLint clean on `ProfileOverlay.tsx`, `MonitoringOverlay.tsx`,
  `RecStreamContainer.tsx`, `EnhancedHLSPlayer.tsx`.
- AST parse of the backend file ✓; `get_configured_capture_fps` is
  defined and referenced from `get_host_system_stats`.
- Manual regression: on a tv_app device with no ffmpeg process running,
  "FPS: in" still shows the measured value (or `—`) as before — the
  fallback to `fpsIn` is preserved.
