# BUG-0087 — MinIO had no lifecycle rules at all; /data filled up and every artifact upload failed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0087                                                                    |
| Reported  | 2026-09-14                                                                  |
| Status    | Fixed (live fix applied on Awesomation; installer + docs updated)            |
| Severity  | High (every script run recorded `success=false`; no reports, logs or screenshots stored) |
| Area      | storage VM `/data` · MinIO ILM · `setup/local/linux/storage/install_minio.sh` |
| Fixed in  | Unreleased                                                                  |

---

## Symptom

Script runs completed with `SCRIPT_SUCCESS:true` and "test result: PASS" in the host log,
but `script_results.success` was `false` and `html_report_r2_url` was NULL. The host log
showed, for every upload:

```
[@cloudflare_utils:upload_verification_review_markdown] ERROR: Verification markdown upload failed:
An error occurred (XMinioStorageFull) when calling the PutObject operation:
Storage backend has reached its minimum free drive threshold.
```

Redis (same VM, same disk) had also stopped accepting writes:

```
MISCONF Redis is configured to save RDB snapshots, but it's currently unable to persist to disk.
```

Both disk *and* virtual scripts failed identically, which is what ruled out the
disk→virtual conversion work happening at the same time.

## Root cause

`/data` on the storage VM was at **95%** (29G of 32G, 1.7G free), below MinIO's free-drive
threshold, so MinIO refused every `PutObject`.

It filled up because **the bucket had no lifecycle configuration at all**:

```
$ mc ilm rule ls local/virtualpytest
mc: <ERROR> Unable to get lifecycle. The lifecycle configuration does not exist.
```

`install_minio.sh` has always contained `add_ilm_rule` calls, but they had never been
applied on this instance (the installer's own guard skips a rule when one already exists,
and nothing re-runs the block on an existing install). Nothing had ever expired since the
bucket was created in February.

Two prefixes would not have been covered even if the rules *had* applied — they were
missing from the installer entirely:

| prefix | size | had a rule? |
|---|---|---|
| `script-reports/` | 6.9G | yes |
| `alerts/` | 6.7G | yes |
| `script-screenshots/` | **5.1G** | **no** |
| `kpi_measurement/` | 4.2G | yes |
| `script-logs/` | 1.5G | yes |
| `heatmaps/` | 496M | yes |
| `reports/` | 139M | **no** |
| `fleet-health/` | 568K | **no** |

## Fix

**Live (Awesomation, 2026-09-14):**
- Purged objects older than 14 days from every artifact prefix
  (`mc rm --recursive --force --older-than 14d`): 169,968 objects,
  **/data 95% → 62%** (1.7G → 12G free).
- Added 14-day expiry rules for all 11 artifact prefixes, including the three that were
  missing. Verified with `mc ilm rule ls`.
- `navigation/` (127M, 1108 objects) and `reference-images/` (7.2M, 414 objects) were
  **not** touched and have **no** expiry rule — they are the permanent nav-tree screenshot
  and reference-image libraries the product reads on every run. Sizes and object counts
  confirmed identical before and after.

**In the repo:**
- `setup/local/linux/storage/install_minio.sh` — all artifact prefixes at 14 days (was
  30/14 split), plus `script-screenshots/`, `reports/` and `fleet-health/`.
- `setup/local/linux/storage/install_storage.md` — table updated, plus the rule that every
  prefix `cloudflare_utils.py` writes to must appear in it, and the `mc rm --older-than`
  recipe for freeing space immediately (ILM only acts when MinIO's scanner next runs).

## Verification

- `mc ilm rule ls local/virtualpytest` — 11 rules, all Enabled, 14 days; no rule on
  `navigation/` or `reference-images/`.
- Same script (`dns_lookuptime`) before and after the purge:
  `success=f, has_report=f` → `success=t, has_report=t`.

## Follow-ups (not done)

- Nothing alerts on `/data` filling up. A disk-usage check on the storage VM would have
  caught this months earlier.
- `install_minio.sh`'s ILM block only runs at install time. An existing instance needs the
  rules applied by hand — there is no reconcile step.
- The `XMinioStorageFull` upload failure is recorded as a *script* failure. A run whose
  assertions all passed should not be marked failed because its report could not be
  stored; that conflates test outcome with infrastructure health.
