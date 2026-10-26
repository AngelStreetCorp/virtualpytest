# BUG-0330 — KPI presets failed when no user interface was given

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                      |
|-----------|--------------------------------------------|
| ID        | BUG-0330                                     |
| Reported  | 2026-10-04                                 |
| Status    | Fixed (pending deploy)                     |
| Severity  | Medium — every KPI canvas cost 1-3 failed tool calls         |
| Area      | backend_server/src/lib/analytics, backend_server/src/agent/core/manager.py |
| Fixed in  | build 90145 |
| Commit    | see branch task43-w9-kpi-default           |

---

## Symptom

Canvas prompts with KPI averages failed with "Missing preset filters" and the model retried with wrong fields (5/5 runs).

## Root cause

kpi_radar/kpi_trend/kpi_slowest require userinterface_name (KPIs only compare within one interface) and the service raised when it was absent.

## Fix

The service defaults it: the conversation's current interface (now passed to analytics as `_context_userinterface_name`), else the interface with the most KPI samples in the request's scope and time range (one grouped query through the normal query path, so scope/server narrowing and Pi forwarding apply). The choice is disclosed in `options.defaulted_filters` / `defaulted_filters_note`, in the tool reply and in the viewer (once per canvas). No KPI samples at all renders the normal empty result.

## Verification

`python3 -m pytest -q tests/backend_server -k "atlas or minimax or analytics or agent"` (`test_kpi_preset_*`); vitest `AnalyticsArtifactViewer` (defaulted-interface note once per canvas).
