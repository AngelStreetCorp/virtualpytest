# BUG-0850 — "Take control of all stb" failed with `take_control: unknown command: take_control`

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0850                                                          |
| Reported  | 2026-10-23                                                        |
| Status    | Fixed (pending deploy)                                            |
| Severity  | High                                                             |
| Area      | backend_server (Atlas skills, MCP tools) / ai                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                               |

---

## Symptom

In the Atlas chat, "Take control of all available stb and if not awake wake them up" answered
`0/1 failed: take_control: unknown command: take_control` and did nothing.

## Root cause

The prompt hits one trigger ("all stb") of the `control-device-group` skill. That skill's tools were
`list_device_groups, list_actions, execute_group_action, capture_screenshot` — no `take_control` — and `take_control`
is hidden from the model's tool listing. The model put `{"command": "take_control"}` in the `actions` of
`execute_group_action`; that list goes to the remote controller, which answers `unknown command`
(`backend_host/src/controllers/remote/bluetooth.py`). Nothing checked that an action was a remote command.

## Fix

- `control-device-group` skill: `take_control`, `release_control` and `execute_device_action` are allowed tools, and a
  section says how to take control of / release / wake all devices of a model (one device is not a group).
- `execute_device_action` and `execute_group_action` refuse `take_control` / `release_control` as an action command
  and name the tool to call (`lock_command_error`, `tests/backend_server/test_lock_command_error.py`).

Found by TASK-163 (`docs/agent/atlas/USECASES.md`, UC-008).
