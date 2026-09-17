# BUG-0109 — A failed incident insert uploaded a million orphan thumbnails and filled MinIO's inodes

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                    |
|-----------|--------------------------------------------------------------------------|
| ID        | BUG-0109                                                                  |
| Reported  | 2026-09-16                                                                |
| Status    | **Fixed in code (pending deploy).** Fleet unblocked by restart + cleanup.  |
| Severity  | High (storage exhausted; heatmap silently stopped publishing for ~8h)      |
| Area      | `backend_host/scripts/incident_manager.py` · `vpt-monitor` · MinIO storage |
| Fixed in  | build 9151                                                                 |

---

## Symptom

The frontend showed **"Heatmap data may be outdated. The backend processor might not be
generating new data."** Restarting `vpt-heatmap` changed nothing.

The processor was never the problem — it ran its full cycle every minute, then failed
every upload:

```
23:58:00  Processing heatmap for 2158
23:58:00  Fetched 5 captures from 6 devices in 0.04s (parallel)
23:58:00  Created mosaics: ALL(6), OK(3), KO(2)
23:58:01  Failed uploads for 2158:
            heatmaps/Awesomation/2158.json → XMinioStorageFull
            ... .jpg, _ok.jpg, _ko.jpg — all four
23:58:01  Generated heatmap for 2158 (6 devices)   ← logged success anyway
```

## The misleading part

`XMinioStorageFull` says *"Storage backend has reached its minimum free drive threshold"*,
which sends you to `df -h`, where everything looks fine:

```
/dev/sdb1   32G   18G   13G  59%  /data      ← 13 GB free
/dev/sdb1   2097152 inodes  2097150 used  2 free  100%   ← the real limit
```

`/data` was out of **inodes**, not bytes. `/data` is default-formatted ext4 (1 inode per
16 KB), so a 32 GB volume caps at ~2.1 M files. MinIO in single-drive mode stores each
object as a directory with `xl.meta`, ~2 inodes per object, and alert thumbnails are ~1 KB
— so the inode ceiling is hit at 8 GB of 32 GB used.

`alerts/` held **2,010,222 of the 2,097,152 inodes (96%)**, essentially all of it
`alerts/freeze/` at 1,005,093 objects.

## Root cause

The DB rejected the insert. Three hosts were presenting the **anon** key after the
service_role/RLS lockdown:

```
GET /rest/v1/alerts?...&incident_type=eq.freeze  →  HTTP 401 Unauthorized
DB INSERT FAILED: {'message': 'permission denied for table alerts', 'code': '42501'}
❌ create_incident returned None - incident creation FAILED
```

`vpt-monitor.service` has **no `EnvironmentFile`** — the process reads `.env` once at
startup via `load_dotenv`. labox-web, labox-mobile and labox-tablet had been running since
Sep 2/7; `/opt/virtualpytest/.env` gained `SUPABASE_SERVICE_ROLE_KEY` on **Sep 8 11:41**.
They never restarted, so they kept the old anon-only environment. (The anon value is a
new-style `sb_publishable_…` key, 46 chars — not even a legacy JWT, so this self-hosted
Supabase rejects it outright.)

Then the state machine turned one auth error into unbounded writes.
`del pending_incidents[issue_type]` only ran on success:

```python
incident_id = self.create_incident(...)
if incident_id:
    ...
    del pending_incidents[issue_type]   # only on SUCCESS
else:
    logger.error("❌ create_incident returned None - incident creation FAILED")
```

On failure the issue stayed pending, so the next detection tick still satisfied
`elapsed_time >= INCIDENT_REPORT_DELAY` and re-entered the same branch — and the upload
block runs *before* `create_incident`, with a freshly computed per-second key:

```python
time_key = f"{now.year}{now.month:02d}...{now.second:02d}"   # new key every second
r2_path  = f"{base_r2_path}/{time_key}_thumb_{i}.jpg"
```

The comment above it — *"Unique naming ensures no overwrites across different incidents"* —
is what made it unbounded rather than self-limiting. Nothing was ever overwritten, so at
~4–6 iterations/second per device across three hosts it wrote a new set of thumbnails
forever:

```
14:40:13.567  freeze persisted for 5231.0s, reporting to DB NOW → upload → 401 → FAILED
14:40:13.731  freeze persisted for 5231.2s, reporting to DB NOW → upload → 401 → FAILED
14:40:13.995  freeze persisted for 5231.5s, reporting to DB NOW → upload → 401 → FAILED
```

The object-date histogram starts the day the `.env` changed:

```
    465  20260907   ← normal
 94,008  20260908   ← .env updated, monitors not restarted
248,009  20260909
256,818  20260910
371,050  20260915
```

## Second-order trap

The 14-day ILM rules added on 2026-09-14 could not save it, for two reasons:

1. At multiple objects/second, 14 days of retention is ~2.4 M objects — past the 2.1 M
   inode ceiling. The rule was correct; the arithmetic never worked.
2. Editing the lifecycle config **is itself a write**. At zero free inodes:
   ```
   mc: <ERROR> Unable to set new lifecycle rules. Storage backend has reached its
   minimum free drive threshold.
   ```
   The mechanism meant to free the drive could not run because the drive was full.

## Fix

`incident_manager.py`:

- `CREATE_RETRY_BACKOFF = 60.0` — after a failed `create_incident`, skip the report branch
  for 60 s. A persistent DB error now costs one upload per minute, not ~5 per second.
- A retry reuses the images from the previous attempt (`{issue_type}_pending_r2`) instead
  of orphaning a fresh set under a new `time_key`.
- Both keys cleared on success and when the issue self-resolves.

Operationally: restarted `vpt-monitor` on the three hosts (0 × 401 afterwards, upload rate
~300/min → 1 per 90 s), deleted `alerts/**` older than 3 days, and set the `alerts/` ILM
rule to 3 days.

## Follow-ups

- `vpt-monitor.service` should carry `EnvironmentFile=/opt/virtualpytest/.env`. Without it
  any credential change silently breaks every host that is not restarted, with no alert.
- `/data` should be reformatted with a smaller bytes-per-inode (`-i 4096`) or `alerts/`
  moved to a bucket on `/shared` (30 GB and ~2 M inodes unused). At ~1 KB per object the
  current geometry wastes three quarters of the volume.
- The heatmap processor logs `Generated heatmap for NNNN` even when all four uploads
  failed. It should surface upload failure in its exit status or a metric so this is
  visible without reading MinIO.
