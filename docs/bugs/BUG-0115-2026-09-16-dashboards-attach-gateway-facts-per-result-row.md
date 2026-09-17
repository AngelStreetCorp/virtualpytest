# BUG-0115 — Dashboards attach gateway facts per result row, so panels take seconds on a large DB

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                         |
|-----------|-----------------------------------------------------------------------------------------------|
| ID        | BUG-0115                                                                                        |
| Reported  | 2026-09-16                                                                                      |
| Status    | **Fixed (pending deploy).**                                                                     |
| Severity  | Medium (every gateway-filtered dashboard on a large `script_results` table; the Home dashboard's overview panel was the visible one) |
| Area      | `infra/monitoring/grafana/dashboards/{dns-lookup,ookla-speedtest,superping,script-results}.json`, `docs/agent/infra/GRAFANA_DASHBOARD_PERF.md` |
| Fixed in  | build 9151                                                                                                                                     |

---

## Symptom

On a production deployment the Home dashboard's **Service Status** overview took several
seconds to render, and the per-script dashboards (DNS, Ookla, Superping and their customer
overlays) were slow to open with a 7-day range. Our own deployment showed nothing: the same
panels render in tens of milliseconds there.

## Root cause

The gateway filters (technology, LAN type, model, firmware, MAC) work by enriching every
result row with that host's gateway facts. Since 2026-06 ([GRAFANA_DASHBOARD_PERF](../agent/infra/GRAFANA_DASHBOARD_PERF.md))
each panel did that with a correlated lookup per row:

```sql
LEFT JOIN LATERAL (
  SELECT metadata FROM script_results gw
  WHERE gw.script_name = 'gw_info' AND gw.success AND gw.host_name = sr.host_name
    AND gw.started_at <= sr.started_at
  ORDER BY gw.started_at DESC LIMIT 1
) gw ON true
```

The index added then makes each lookup a single seek, and on our DB (25K rows, `gw_info`
once a day) that is invisible. It scales with **rows × gateway-scan frequency**, and a
production DB had both: 1.7M rows, `gw_info` every 40 minutes per host. `EXPLAIN ANALYZE`
of the overview panel over 7 days there:

| Measure | Value |
|---|---|
| Result rows in the window | 56,958 |
| `gw_info` runs in the window | 4,575 (≈241 per host) |
| Per-row lookups (original) | 57K seeks + 57K `metadata` fetches |
| Rows discarded by an as-of-run range-join rewrite (`LEAD()`) | 16.8M, 3.3 s |

The overview panel also built its labels with `MAX()` over every row's `script_identity`
metadata, and the `script-results` dashboard did the same in two panels and in its
`script_name` variable — another full pass over `metadata` per load.

## Fix

`fa44ce6` (platform), plus the same change in the customer overlay.

- Every enriched panel now `LEFT JOIN`s **`gw_info_latest`** — one row per host, the table
  migration `20260910c_gw_info_latest.sql` already maintains for exactly this — instead of
  looking the scan up per row. With a scan every 40 minutes "the latest scan" is never
  materially stale, so the filters keep their meaning. Hosts without an auth-successful scan
  read `Unknown` and pass every gateway filter, as before. HGW MAC follows
  `gw_info_latest.hgw_mac` (cable → PON → WAN), the derivation the HGW MAC variable used already.
- `script-results` labels (two panels, the `script_name` variable) join `executable_identity`
  instead of aggregating each row's metadata; the variable lists `DISTINCT script_name` first.
- `infra/monitoring/grafana/dashboards/README.md` documents the pattern and names the one not
  to use; the perf doc records why the 2026-06 index was not the end of the story.

## Verification

- Lab DB: all 26 rewritten platform queries plan and run with variables substituted; the
  gateway-filter audit (`scripts/audit_grafana_dashboards.js`) reports the same 28 pre-existing
  findings before and after.
- Production DB, same 7-day window, after the change: the largest single-script table
  (7,454 rows) plans as one index range and completes in **41.6 ms**, with no gateway lookup
  and no metadata fetch in the plan.
- Old vs new output was fingerprint-identical on three panels over 90 days on the lab DB for
  the intermediate range-join version; the `gw_info_latest` version differs only where a host's
  gateway facts changed inside the window, by design.
