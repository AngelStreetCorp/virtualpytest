# BUG-0320 — Analytics time series without time_grain drew raw rows

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                      |
|-----------|--------------------------------------------|
| ID        | BUG-0320                                     |
| Reported  | 2026-10-04                                 |
| Status    | Fixed (pending deploy)                     |
| Severity  | Medium — a trend chart showed a flat line at 1         |
| Area      | backend_server/src/lib/analytics/service.py |
| Fixed in  | build 90145 |
| Commit    | see branch task43-w7-analytics-r3           |

---

## Symptom

A line/area chart grouped by a time dimension with no time_grain returned one raw row per timestamp (100 rows, each count 1).

## Root cause

compile() only truncated time dimensions when time_grain was given.

## Fix

With metrics grouped by a time dimension and no grain, the grain defaults from the range (<= 2 days hour, else day) and is disclosed in the result (`time_grain_defaulted`) and the artifact (`options.time_grain_note`).

## Verification

`python3 -m pytest -q tests/backend_server -k "atlas or minimax or analytics or agent"` (`test_time_dimension_without_grain_defaults_from_the_range / test_defaulted_grain_is_disclosed_in_result_and_artifact` in `tests/backend_server/test_atlas_analytics.py`).
