# BUG-0633 — Long validation runs killed at 60 min, no result written

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0633 |
| Reported  | 2026-10-18 |
| Status    | Fixed (pending deploy) |
| Severity  | High |
| Area      | backend_host / script executor |
| Fixed in  | build 90145 |
| Commit    | TBD |

---

## Symptom

TASK-133: `validation --userinterface stb_tv` on stb4 (vpt-pi1/device4) ended with no `script_result` and the
server answered `Task not found` for the task id.

## Root cause

Two things together:

1. `ScriptExecutor._execute_script_subprocess` kills every script after a hard 3600 s. A full `stb_tv` validation
   needs ~70 min on a slow box (the script itself estimated 4400 s left at minute 18). The kill is a signal, the
   validation writes its result only at the end, so the run leaves nothing. Host journal: `Script execution timed
   out after 3600 seconds (elapsed: 3600.3s)`.
2. The server's `task_manager` is in memory. Every `vpt-server` restart (two deploys on vpt-pi1 during the runs,
   16:40 and 17:21) wipes it, so `/server/script/status/<id>` answers `Task not found` while the run still goes on at the host.

## Fix

`validation` gets a 4 h limit; every other script keeps 1 h (`shared/src/lib/executors/script_executor.py`).
The restart half is operational: do not deploy a server to the node that runs the validation (check the lease;
the host keeps running and finishes, only the status poll is lost: read `script_results` instead).

## Verification

Run `validation --userinterface stb_tv` on a box that needs more than 60 min; a `script_result` exists at the end.
