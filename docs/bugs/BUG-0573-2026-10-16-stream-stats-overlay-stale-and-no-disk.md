---
bug_id: BUG-0573
title: stream-stats overlay — stale "checked" label, missing disk/IO row, redundant "behind live"
summary: useHostSnapshot only fetched once on mount, so the HOST line's "checked Xs ago" counter drifted away from the heartbeat age forever (e.g. "14s old · checked 26s ago"). The overlay also never showed disk_percent and only showed write I/O (read was missing). The Latency row repeated "behind live" right after the value.
tags: [frontend, monitoring, stream, polling, disk, ux]
keywords: [useHostSnapshot, StreamStatsOverlay, host_snapshot_poll_ms, disk_percent, disk_read_mb_per_sec, disk_write_mb_per_sec, behind_live]
created: 2026-10-16
---

# BUG-0573

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0573                                                     |
| Reported  | 2026-10-16                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / backend_host                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

## Symptom

Open any live host in the rec stream modal and look at the bottom-left
overlay (TASK-20 screenshot, 2026-10-16 14:05:39):

```
STREAM · live
FPS: 10
Latency: 1.7s behind live
HOST · 14s old · checked 26s ago ↻
CPU/RAM: 35% · 54%
Load: 2.08 · 3.1 MB/s
```

Three observable defects:

1. The two HOST numbers disagree. `14s old` is the host heartbeat age as
   stamped by the host's own server, `checked 26s ago` is *time since the
   modal opened*, because the hook that fetches the snapshot only runs on
   mount (and on the manual refresh icon). The label grows without bound;
   a long-open modal will eventually read `checked 2m ago` while the data
   behind it might be `30s old`. The two values are unrelated clocks.
2. The overlay has no `disk_percent` row even though the backend has
   always published it (and the FULLEST-monitored-mount metric, see
   BUG-0198). The single `3.1 MB/s` shown is **write only**; read I/O
   was silently dropped on the backend as well.
3. The Latency row says `1.7s behind live`. The row is already labeled
   `Latency`, so the suffix is noise.

## Root cause

- `frontend/src/components/monitoring/hooks/useHostSnapshot.ts` had a
  single `useEffect` keyed on `[hostName, serverUrl, nonce]`. `nonce`
  only changes when the user clicks the refresh button, so without a
  click the fetch happens exactly once.
- `frontend/src/components/monitoring/StreamStatsOverlay.tsx` rendered
  `cpu_percent`, `memory_percent`, `load_average_1m` and the
  already-typed `disk_write_mb_per_sec` — but the type declaration
  (`SystemStats` in `types/pages/Dashboard_Types.ts`) never listed
  `disk_read_mb_per_sec`, `disk_used_gb`, `disk_total_gb` or
  `disk_worst_mount`, so the TS compiler hid them from view.
- `backend_host/src/lib/utils/system_info_utils.py` only tracked the
  *write* counter from `psutil.disk_io_counters()`; the read counter
  was discarded.

## Fix

### Polling cadence (TASK-20)

`useHostSnapshot` now schedules a `setNonce(n => n + 1)` every
`HOST_SNAPSHOT_POLL_MS = 20_000` while the hook is mounted. 20 s is
well below the 30 s ceiling the operator named for the "checked"
label to be truthful, and matches the Status page's host-tile refresh
cadence. A `document.visibilitychange` listener forces an immediate
re-read when the tab comes back to the foreground, so a long-idle
overlay doesn't show 19 s of stale data the moment the user looks
again. In-flight fetches stay cancellable on unmount and on
`refresh()`.

### Disk + I/O row

`StreamStatsOverlay` now has its own `Disk` row, sitting between
`CPU/RAM` and `Load`:

- `disk_percent` colour-graded the same way as CPU/RAM, with a
  Tooltip showing `Worst mount: <path>` (or `Fullest monitored mount`
  when the backend omits the field — see BUG-0198 for the
  "fullest-monitored-mount, not `/`" rationale).
- `R/W MB/s` only renders when at least one of the two rates is > 0,
  so an idle host doesn't show `R 0.0 · W 0.0`.

The previous `Load` row's trailing `disk_write_mb_per_sec` is gone
— I/O lives on the Disk row now.

### Backend (`system_info_utils.py`)

Both `get_host_system_stats` and `get_enhanced_system_stats` now
track `read_bytes` alongside `write_bytes` in the same
`psutil.disk_io_counters()` snapshot and publish
`disk_read_mb_per_sec` next to `disk_write_mb_per_sec`. First-run
baseline is 0/0 (same convention as the previous write-only
implementation). The `max(0, ...)` guard prevents a counter reset
(after a reboot) from going negative.

### Type declarations

`SystemStats` now declares `disk_read_mb_per_sec`, `disk_used_gb`,
`disk_total_gb`, `disk_worst_mount` and `disk_mounts`. The first two
are read by the new overlay row; the others are not consumed yet but
the type matches what the backend already sends (so the next agent
won't be surprised).

### Latency row

The `behind live` suffix is removed; the row now reads
`Latency: 1.7s` only.

## Verification

- `vite build` succeeds. `tsc --noEmit` has one pre-existing error
  in `src/config/navItems.tsx` that is present on `main` and
  unrelated to this change.
- `vitest run`: 18 of 19 files pass, 154/155 tests pass. The single
  failure (`useDeviceProfileFilter.test.tsx`) reproduces on `main`
  and is unrelated to this change.
- ESLint on the three touched files: clean.
- Backend module: `ast.parse` succeeds; both `get_host_system_stats`
  and `get_enhanced_system_stats` reference `disk_read_mb_per_sec`
  and `_last_disk_io`.
- Manual: open a live host in the rec stream modal, leave the modal
  open without touching the refresh icon. The HOST line's "checked"
  counter resets to ~0 every 20 s, and a `Disk` row appears
  underneath `CPU/RAM` showing `disk_percent` and `R/W MB/s` (read
  appears once the host's `get_host_system_stats` has run at least
  twice after the host restart).
