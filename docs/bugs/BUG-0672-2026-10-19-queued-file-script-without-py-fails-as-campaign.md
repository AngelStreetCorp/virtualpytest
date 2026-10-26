# BUG-0672 — A queued file script without ".py" failed as "no DB campaign found" (vpt-smoke flake)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0672                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host deployment scheduler / CI                       |
| Fixed in  | build 90145 |
| Commit    | see the merge commit of fix/vpt-smoke-script-lookup          |

---

## Symptom

The gating CI job `vpt-smoke` failed intermittently with a different script each time: run 3473 `vpt/smoke_ui` (36.8 s), run 3475 `vpt/smoke_network_server` and `vpt/smoke_video_stream` (21.0 s each), all `ValueError: '<name>' is not a .py script and no DB campaign found with that name`. Passing scripts in the same run took 5-11 s; the failures took longer.

## Root cause

`tests/test_scripts/run_vpt_smoke.py` posts `script_name: "vpt/smoke_ui"` (no `.py`) to `/server/script/execute`. When the device is free the host runs it directly and `ScriptExecutor` appends `.py`. When another run holds the device lock, the route queues the run as a one-shot deployment (`server_script_routes.py`, BUG-0118) carrying the same extension-less name. The host `deployment_scheduler` then classified every name without `.py` as a DB campaign, found none and raised. So the failure depends on whether something else (another CI job, an e2e run) held `host-clone-1:host` at that moment, which is why the script differed per run. Not a missing file: `test_scripts/vpt/` is present.

## Fix

`backend_host/src/services/deployment_scheduler.py`: a name without `.py` is a DB campaign only if one exists; otherwise, if it resolves to a file under `test_scripts/` (new `_is_file_script`), it runs as a file script. The "no DB campaign" error remains for names that are neither, and a campaign lookup exception is only raised when no such file exists. Needs a host deploy.

## Verification

`tests/backend_host/test_deployment_scheduler_file_script.py`.
