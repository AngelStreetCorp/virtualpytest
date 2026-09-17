# BUG-0116 — The Host filter on the host monitoring dashboard scans every metric row

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                         |
|-----------|-----------------------------------------------------------------------------------------------|
| ID        | BUG-0116                                                                                        |
| Reported  | 2026-09-16                                                                                      |
| Status    | **Fixed (pending deploy).**                                                                     |
| Severity  | Low (one dashboard, seconds of delay on every open; grows with the metrics table)              |
| Area      | `infra/monitoring/grafana/dashboards/system-host-monitoring.json` (template variable `host`) |
| Fixed in  | build 9151                                                                                   |

---

## Symptom

Opening **System – Host Monitoring** stalled for a couple of seconds before the Host dropdown
and the panels appeared, every time, while the panels themselves render in a millisecond or two.

## Root cause

Found while auditing every dashboard after [BUG-0115](BUG-0115-2026-09-16-dashboards-attach-gateway-facts-per-result-row.md).
The `host` template variable was

```sql
SELECT DISTINCT host_name FROM system_device_metrics WHERE host_name != 'server' ORDER BY host_name
```

with no time bound. `system_device_metrics` is the per-minute device metrics table (913K rows on
the lab, growing) and Postgres 17 has no skip scan, so a DISTINCT over an indexed column still
reads the whole table: a parallel seq scan, **2.6 s cold, 0.7 s warm**, on every dashboard load
and every refresh. The two sibling variables (`host_download`, `host_upload`) were already
time-bounded and are fine.

## Fix

`a554774`. The variable walks the existing `host_name` index one host at a time with a recursive
CTE (the standard loose-index-scan idiom):

```sql
WITH RECURSIVE h AS (
  (SELECT host_name FROM system_device_metrics ORDER BY host_name LIMIT 1)
  UNION ALL
  SELECT (SELECT host_name FROM system_device_metrics WHERE host_name > h.host_name ORDER BY host_name LIMIT 1)
  FROM h WHERE h.host_name IS NOT NULL
)
SELECT host_name FROM h WHERE host_name IS NOT NULL AND host_name != 'server' ORDER BY host_name
```

One index probe per distinct host instead of one row read per metric.

## Verification

- Lab DB: same 16-host list from both queries; **733 ms → 32 ms** warm.
- Run through the Grafana datasource API against the lab datasource: 200, no error, same list.
- Pushed to the lab Grafana (uid `system-host-monitoring`) and reopened.
