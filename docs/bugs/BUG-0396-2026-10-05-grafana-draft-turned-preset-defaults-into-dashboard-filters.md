# BUG-0396 — A Grafana draft turned preset defaults into dashboard-wide filters

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0396                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_server (Atlas analytics, Grafana drafts)             |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Chat canvas "pass rate by device, KPI averages, incidents over the last 7 days" gave a Grafana draft with
User Interface = web_tv and Environment = Dev, Prod, Test preselected. Variables are dashboard-wide, so
"Pass Rate by Device" was filtered too (67.7%) and no longer matched the chat canvas (72.7%).

## Root cause

`resolved_request` carried the KPI preset's `default_filters` and the BUG-0330 defaulted
`userinterface_name` as ordinary filters; `GrafanaBinder` made every filter whose name has a variable
a variable selection, with no notion of who asked for it.

## Fix

`service.py`: `resolved_request` records `filter_origin` (`preset_default`, `defaulted`, `panel`; user
filters are implicit), computed in `filter_origins`; `merge_canvas_panel` keeps panel-only filters
distinguishable (device/host filters from named devices stay the user's). `grafana_drafts.py`:
`GrafanaBinder(literal=...)` inlines those filters in their own panel only, never as a variable
selection; the panel description says what it is fixed to. `filter_origin` is part of the panel
provenance, so the sha256 recompile matches. Explicit canvas/dashboard filters, named devices and
`scope: current_device` still become variable selections.

## Verification

`tests/backend_server/test_atlas_grafana_drafts.py` (origin tests, and render-vs-draft effective filters per
panel). E2E: `DASHBOARD JSON shows the template variables` and `GRAFANA canvas draft: variables not
requested are on All (JSON)` read the dashboard JSON from the logged-in Grafana context and fail when a
variable the user did not ask for is not All. Live: a local draft pushed to Grafana showed every variable on
All and Pass Rate by Device 72.7% (SQL on the same window: 72.77%).
