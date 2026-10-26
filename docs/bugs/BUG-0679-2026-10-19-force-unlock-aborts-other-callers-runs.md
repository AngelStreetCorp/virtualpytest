# BUG-0679 — force_unlock aborted other callers' live runs on the device

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0679                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_server / device locks / MCP                          |
| Fixed in  | build 90145 |
| Commit    | see the merge commit of fix/force-unlock-no-abort-others     |

---

## Symptom

An AI agent called `execute_device_action` on a busy device, was told "in use by ... (script_execution)", retried with `force_unlock=true`, and the server SIGTERM-ed whatever was running there, including other sessions' scripts. Two CI smoke runs on one host were killed that way (exit -15 two seconds after start; a deployment run killed). Any caller could kill any other caller's or user's run.

## Root cause

`force_unlock` on the MCP tools (via `/server/control/takeover` with `stop_running_execution`) and on `/server/script/execute` and campaign execute (via `abort_and_force_unlock`) called the host's abort endpoints without checking who owned the run or whether it was still alive.

## Fix

New `live_foreign_execution()` in `backend_server/src/lib/utils/lock_utils.py`. force_unlock may clear a stale lock (the host's `is_busy` reports nothing running) or the caller's own lock (same session or user). Otherwise it refuses with `errorType: device_busy`, HTTP 409: "device busy: <reason> by <owner> since <t>; force_unlock does not abort another caller's live run". An unreachable host counts as live. Used by `abort_and_force_unlock(protect_others=True)` (script and campaign execute) and by `/takeover` when `protect_live_execution` is set (MCP `auto_lock`). The human paths keep working unchanged: the UI Force Takeover dialog and `/forceUnlock`. MCP tool descriptions say force_unlock does not kill others' runs.

## Verification

`tests/backend_server/test_force_unlock_protects_live_runs.py` (stale cleared, own cleared, other's live script not aborted with the refusal text, human path unchanged) and `test_mcp_auto_lock_owner.py::test_force_unlock_on_another_callers_live_run_is_refused_with_device_busy`.
