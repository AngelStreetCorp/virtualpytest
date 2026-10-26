# BUG-0261 — Atlas KPI charts filtered by device flag failed on every query

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0261                                                     |
| Reported  | 2026-10-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — the documented KPI "flags" filter could not be used |
| Area      | `backend_server/src/lib/analytics/service.py` (flag filter)  |
| Fixed in  | build 90145 |
| Commit    | `8ee5bd2bc`                                                       |

---

## Symptom

A KPI radar or KPI query with a device-flag filter (e.g. "KPI radar for stb_tv, lab devices
only") failed with *Analytics query failed.*

## Root cause

The flag predicate joined `device_flags df ... WHERE df.team_id = er.team_id`. `device_flags`
has no `team_id` column, so PostgreSQL rejected the statement. The unit test only inspected the
SQL text and never ran it. The predicate also did not apply the caller's device scope to the flag
rows, unlike the KPI dashboard.

## Fix

The flag predicate matches flags by host and device only and scopes the flag rows through the
same `grafana_device_scope` result as the rest of the query (the dashboard's behaviour). Every
source and preset was then executed read-only against the live schema.

## Verification

- `test_flag_filter_is_parameterized_scoped_and_has_no_team_column`.
- Every source (default and all fields) and every preset was run read-only against the database
  schema; none errors.
