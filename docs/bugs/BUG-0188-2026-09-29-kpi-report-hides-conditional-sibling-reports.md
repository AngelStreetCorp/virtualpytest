# BUG-0188 — A failed KPI measurement on a conditional edge hid the sibling's report and blamed the KPI service

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0188                                                     |
| Reported  | 2026-09-29                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — misleading report, no data loss                     |
| Area      | backend_host / reports / test_scripts                        |
| Fixed in  | build 90145 |
| Commit    | `c4858fb32`                                                  |

---

## Symptom

A conditional edge is one action with several possible destinations (e.g. `apps → app_home`
or `apps → app_profile`). When it fails, the Navigation editor's Go To panel lists two links —
*View target report — app_home* and *View sibling report — app_profile* — so the user sees that
neither screen matched.

The same failure inside the `kpi_measurement` script showed only the target's comparison report
on the failed step, and the Execution Summary said:

`❌ Error: KPI post-processing produced no measurements for 'apps → app_home' within 68s (0/1
successful). If the navigations succeeded, vpt-kpi.service may be lagging or not running on this host.`

The user had no way to see that the sibling had been checked too, and was sent to look at the
KPI service instead of the navigation.

## Root cause

- `NavigationExecutor.execute_navigation` already collects the target's and every failed
  sibling's report in `error_details.verification_reports` (the Go To panel reads it), but the
  script step it records for the report was written before the sibling check and never got them.
- `kpi_measurement.py` read only `sibling_landed_*` from a failed navigation's `error_details`,
  never the reports, and its "why no KPI" message had no case for a navigation that failed.

## Fix

- `navigation_executor.py` attaches the failed siblings' reports to the recorded step
  (`sibling_reports`).
- `report_step_formatter.py` lists them under the target's failed verifications in the step's
  Error Details: *"Conditional edge — the device matched neither 'app_home' nor its alternative
  destination(s)"*, each with a *View sibling report* link.
- `kpi_measurement.py` keeps the first failed navigation's error and reports, and on a failed run
  adds a `🧭 Navigation failure` block to the Execution Summary with *View target report* /
  *View sibling report* links. When no KPI was measured because the navigation failed, the error
  now says so instead of pointing at vpt-kpi.

## Verification

- Rendered `format_step_error` and the summary lines through `format_console_summary_for_html`
  with a target + sibling failure: both links render and open in a new tab.
- After deploy: run `kpi_measurement` on a conditional edge whose destination is not on screen;
  the failed step and the Execution Summary both show the target and sibling reports.
