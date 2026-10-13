# BUG-0410 — A Grafana draft built from "my selected devices" opened with Host and Device on All

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0410                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | backend_server (analytics Grafana drafts)                    |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

A canvas built from "my selected devices" (BUG-0405 sets `scope='current_device'`, Target host-clone-1 / host-clone-1_Host)
opened in Grafana with the Host and Device variables on All while every panel was literally limited to that device. Naming the
device ("for host-clone-1") opened the draft with Host = host-clone-1 preselected.

## Root cause

`scope='current_device'` compiled into a literal host/device clause in the draft. Only filters (named devices) were bound to
the dashboard variables.

## Fix

In `GrafanaDraftService._panel`, a user-origin `scope='current_device'` becomes `filters.host_name` / `filters.device_name`
(from the already resolved context) bound to `$host` / `$device_name` with the device preselected, like a named device. The
chat-side query is unchanged. A panel's own scope (not the canvas-level one) is recorded as `filter_origin.scope = panel` and
stays literal; sources keyed by device id, explicit device/host filters, or a template without those variables also stay
literal. The provenance query holds the converted filters (or the literal scope plus its origin), so the recompile matches.

## Verification
- `tests/backend_server/test_atlas_grafana_drafts.py`: current_device canvas -> host/device_name variables preselected, panels
  bound (not literal), provenance valid; panel-only scope literal; named device unchanged.
- Suite prompt `selecteddev` reads the draft's variables from the logged-in Grafana context.
