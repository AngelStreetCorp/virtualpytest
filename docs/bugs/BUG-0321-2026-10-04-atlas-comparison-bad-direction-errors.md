# BUG-0321 — Analytics comparison failed on an unrecognised direction

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                      |
|-----------|--------------------------------------------|
| ID        | BUG-0321                                     |
| Reported  | 2026-10-04                                 |
| Status    | Fixed (pending deploy)                     |
| Severity  | Low — one failed call         |
| Area      | backend_server/src/lib/analytics/service.py |
| Fixed in  | build 90145 |
| Commit    | see branch task43-w7-analytics-r3           |

---

## Symptom

query_kpi_radar/compare raised 'direction must be lower_is_better or higher_is_better' for another value.

## Root cause

compare() validated the direction before the metric's own preferred direction was applied.

## Fix

An unrecognised direction is ignored; the metric's direction is used and `direction_note` says so.

## Verification

`python3 -m pytest -q tests/backend_server -k "atlas or minimax or analytics or agent"` (`test_comparison_rejects_positional_or_bad_configuration` in `tests/backend_server/test_atlas_analytics.py`).
