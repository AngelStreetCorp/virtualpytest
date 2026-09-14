# BUG-0018 — KPI report drill-down links 404 (Grafana subpath)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0018                                                     |
| Reported  | 2026-07-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | grafana / kpi-measurement dashboard                         |
| Fixed in  | build 8713                                                   |
| Commit    | `523fa9b72`                                                 |

---

## Symptom

On the **KPI Measurement** dashboard, clicking a row's **Report** cell returned Grafana's
`404 page not found` instead of opening the KPI Test Report drill-down dashboard.

## Root cause

The Report cell built a **root-relative** link (`/d/<uid>/…`). Grafana is served from the
`/grafana` subpath behind the reverse proxy, so a root-relative `/d/…` resolves against the site
root (`https://host/d/…`) rather than `https://host/grafana/d/…`, which doesn't exist → 404.

## Fix

`infra/monitoring/grafana/dashboards/kpi-measurement.json` (`523fa9b72`): the Report cell link is
prefixed with the `/grafana` subpath (`/grafana/d/<uid>/…`) so it resolves under the served base
path.

## Verification

On the deployed KPI Measurement dashboard, click a Report cell: the KPI Test Report drill-down
opens with the row's context instead of 404.
