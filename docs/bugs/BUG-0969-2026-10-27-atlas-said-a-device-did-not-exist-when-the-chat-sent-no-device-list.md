# BUG-0969 — Atlas said a device did not exist when the chat sent no device list

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0969                                                     |
| Reported  | 2026-10-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend / agent                                              |
| Fixed in  | build 90256 |
| Commit    | TBD                                                          |

---

## Symptom

During the TASK-179 P4 live check, `scripts/atlas_chat.py --scope all "Release control of device1 on host
lenovo-local-low."` was answered at once with `I can't find a device named "lenovo-local-low/device1": I don't see any
device on this server right now.` No tool ran and the device (on vpt-pi4's server, locked by the previous turn) stayed
locked. The same request worded at length went to the full model and worked.

## Root cause

The Atlas quick step (`backend_server/src/agent/quick_step.py`, `missing_device`, TASK-175) checks the device the
small model picked against `available_devices`, the list the chat page sends with each message. A client that sends
no list (the chat script, any API caller) has an empty list, so every device counted as missing and the turn ended
with the "no such device" answer before the model or the TASK-179 owner lookup could find it on another server.

## Fix

`missing_device` returns `None` when there is no list to check against: the turn goes on to the model, whose tools
find the owning server. The "I don't see any device on this server" text is gone. A page that does send its device
list keeps the TASK-175 behaviour. Test: `tests/backend_server/test_agent_routing_rules.py`
(`test_a_device_that_is_not_there_is_named_back`).

## Verification

After deploy, `scripts/atlas_chat.py --scope all "Release control of device1 on host lenovo-local-low."` calls
`release_control` and `lockedDevices?scope=all` no longer lists `vpt-pi4:lenovo-local-low:device1`.
