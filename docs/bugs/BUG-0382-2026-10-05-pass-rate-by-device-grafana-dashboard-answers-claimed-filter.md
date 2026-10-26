# BUG-0382 — "Pass rate by device" Grafana dashboard answers claimed filters were preselected; named devices were ignored by drafts

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0382                                                       |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                           |
| Area      | backend                                                   |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

For "create a Grafana dashboard with pass rate by device and incidents over time" the answer said the Workspace, Host and Device variables were "preselected to current context". If Host/Device were really narrowed to the chat's device, "pass rate by device" would show one device.

## Root cause

The draft code itself only preselects values present in the request filters; nothing is taken from the chat's current device unless the model passes `scope='current_device'`. The wrong claim came from the tool text, which listed the variables without saying what was preselected, so the model invented "current context". Separately `create_grafana_draft` skipped `enforce_named_devices`, so a device the user named (BUG-0355) was not applied to drafts.

## Fix

The tool reply now states `Preselected filters: none. Every variable starts on All (Workspace keeps its normal default)` when nothing was asked for, labels explicit ones "(only values the user asked for)", and reports panels limited to the current device in the query. `create_grafana_draft` applies named devices like the render path. The tool description and the `grafana-dashboard` skill say to pass a filter or `current_device` only when the user asked, and to claim a preselection only when the tool lists it.

## Verification

`tests/backend_server/test_atlas_dashboard_template.py`: chat context (host, device, interface, workspace) preselects nothing and the pushed variables stay on All; a named device is preselected and disclosed.
