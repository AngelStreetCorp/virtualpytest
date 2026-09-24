# BUG-0157 — Standby KPI runs lost the selected mode's display name

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0157                                                     |
| Reported  | 2026-09-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | `test_scripts/tv/standby_measurement.py`, Grafana KPI dashboards |
| Fixed in  | Unreleased                                                   |
| Commit    | `2b42a227a4`                                                 |

---

## Symptom

A standby measurement could record a raw navigation node name, or omit the configured friendly
name, in the KPI report and Grafana. This made measurements for standby modes such as cold standby,
lukewarm, and fast start hard to distinguish when they shared the same wake edge. The KPI report
could show the edge label while the KPI measurement dashboard showed a different or incomplete
label.

## Root cause

The standby script used the shared database display-name resolver. That resolver reads the base
navigation hierarchy, while the script's active graph may include variant-specific node metadata.
The selected mode's `display_name` could therefore be present in the graph used by the run but
missing from the hierarchy the resolver queried. Grafana panels also preferred the edge's
`kpi_name` or label over the run's stored `kpi_display_label`.

## Fix

The script now checks the active navigation graph first for the selected mode node's
`display_name`, then uses the shared database resolver as a fallback. The KPI measurement and KPI
test report dashboards now prefer the recorded KPI display label, with the edge name retained as
context where appropriate. The standby script documentation explains that the mode node controls
the run-level display name and the wake edge supplies the transition label or fallback.

## Verification

Confirm a standby run on a variant whose selected mode node has a `display_name`. The run's KPI
report and Grafana KPI panels should show that friendly mode name, with the measured edge available
as context. JSON parsing and the bug index / metadata checks are run with this change.
