# BUG-0075 — `gateway_info_corrected` read hits the 8 s PostgREST statement timeout every minute on the customer DB

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0075                                                                    |
| Reported  | 2026-09-10 (customer DB Postgres log, found while working on BUG-0074)      |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | Medium (hosts listing waits ~8 s per call, gateway info never attached, 8 s of heavy scan on the DB every minute) |
| Area      | `setup/db/schema/036_gateway_info.sql` view · `backend_server/src/routes/server_system_routes.py:1497` · `shared/src/lib/database/device_info_overrides_db.py` |
| Fixed in  | build 8887                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

Customer DB (`hostdb1`) Postgres log, once per minute, at `hh:mm:08–10`:

```
172.26.x.9 07:20:09 UTC authenticator@postgres ERROR:  canceling statement due to statement timeout
172.26.x.9 07:20:09 UTC authenticator@postgres STATEMENT:  WITH pgrst_source AS ( SELECT
  "public"."gateway_info_corrected"."device_name", … FROM "public"."gateway_info_corrected"
  WHERE "public"."gateway_info_corrected"."team_id" = $1 LIMIT $2 OFFSET $3 ) …
```

`authenticator` carries `statement_timeout=8s` (Supabase default), so the read is killed after
8 s. Nothing surfaces in the VPT server: the caller is best-effort.

## Where it comes from

`server_system_routes.py:1497` — the hosts-listing endpoint attaches gateway info to every
device via `device_info_overrides_db.get_corrected_gateway_map(team_id)`, inside a
`try/except` ("host listing must never break if the device-info views are unavailable").
Something polls that endpoint every minute (client not identified). Consequences:

- every hosts listing call waits the full 8 s for the killed query before answering;
- `device['gateway_info']` is never populated on the customer install (tooltip empty);
- 8 s of full-scan load on the DB every minute — one of the concurrent queries behind
  BUG-0074's shared-memory exhaustion.

## Root cause

The view (`036_gateway_info.sql`) computes `latest` as

```sql
SELECT DISTINCT ON (team_id, device_name, host_name) …, (metadata - 'gateway_url' - … ) AS info_raw
FROM script_results
WHERE script_name = 'gw_info' AND metadata->>'auth_success' = 'true'
  AND device_name IS NOT NULL AND device_name <> 'host'
ORDER BY team_id, device_name, host_name, started_at DESC
```

On the customer DB that is 93K `gw_info` rows: every row is fetched, its jsonb subtracted,
then sorted, before `DISTINCT ON` keeps one row per device. `metadata->>'auth_success'` is
not indexable, and the `team_id = $1` from PostgREST is applied after the CTE. The lab has
437 `gw_info` rows, so the same view answers instantly there.

## Fix

TASK-16 (`docs/tasks/TASK-16-gw-info-latest-table.md`), migration
`setup/db/migrations/20260910c_gw_info_latest.sql`, schema `046_gw_info_latest.sql`:

- `gw_info_latest` — the latest auth-successful `gw_info` scan per (team, device, host),
  exactly the rows the view's `latest` CTE produced, maintained by a row trigger on
  `script_results` (`trg_gw_info_track`, fires only for `script_name = 'gw_info'`; an older
  scan arriving late never overwrites a newer one; deleting the scan row cascades).
- `gw_info_values` — every value seen per Grafana variable kind (model, firmware, technology,
  network type, derived HGW MAC) in successful runs; the dashboards' filter variables read
  this (~50 rows) instead of rescanning every `gw_info` row per dashboard load (BUG-0074's
  remaining cost).
- `gateway_info_corrected` / `gateway_info_key_status` recreated over `gw_info_latest` with
  the same columns and `security_invoker`, so `device_info_overrides_db.py` and the hosts
  endpoint are unchanged — the read is now a `team_id` lookup on a table with one row per device.
- Backfill inside the migration; grants, RLS and policies copied from `script_results` on the
  DB it runs on, so the same file is right on main (service_role) and on the customer (anon).

## Verification

- Lab `.102`, 2026-09-10: migration in one transaction; `gateway_info_corrected` output
  identical before/after (`EXCEPT` both ways = 0); grants/RLS = `script_results`' (postgres +
  service_role, RLS on, no policy). Trigger test with synthetic rows: insert → row + 5 values +
  view + key_status rows; older scan → not overwritten, value counted; newer scan → overwritten
  (fiber MAC derived from `pon_mac_address`); failed run → nothing; delete of the scan → row
  gone (cascade). Test rows removed.
- Repo dashboards (`dns-lookup`, `superping`, `ookla-speedtest`) variables → `gw_info_values`, pushed to the lab Grafana.
- Not yet on the customer DB (their migration tool, next release; the 10 overlay dashboards
  follow the same rewrite). Expected there: the per-minute `canceling statement` lines stop,
  hosts listing no longer waits 8 s, gateway tooltip filled.
- QualiAI: migration rolls back — that DB never received `device_info_overrides` (035/036);
  prerequisite, not part of this fix.
