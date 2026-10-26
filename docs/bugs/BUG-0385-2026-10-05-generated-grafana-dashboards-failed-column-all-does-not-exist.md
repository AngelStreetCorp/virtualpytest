# BUG-0385 — Generated Grafana dashboards failed: column "__all" does not exist

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0385                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | ai-agent                                                     |
| Fixed in  | build 90145 |

## What happened
Every dashboard Atlas generated (canvas auto-drafts and "create a dashboard") opened in Grafana with all panels in error: `db query error: pq: column "__all" does not exist`. The variable queries worked; every panel query failed on the default view (all variables on All). Found by opening `atlas-draft-4ea3e0f4cce0dbd3b76e` in a logged-in browser and reading the `/api/ds/query` responses.

## Cause
`template.json` gave host/device_name/user_interface/environment `allValue: "__all"`. Grafana inserts a custom allValue RAW (selected values are quoted, the allValue is not), so the panel predicate `'__all' IN ($host)` became `'__all' IN (__all)` — an identifier. The unit tests only compared the SQL text with variables unexpanded, and the post-deploy link check got HTTP 200 from Grafana's login page, so neither saw it.

## Fix
The template stores the allValue with its quotes (`'__all'`), so `$host` on All reads `'__all'` and the predicate is `'__all' IN ('__all')`. Regression test `test_all_value_interpolates_to_valid_sql` expands the panel SQL the way Grafana does (raw allValue, quoted selections) and fails on an unquoted `__all`.
