# BUG-0311 — Atlas told the model to use a device the selected server does not own

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                      |
|-----------|--------------------------------------------|
| ID        | BUG-0311                                     |
| Reported  | 2026-10-04                                 |
| Status    | Fixed (pending deploy)                     |
| Severity  | Low — one wasted failing tool call         |
| Area      | backend_server/src/agent/core/manager.py, lib/analytics/service.py |
| Fixed in  | build 90145 |
| Commit    | see branch task43-w5-scope-hints           |

---

## Symptom

On RPI1-server (build 9777) the chat Target was host-clone-1:host, a device of the main server. The prompt said my selected devices = Current Device, so render_analytics_artifact(scope='current_device') failed with 'The current device is not registered on the selected server'; the model recovered on its second call.

## Root cause

The analytics scope line only checked that a host and device were set, ignoring selected_server_hosts (the selected server's host list).

## Fix

When the selected server's host list is known and the current host is not in it, the router prompt uses a new scope line (not a valid selection, use scope='visible'). The service's 'not registered' error now also says: do not ask, retry with scope='visible'.

## Verification

`python3 -m pytest -q tests/backend_server -k "atlas or minimax or analytics or agent"` (regression tests added in
`test_agent_minimax_quirks.py` / `test_atlas_analytics.py`).
