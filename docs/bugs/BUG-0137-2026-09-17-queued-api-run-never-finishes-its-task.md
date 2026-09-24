# BUG-0137 — A queued API run finished, but the caller polling it was never told

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0137                                                                    |
| Reported  | 2026-09-17                                                                  |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | Medium (the run itself is fine and fully recorded; only the caller's task is orphaned, so an API client polling for its result waits forever) |
| Area      | `backend_server/src/routes/server_deployment_routes.py`                     |
| Fixed in  | Unreleased                                                                  |
| Commit    | `389df6ce21` |

---

## Symptom

`POST /server/script/execute` against a device that is already locked queues the run and hands
back a `task_id`, promising that the task "stays open and is completed by
`/server/deployment/executionComplete` with the run's real result".

The run executes. The task never completes.

```
status=started | script_success=None | queued=True | completed_at=None     ← 30+ min later
```

Everything else is correct — this is visible only from the caller's side:

| | |
|---|---|
| `deployments` row | `status: completed`, `execution_count: 1`, `last_executed_at` set |
| `script_results` row | present, `completed_at` set, `success: f` |
| device lock | released |
| caller's task | `started`, forever |

Host log for the same run:

```
[@deployment_scheduler] Dequeued deployment 4bbd6ce8… for device device2
[@deployment_scheduler] Executing command: python goto.py … --node shorts …
[@deployment_scheduler] Extracted script_result_id: 32bba7f3…
[@deployment_scheduler] Deployment 4bbd6ce8… completed: False
[@deployment_scheduler] Marked as completed: 4bbd6ce8…
```

Tasks do not expire on their own, so the task is orphaned permanently and the only way to learn
the outcome is to read the host journal or query `script_results` directly.

## Root cause

`execution_complete()` hands the result back to the waiting caller by reading the queued task id
off the deployment:

```python
queued_task_id = ((deployment or {}).get('rerun_payload') or {}).get('queued_task_id')
if queued_task_id:
    task_manager.complete_task(queued_task_id, result_payload, error=error, ...)
```

but `deployment` is fetched without that column:

```python
dep_res = supabase.table('deployments').select(
    'id, team_id, name, host_name, device_id, script_name'      # no rerun_payload
).eq('id', deployment_id).single().execute()
```

So `queued_task_id` is always `None` and `complete_task` never runs. The row does hold it:

```
rerun_payload | {"type": "script", …, "queued_task_id": "214b0c02-…"}
```

The two *failure* paths that resolve the same task both select the column correctly —
`_abort_stale_queued_executions` uses `deployments!inner(team_id, rerun_payload)` and
`abort_queued_execution` uses `deployments(rerun_payload)`. Only the success path omitted it,
which is the inversion that let this sit unnoticed: a caller is told when its queued run is
dropped or aborted, but not when it actually runs.

It also needs an unusual approach to reach. The queue only engages for a caller that sets
`queue_if_locked` (the default for the API); the UI's rerun button sends `queue_if_locked=false`
and takes the `423` instead. So no browser user can hit this — only an API client firing at a
device that is already busy, which is the case `/server/script/execute`'s server-side queue was
added for (BUG-0118).

Found while re-running `goto.py` repeatedly against one phone during BUG-0135: runs fired faster
than the device freed up, so one went through the queue and its task never returned.

## Fix

Add `rerun_payload` to the select in `execution_complete()`.

## Verification

Fire two `/server/script/execute` calls at the same host/device back to back, with
`queue_if_locked` left at its default. The second response carries `queued: true` and a
`deployment_id`; when the device frees and the queued run finishes, its `task_id` must reach
`completed`/`failed` with the run's real `script_success`, rather than staying `started`.

Not yet verified live: the fix is committed but not deployed, so the behaviour above still
reproduces on the running server until `update_core.sh` ships it.
