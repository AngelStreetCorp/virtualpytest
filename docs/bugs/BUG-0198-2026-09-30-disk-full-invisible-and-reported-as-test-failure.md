# BUG-0198 — A host filled its 960 GB data disk, the dashboard showed 9.8%, and every verification reported it as "0/2 passed"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                        |
|-----------|------------------------------------------------------------------------------|
| ID        | BUG-0198                                                                     |
| Reported  | 2026-09-30 (a customer host)                                                 |
| Severity  | High — verification unusable on the host, and nothing surfaced the cause      |
| Status    | Fixed (pending deploy)                                                       |
| Area      | backend_host (metrics, screenshot, archiver) / frontend (dashboard, verification) |
| Fixed in  | Unreleased                                                                   |
| Commit    | this commit                                                                  |

---

## Symptom

Every verification launched from the Navigation editor timed out, on a host whose
dashboard tile read **Disk = 9.8%** and whose Status page showed no resource error.

```
09:34:50  Async execution started: e3d0b898-…      (device1 / capture1)
09:34:50  [HDMI] ERROR taking screenshot: [Errno 28] No space left on device
          …/capture1/hot/captures/capture_002003095.jpg -> …/capture1/captures/…
09:34:50  ⚠️ Could not draw crop rectangle: cannot identify image file
          '/data/stream/capture1/captures/capture_002003095.jpg'     ← 0-byte file
09:34:50  'all must pass' mode: 0/2 passed → ❌ FAIL
09:34:50  Failed to generate verification failure report: [Errno 28]
09:34:50  ✗ 67ms | Batch verification completed: 0/2 passed          ← recorded as a node failure
```

```
/dev/nvme1n1p1   960302096  911427560  20112  100%  /data
/dev/mapper/…-root  56193200  5226972  48079368  10%  /
```

## Root cause

Four separate things, each of which would have caught it on its own.

**1. The host measured the one filesystem that cannot fill.** `system_info_utils`
reported `psutil.disk_usage('/')`. On this host `/` is a 56 GB LV at 10% while
`/data` — every capture, reference and report — is a 960 GB NVMe that was at 100%
with 20 MB free. The Dashboard tile has threshold colouring and the Status page
has a >90% Resources row; both were fed a number that could not rise.

**2. ENOSPC was reported as a verification result.** `base_controller.take_screenshot`
records `last_screenshot_error` so a caller can say *why* a capture failed — but
only on the "device is not streaming" paths. The generic `except` recorded
nothing, so `image.py` / `text.py` returned a bare "Failed to capture screenshot
automatically", the batch scored 0/2, and `record_node_execution` wrote a
`node_metrics` row marking the node failed. An infrastructure outage was
indistinguishable from a device that had drifted off-screen, and it polluted the
metrics of every node checked during the outage.

**3. Retention is clock-based only.** Reports keep 30 days and cold hour folders
26 h regardless of how full the mount is. 184 GB of that disk was reports *inside*
their window. Nothing tightened as the mount filled, and the sweeps kept their
hourly cadence right up to 20 MB free.

**4. Why it filled at all** was [BUG-0094](BUG-0094-2026-09-15-archiver-never-rotates-capture-root-artifacts.md),
already fixed on 2026-09-15 in `edefe4cff` — a sweep for the `original_with_crop_*`
/ `verification_failure_*` artifacts written loose into the capture root. That
commit is **not** an ancestor of the host's pinned `main-2026.09.08-8713` /
`prod-2026.09.08-8558`, so on that install nothing had ever deleted them:
**2,056,005** files, oldest from 2026-06-17, and `du` itself failed with
"Argument list too long". The leak was known and fixed; what let it run 3.5 months
into a wedged disk is 1–3.

And the reason it presented as a *timeout* rather than a red result: with no
screenshot the batch failed in **67 ms**, so the host's completion event was
emitted before the browser's freshly-opened `/system` socket finished connecting,
and verification was the only flow with no polling fallback
([BUG-0197](BUG-0197-2026-09-30-verification-waits-on-socket-only.md)).

## Fix

- `shared/src/lib/utils/disk_space_utils.py` — one answer to "how full is the
  filesystem behind this path, and which mount is it". `shutil.disk_usage` so
  Windows hosts answer too; `worst_usage()` dedupes by `st_dev` so a host with the
  stream tree on `/` reports one mount, not two.
- `system_info_utils.get_disk_stats()` watches the root, the stream base and every
  `captureN/hot` tmpfs. **`disk_percent` is now the fullest of them**, so the
  tiles, the >90% row and the metrics table keep working off one number while
  finally tracking a filesystem that can fill; `disk_worst_mount` / `disk_mounts`
  carry the detail and the Dashboard tile names the mount.
- `take_screenshot` names ENOSPC (`last_screenshot_error` with the mount and its
  free space) and classifies it (`last_screenshot_error_code='no_space'`); any
  other exception at least reports itself. `image`/`text` pass
  `execution_error='no_space'` up; `verification_executor` aborts the batch on the
  first infrastructure failure and surfaces `execution_error`/`error` at batch
  level; `navigation_executor` skips `record_node_execution` for an aborted batch;
  `useVerification` shows the cause instead of "N/M passed".
- `hot_cold_archiver` gains space-aware retention: below 20% / 10% / 5% free the
  reports and root-artifact windows drop to 14 d / 7 d / 2 d, and below 10% the
  sweeps stop waiting for their hourly slot. Reports absorb the pressure first —
  that is where the space goes and they have no live consumer. Cold hour folders
  back the AVQ frame viewer's 24 h promise, so they are trimmed only at the
  critical tier and never below 24 h. Thresholds are env-tunable
  (`RETENTION_{ELEVATED,HIGH,CRITICAL}_FREE_PCT`), and the tier is logged on change.

Not changed: alerting. There is still no incident raised for a filling mount —
the >90% Resources row on the Status page is now fed a truthful number, which is
what that row was for.

## Verification

- `worst_usage` on Windows: three paths on one drive collapse to a single mount, a
  nonexistent drive is skipped, and a path whose file does not exist still resolves
  its mount (the ENOSPC case).
- `get_disk_stats()` on a dev box enumerates root + stream base, dedupes to one
  mount and reports it by name.
- `_retention_policy` at 60 / 15 / 8 / 2 % free returns normal / elevated / high /
  critical with reports at 30 / 14 / 7 / 2 days, archive folders never below 24 h,
  and `force_sweep` only from the high tier down.
- On the host: free the mount, then a verification reports checks again instead of
  a timeout; with the mount full it reports "the host is out of disk space on
  /data (… free of … GB)" and writes no node_metrics row.
