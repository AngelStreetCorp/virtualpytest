# BUG-0089 — A virtual script that never ran is recorded as SUCCESSFUL

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0089                                                                    |
| Reported  | 2026-09-15                                                                  |
| Status    | Deploy warning added + live workaround applied; the silent-success path itself is NOT fixed |
| Severity  | High (a run that never executed reports green — the worst possible failure mode) |
| Area      | `setup/proxmox/node/update_core.sh` · `backend_host/src/routes/host_script_routes.py` · `backend_server/src/routes/server_script_routes.py::task_complete` |

---

## Symptom

Every virtual script dispatched to `labox-web` "completed" in ~90 ms. No
`script_results` row was written, no report, no logs — and
`deployment_executions` recorded `status=completed, success=true, error_message=NULL`.

The server log shows a clean, healthy-looking dispatch:

```
[@call_host] 🔗 Connecting to host 'labox-web'
[@route:server_script:execute_script] Host execution started for task 34cced33-…
[@route:server_script:task_complete] Device unlock for labox-web:host: success
[@route:server_script:task_complete] Task 34cced33-… marked as completed
```

Nothing anywhere says the script did not run.

## Root cause — three failures stacked

**1. The deploy silently leaves the tree unwritable.** `update_core.sh` fixed
ownership with:

```bash
run_ssh "$host" "sudo -n find $TARGET_DIR … -exec chown vpt_user:vpt_user {} + 2>/dev/null || true"
```

`jndoye` has no passwordless sudo on `labox-web`, so `sudo -n` fails, `2>/dev/null`
eats the message and `|| true` keeps the deploy green. 201 of 219 paths under
`/opt/virtualpytest` stayed `jndoye:jndoye` (mode 775), so **`vpt_user` could not
write `test_scripts/`** — which is precisely where a virtual script materializes
its `.vs_<uuid>.py`. Every deploy re-breaks it.

**2. The host reports nothing.** `execute_script` returns early when
materialization fails; `execute_async` posts the callback with
`slim_result = {}` and **no `error` key**.

**3. The server reads "no error" as "passed."**
`server_script_routes.py::task_complete`:

```python
script_success = result.get('script_success')
adhoc_success = script_success if script_success is not None else not bool(error)
```

An empty result with no error yields `adhoc_success = True`. A run that never
started is indistinguishable from one that passed.

## Evidence

`labox_w9_replay` and `labox_w10_series_detail` (both virtual) ran green on
labox-web at 15:40. The deploy landed at 19:53. Every virtual run after it
"completed" instantly with no row. After `chmod 777 /opt/virtualpytest/test_scripts`,
a virtual `dailymotion_video_check` ran on labox-web in 72 s with a report —
versus the same script before the fix producing no row at all.

## Fix

**Live:** `chmod 777 /opt/virtualpytest/test_scripts` on `labox-web` (jndoye owns
it, so no sudo needed). **This does not survive a deploy** — re-apply, or give
`jndoye` passwordless sudo there.

**In the repo:** `update_core.sh` no longer swallows the chown failure. It reports
the host, names the consequence, prints the workaround, and lists every affected
host under `⚠️ OWNERSHIP NOT FIXED` in the deploy summary.

## Not fixed — the actual silent success

The stacked failure remains reachable by any other early return. Two changes are
needed, neither made here because both alter the host/server contract:

1. `ScriptExecutor.execute_script` should return `{'success': False, 'error': …}`
   when materialization fails, and `_materialize_virtual_script` should raise
   rather than return falsy (`script_executor.py` — "Virtual script not found"
   is currently only a `print`).
2. `task_complete` should treat a callback with **no `script_success` and no
   `script_result_id`** as a failure, not a pass. Absence of evidence that a
   script ran is not evidence that it passed.

Also open: `resolve_virtual_script_libs` only `print`s and skips a lib it cannot
fetch, so a script missing its library fails later with a confusing ImportError
instead of a clear "library not found".
