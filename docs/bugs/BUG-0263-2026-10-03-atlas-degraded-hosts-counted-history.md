# BUG-0263 — "Show degraded hosts" listed every device that had been degraded in the last 30 days

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0263                                                     |
| Reported  | 2026-10-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — a recovered device still read as degraded           |
| Area      | `backend_server/src/lib/analytics/catalog.py` (fleet health) |
| Fixed in  | build 90145 |
| Commit    | `8ee5bd2bc`                                                       |

---

## Symptom

The `degraded_hosts` preset returned devices that were healthy now but had a DEGRADED or DOWN
verdict at any point in the trailing 30 days, with a count per device.

## Root cause

The preset aggregated the whole `fleet_health` history in the time range. The Fleet Health
dashboard's *Live — per device* panel only shows the rows of the newest live check.

## Fix

New source `fleet_health_latest`: rows of the newest check per run kind within the caller's
device scope (exactly the panel's `generated_at = max(generated_at)` rule). `degraded_hosts`
uses it with `run_kind = live`; `fleet_verdicts` gives the verdict counts. History stays on
`fleet_health` (`fleet_verdicts_over_time`).

## Verification

- `test_latest_fleet_uses_newest_scoped_check_not_history`, `test_show_degraded_hosts_uses_fleet_health`.
- Parity case `fleet_live_per_device` matches the panel row for row.
