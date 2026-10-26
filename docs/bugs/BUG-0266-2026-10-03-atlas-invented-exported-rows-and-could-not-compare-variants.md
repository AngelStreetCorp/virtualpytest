# BUG-0266 — Atlas made up the rows of an export and struggled to compare two variants

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0266                                                     |
| Reported  | 2026-10-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High — an export answer showed numbers that were not in the data |
| Area      | `backend_server/src/mcp/tools/analytics_tools.py`, `backend_server/src/lib/analytics/service.py`, `backend_server/src/agent/core/manager.py` |
| Fixed in  | build 90145 |
| Commit    | `24dae71f4`, `49e44bd38`                                            |

---

## Symptom

Live Atlas smoke test on the deployed build:

- "Export the pass rate by device as CSV": the export ran (15 rows), but the chat showed a CSV of
  invented devices (`device1…device5`) with invented numbers.
- "Compare Base and variant1 KPI … show only regressions over 10%": about 25 tool calls, five
  validation errors (missing `align_by`/`series_field`, unknown direction), a Grafana draft
  nobody asked for, and finally regressions computed by the model by hand.

## Root cause

- The export reply text said only *Exported N rows as CSV*; the model never saw the file content,
  so it wrote one.
- A comparison required `align_by`, `series_field` and `metric` even when the chart already
  defines them (category, series, first metric), and `query_kpi_radar` had no `comparison`
  parameter at all (the model passed one as a string, which was ignored).
- `create_grafana_draft` was offered for any analytics question and the model used it.

## Fix

- The export reply includes the file content (up to 6,000 characters) and says to show or
  summarise only that content.
- `comparison` defaults `align_by`, `series_field`, `metric` and the sample count from the chart;
  the schema explains that only `baseline` and `candidate` are needed, and which direction fits
  durations vs rates. `query_kpi_radar` accepts `comparison`.
- The router offers `create_grafana_draft` only when the message mentions Grafana, and
  `export_analytics_data` only for export/CSV/JSON/download/file.
- A render reply tells the model the chart is already displayed and hands it the rows to summarise: a comparison in full (up to 60 rows), data up to 30 rows with a "first N of M" note. A 5-row sample had made Atlas report 1 regression out of 5.

## Verification

- `test_export_reply_carries_the_real_content`, `test_kpi_radar_shortcut_compares_with_only_baseline_and_candidate`,
  `test_only_regressions_over_ten_percent` (now with only baseline/candidate/threshold),
  `test_router_offers_grafana_and_export_only_when_asked`.
- Live smoke prompts re-run after deploy.
