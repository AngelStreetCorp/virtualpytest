# BUG-0355 — Atlas dropped the device filter the user named and charted other devices

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0355                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend (Atlas analytics / agent)                            |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Asked for a chart "for devices samsung SM-G998B and Phone slot 1" (devices not on the selected server), Atlas sometimes sent no `device_name` filter, charted other devices and titled the canvas after the devices the user named. BUG-0323/BUG-0331 added a prompt rule and a note for a filter that was *sent* and matched nothing; neither catches a filter the model never sent.

## Root cause

Enforcement depended on the model. Nothing in the pipeline knew which devices the user had named.

## Fix

- `backend_server/src/lib/analytics/named_devices.py`: whole-phrase, case-insensitive mention detection against every known device name, classified on-selected-server or not.
- `QAManagerAgent._record_named_devices` stores the result per message in the session context (`named_devices`) and the router prompt carries "User named devices: ...". `ToolBridge` injects `_context_named_devices` and `_context_known_device_names`.
- `analytics_tools.py` (`enforce_named_devices`, `sanitize_titles`): a request with no device/host filter gets `filters.device_name` = the named devices on this server, disclosed in the reply; when none is on this server the tool returns no data and a note, never other devices; titles naming a known device outside the effective filter are replaced with a neutral title and disclosed.

## Verification

`tests/backend_server/test_atlas_analytics.py` (`test_named_device*`, `test_titles_never_name_devices_outside_the_filter`) and `tests/backend_server/test_agent_minimax_quirks.py::test_user_named_devices_are_recorded_and_put_in_the_router_prompt`.
