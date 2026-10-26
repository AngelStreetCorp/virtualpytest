# BUG-0264 — Atlas KPI radar and device occupancy numbers differed from the dashboards

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0264                                                     |
| Reported  | 2026-10-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — the same question gave different numbers in Atlas and Grafana |
| Area      | `backend_server/src/lib/analytics/catalog.py` (KPI, occupancy, campaign/script presets) |
| Fixed in  | build 90145 |
| Commit    | `8ee5bd2bc`, `c31a83788`                                          |

---

## Symptom

Running the maintained panels' own SQL next to Atlas on the same database showed:

- KPI radar for one interface: 5 of 38 axis values differed (e.g. one KPI 1875 ms in Atlas vs
  2432 ms in Grafana) and one axis existed only in Atlas.
- Device occupancy %: sessions overlapping the range edge counted in full.
- Campaign/script pass rates: unfinished runs (no PASS/FAIL yet) counted in the denominator.

## Root cause

- KPI: Atlas grouped by the label computed per row, so one action set whose rows resolved to two
  labels became two axes, and two action sets sharing a label merged. The dashboard groups by the
  action set and aggregates the label. Atlas also treated KPI rows with no script result as
  `prod`, while the dashboard's default "all environments" filter excludes them; and KPI sample
  counts included navigation steps without a measurement.
- Occupancy: seconds were summed from session start to end, not clipped to the range, and the
  range filter used the start time instead of interval overlap.
- Pass rates: the dashboards default to PASS + FAIL, which excludes runs still in progress.

## Fix

- New `kpi_measurements` source (rows with a measurement only), grouped by action set with an
  aggregated `kpi_label`; KPI environment is the script result's own; KPI presets default to the
  dashboard's dev/test/prod selection.
- Occupancy clips each session to the range (`LEAST/GREATEST` against the trusted bounds) and
  selects sessions that overlap the range, as the dashboard does.
- Script/campaign presets default to `success in (true, false)`.

## Verification

`tests/backend_server/test_atlas_analytics_parity.py`: 11 maintained panels across every metric
family, run with their own SQL (Grafana interpolation emulated) and compared with Atlas on a frozen
window — all match. Two remaining, intentional differences are declared in the fixture: the KPI
panel can show one label twice (Atlas merges it), and the campaign panel hides a run that failed
before any script started (Atlas counts it as a failed run).
