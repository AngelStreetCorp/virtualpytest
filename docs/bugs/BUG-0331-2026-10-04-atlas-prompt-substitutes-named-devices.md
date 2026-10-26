# BUG-0331 — Atlas dropped the device filter and charted other devices

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                      |
|-----------|--------------------------------------------|
| ID        | BUG-0331                                     |
| Reported  | 2026-10-04                                 |
| Status    | Fixed (pending deploy)                     |
| Severity  | Medium — a canvas titled after devices the user never named         |
| Area      | backend_server/src/lib/analytics, backend_server/src/agent/core/manager.py |
| Fixed in  | build 90145 |
| Commit    | see branch task43-w9-kpi-default           |

---

## Symptom

Asked for devices samsung SM-G998B and Phone slot 1 (absent on the server), Atlas dropped the filter, charted all devices and titled the canvas "S21x & stb4".

## Root cause

BUG-0323 flags a filter the model sent that matched nothing; it cannot flag one the model never sent.

## Fix

The router prompt now carries a "Named devices" rule: pass named devices exactly as `filters={"device_name": [...]}`; if nothing matches say so and offer the closest names; never substitute, drop the filter or title the result after other devices.

## Verification

`test_router_prompt_forbids_substituting_named_devices` in `tests/backend_server/test_agent_minimax_quirks.py`.
