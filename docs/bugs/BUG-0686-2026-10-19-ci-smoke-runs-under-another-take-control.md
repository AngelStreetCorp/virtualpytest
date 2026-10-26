# BUG-0686 — CI smoke scripts ran on a device under another session's Take Control

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0686                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                       |
| Area      | backend_server device locks / CI smoke runner |
| Fixed in  | build 90145 |
| Commit    | `8e7e681c5`                                                  |

---

## Symptom

During the TASK-135 benchmark the harness held a Take Control lock on host-clone-1/host (heartbeat every 60 s), yet post-push CI smoke scripts
(`smoke_ui`, `smoke_device_control`, ...) drove the same browser every 10-40 min, and the agent's tool calls got "in use by ... (script_execution)".

## Root cause

The script, testcase and campaign launch routes acquire the lock with `allow_same_user_takeover=True`: a caller may run a script under its own
Take Control. The smoke runner calls with the service API key and the harness used the auto-sign token; neither is a personal login, so both
locks carry the built-in default user id, and `DeviceLockManager.acquire_lock` took "same user id" as the same person: the smoke ran as a
subordinate of the harness's lock. `live_foreign_execution` already refused to treat the shared default ids as one caller; `acquire_lock` did not.

## Fix

- `backend_server/src/lib/utils/lock_utils.py`: `same_user` is false for the shared default ids (`_shared_user_ids()`); the same session still matches.
- `tests/test_scripts/run_vpt_smoke.py`: sends `queue_if_locked=false` (a queued run would start after the runner gave up) and skips a device
  under Take Control at once; the CI smoke report shows SKIP rows and a Skipped tile.

## Verification

`tests/backend_server/test_lock_shared_user_takeover.py`, `tests/test_scripts/test_run_vpt_smoke.py`.
