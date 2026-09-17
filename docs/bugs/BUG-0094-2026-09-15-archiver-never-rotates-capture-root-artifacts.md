# BUG-0094 — Report artifacts in the capture root are never rotated; and a long-lived archiver silently runs pre-fix code

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0094                                                                     |
| Reported  | 2026-09-15                                                                   |
| Status    | **Fixed in code (pending deploy).** Part 2 needs a service restart on hosts.  |
| Severity  | Medium (local disk growth; no stream impact observed on vpt-pi1)              |
| Area      | `backend_host/scripts/hot_cold_archiver.py` · `vpt-archiver.service`          |
| Fixed in  | build 9151                                                                    |

---

## Symptom

Capture directories grow without bound even though the hot/cold archiver is running
and healthy. On vpt-pi1:

| directory | size | note |
|---|---|---|
| `capture3/reports` | 1.3 GB (7580 files) | 7544 older than the 30-day retention |
| `capture4/reports` | 599 MB (2517 files) | 2503 older than 30 days |
| `original_with_crop_*.png` in capture roots | **1.8 GB (5105 files)** | oldest 2026-05-12 |
| `verification_failure_*.html` in capture roots | 2462 files | never swept |

The rolling design itself is fine — `segments`, `captures`, `thumbnails` and `metadata`
rotate correctly, and the disk was at 37 % (71 GB free). Only the side-artifacts leak.

There are **two independent causes**, and they need different fixes.

---

## Part 1 — a coverage gap in current code (FIXED here)

`sweep_stale_hot_files()` is the catch-all, but it only walks four subdirectories:

```python
for sub in ('segments', 'captures', 'thumbnails', 'metadata'):
```

`cleanup_reports()` covers `reports/`. **Nothing covers the capture root itself.**

Verification and KPI runs write `original_with_crop_*.png`, `verification_failure_*.html`
and `kpi_failure_*.html` directly into `/var/www/html/stream/captureN/`. They are not
under a hot subdir, not under `reports/`, and match no per-type rotation pattern — so no
sweep has ever been able to see them. On vpt-pi1 that is 1.8 GB going back four months.

Creation itself has stopped (newest `original_with_crop_*` is 2026-09-08, none in the
last 24 h — the BUG-0009 OCR-helper purge is doing its job), but the existing backlog
would have sat there forever.

**Fix:** `cleanup_capture_root_artifacts()`, run on the same hourly cadence and the same
30-day retention as `cleanup_reports()`. It is non-recursive and matched by explicit
prefix, so it can never touch config, manifests or `test_video.mp4` in the same
directory.

---

## Part 2 — the archiver was running three-month-old code (needs a restart)

This is the bigger and more general problem.

```
vpt-archiver.service   ActiveEnterTimestamp = Wed 2026-06-24 20:54:21 CEST
                       NRestarts = 0
/opt/.../hot_cold_archiver.py  mtime = 2026-09-15 00:18
journalctl | grep -c "Reports: Deleted"  ->  0
```

The process has run continuously since **24 June**. Two cleanup fixes have landed since,
been deployed to disk, and **never taken effect**, because Python loads the module once
at start:

| commit | date | what it added |
|---|---|---|
| `718954808b` | 2026-07-21 | catch-all stale sweep for hot dirs (BUG-0009) |
| `4e33a17136` | 2026-09-01 | 30-day retention for `reports/` and verification results |

That is why `reports/` still holds files from July: the retention code exists on disk but
the running process predates it.

**This is a deployment-hygiene bug, not a code bug** — the same class as
`vpt-kpi.service` being rsynced but not restarted. Any long-lived host service that is
updated by file sync needs an explicit restart, or its fixes are invisible.

### What a restart reclaims

~1.9 GB of >30-day reports immediately, plus the 1.8 GB of root artifacts once Part 1
ships.

```bash
ssh vpt-pi1 'sudo systemctl restart vpt-archiver'
# then confirm the retention is actually running:
ssh vpt-pi1 'journalctl -u vpt-archiver --since "2 hours ago" | grep -E "Reports:|Capture root:"'
```

---

## Not related to this bug

`capture_monitor.py` was at **4.9 GB RSS** after 7 days (~700 MB/day). That process
*is* running current code (started 2026-09-08, file dated 2026-09-07), so it is a
genuine leak in the current monitor and is tracked separately — not an archiver or
rotation problem. The host was not actually starved at the time (8.1 GB available,
most of `used` being reclaimable page cache).
