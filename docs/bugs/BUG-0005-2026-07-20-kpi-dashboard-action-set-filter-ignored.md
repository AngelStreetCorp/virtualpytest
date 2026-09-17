# BUG-0005 — KPI Measurement dashboard ignores the Action Set filter

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0005                                                     |
| Reported  | 2026-07-20                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | grafana / kpi-measurement dashboard                          |
| Fixed in  | build 8414                                                   |
| Commit    | `407030187`                                                    |

---

## Symptom

On the **KPI Measurement** dashboard, picking one or more entries in the **Action Set**
dropdown changed nothing — every table, timeseries and stat panel kept showing all action
sets. The dropdown itself populated correctly, so the filter looked functional.

## Root cause

The `action_set` template variable was declared in `templating.list` (multi-select,
`includeAll`, with a working options query) but the string `${action_set}` appeared **zero
times** across all 18 panel queries. Nothing consumed it, so selecting a value only re-ran
the variable's own query.

Only `variant` was actually wired into the panels (17 of 18). The `action_set` variable's
options query *does* filter on `${variant:sqlstring}`, which is why the dropdown contents
responded to the Variant filter — masking the fact that the panels did not respond to the
Action Set filter.

## Fix

Added the `action_set` predicate to every panel query in
`infra/monitoring/grafana/dashboards/kpi-measurement.json`, in three shapes matched to each
query's structure:

- **16 panels** (per-UI tables, Top Slowest, KPI Evolution, per-variant heatmaps, Details) —
  appended after the existing variant predicate:
  `AND (er.action_set_id IN (${action_set:sqlstring}))`
- **Panel 1** (top summary stat) — queries `execution_results` unaliased:
  `AND (action_set_id IN (${action_set:sqlstring}))`
- **Panel 18** (model/software heatmap) — the predicate goes *inside* the derived table `d`,
  next to the `ui.name` filter. The outer query only sees the aggregated `d.action_set_id`,
  which holds the resolved KPI *label*, not the raw id, so filtering there would not match.

The tables' `Report` link subqueries already correlate on `er2.action_set_id =
er.action_set_id`, so they inherit the filter and needed no change.

## Verification

1. Re-audited all three dashboard copies: 18/18 panels now reference `${action_set}`, 0 missing.
2. Parsed all 54 queries (18 panels × 3 copies) with `pglast` (real Postgres grammar), with
   `$__timeFilter` and both variables substituted — 54 parsed OK, 0 failures.
3. Diff footprint is 18 changed lines per file, one per panel — no incidental reformatting.

Not verified: the queries were not run against the live database (no DB credentials in that
session), so this is a syntax- and scope-level check, not a row-count check. Confirm on the
deployed dashboard that selecting an Action Set narrows the panels.

## Notes / left alone

- **Panel 18 still ignores `$variant`** — it groups by STB model + software version and reuses
  the column name `variant` for that, so wiring the Variant dropdown in would fight what the
  panel displays.
- **`user_interface`, `stb_model` and `software` remain dead filters** — declared but
  referenced by zero panels. `user_interface` is arguably redundant since each row hardcodes
  `ui.name`, but `stb_model` and `software` have no effect at all.
