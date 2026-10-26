# BUG-0477 — The script-execute API ran scripts on targets their target rules forbid

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0477                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend                                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

A script whose `_target_rules` say `target_type: "host"` (it must run on the host target,
`device_id` `host`) is only offered on the host target in the web app, but
`POST /server/script/execute` accepted any `device_id`. Called with `device_id: "device1"`, the
run went to that device and was recorded against it (the device's name in the results list),
and on a host with no host target it was accepted as well. The same gap existed for
`target_type: "device"` scripts sent to `host`, for `host_os`, and for `device_model`.

## Root cause

Target compatibility was only checked in the frontend
(`frontend/src/utils/targetCompatibility.ts`, `isTargetKeyCompatibleWithRules`) before a
target is offered. `execute_script()` in `backend_server/src/routes/server_script_routes.py`
validated the host and the variant, never the script's `_target_rules`.

## Fix

`target_incompatibility(rules, host, device_id)` in
`shared/src/lib/utils/script_target_rules_utils.py` ports the frontend rules (host OS,
`target_type` host / device / all including "host has a host target", `device_model` with model
families via `get_compatible_models`). `execute_script()` reads the script's `_target_rules`
(`extract_script_target_rules`) and answers **400** with the reason before locking the device.
Scripts without `_target_rules` and virtual scripts are not checked, so existing API callers of
rule-less scripts keep working.

## Verification

- `pytest tests/shared/test_script_target_compatibility.py` (host script: host OK, device
  refused, host without host target refused; device script on host refused; model and OS rules).
- On a server with the fix: `POST /server/script/execute` with a `target_type: "host"` script
  and `device_id: "device1"` returns 400 `Target not allowed … host target only`; the same call
  with `device_id: "host"` on a host that has a host target starts the run.
