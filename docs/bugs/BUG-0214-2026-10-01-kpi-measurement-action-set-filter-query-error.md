# BUG-0214 — KPI Measurement: the Action Set filter failed with a GROUP BY error

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0214                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | grafana                                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

On the **KPI Measurement** Grafana dashboard the **Action Set** drop-down had no options. Its query
failed with:

```
pq: column "lbl.edge_label" must appear in the GROUP BY clause or be used in an aggregate function
```

Found while aligning QualiAI's KPI Measurement dashboard with node1's: the same query fails on both.

## Root cause

[BUG-0157](BUG-0157-2026-09-23-standby-kpi-display-name-ignored.md) (`2b42a227a`) changed the
`action_set` variable to label each action set from its navigation edge
(`COALESCE(NULLIF(lbl.edge_label, ''), NULLIF(lbl.kpi_name, ''), er.action_set_id)`). The query
groups by `er.action_set_id` only, and that label expression was used outside any aggregate. The
version before BUG-0157 (`ba63d3019`) runs; the BUG-0157 version does not.

## Fix

`infra/monitoring/grafana/dashboards/kpi-measurement.json`: the 4 bare uses of the label
expression in the `action_set` query are wrapped in `MIN(...)`. Each action set still gets one
label, and the standby display-name rule of BUG-0157 is unchanged.

## Verification

- Ran the `action_set` query through each Grafana's `/api/ds/query`, before and after the fix:
  node1 failed before and lists 47 action sets after; QualiAI failed before and runs after
  (0 rows: no KPI data there).
- Every other query of the dashboard runs without error on both; `_check_device_scope.py` passes.
