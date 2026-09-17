# BUG-0006 — Scheduled script keeps running after force take-control

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0006                                                     |
| Reported  | 2026-07-20                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | device locks / deployment scheduler / abort                  |
| Fixed in  | build 8414                                                   |
| Commit    | `320490598`                                                    |

---

## Symptom

A user force-took control of a device that was running a **scheduled** test run. The UI
reported the takeover succeeded and handed them the device — but the scheduled script kept
running and kept driving the STB underneath them. Two actors on one device.

Reported as "I thought we fixed this before": the abort-on-takeover machinery was added
2026-03-02 (`6640cb7f3`) and does work for interactive runs. It never worked for scheduled
ones.

## Root cause

Three independent defects stacked. The first is the one the user hit.

### 1. Scheduler registered its process under the wrong key

`backend_host/src/services/deployment_scheduler.py:1494` built the executor positionally:

```python
executor = ScriptExecutor(self.host_name, dep['device_id'], 'unknown')
```

`ScriptExecutor.__init__` is
`(script_name=None, description="", host_name=None, device_id=None, device_model=None, ...)`
(`shared/src/lib/executors/script_executor.py:657`). So the three values landed in
`script_name` / `description` / `host_name`, and **`device_id` stayed `None` → defaulted to
`"unknown-device"`** (`:666`).

The kill registry `_running_processes_by_device` is keyed by `device_id` (`:63`, registered
at `:940`). Every scheduler- and queue-launched script therefore registered itself under the
literal key `"unknown-device"`. On takeover the server sent the *real* device_id to
`/host/script/abort`, the dict lookup at `:114` missed, and the process was never signalled.

Both the cron path (`deployment_scheduler.py:731`) and the queue-drain path (`:813`) funnel
into `_execute_deployment` → line 1494, so both were affected. The campaign branch
(`campaign_executor.py:472`) already used keyword args and was never affected.

### 2. The miss was reported as success

`abort_running_script` returns `{'success': True, 'aborted': False}` with HTTP 200 when the
key isn't found (`script_executor.py:114-121`) — correct on its own, since a zombie lock
legitimately has nothing running. But `abort_running_execution` treated any 200 as success
and dropped `aborted` into an unread `details` blob. No caller ever inspected it, so a total
failure to find the process was indistinguishable from a successful kill. This is why the
bug survived a previous "fix" and produced no error anywhere.

### 3. Campaigns and testcases were never aborted at all

- **Campaigns:** `abort_running_execution` only called `/host/script/abort` and
  `/host/deployment/abortRunning`. A campaign runs N scripts in a loop; killing the current
  child just advanced `CampaignExecutor` to the next script. The cooperative flag
  (`campaign_executor.py:94`, polled at `:214`/`:276`/`:387`) is only reachable via
  `/host/campaigns/abortRunning`, which no force-unlock path called.
- **Testcases:** they take **no device lock at all** (no `acquire_device_lock` anywhere in
  `server_testcase_routes.py`) yet drive real devices through the same controllers
  (`testcase_executor.py:351-369`). Since the abort branch was gated on
  `owner_type in ('script_execution','deployment_execution')`, and a testcase has no lock and
  thus no owner_type, it was never a candidate for abort.

## Fix

- **`deployment_scheduler.py:1494`** — keyword args, so `device_id` reaches the registry.
- **`script_executor.py:_register_running_process`** — logs a loud warning when asked to
  register under a falsy or `"unknown-device"` key, so this class of regression is visible at
  launch rather than only at abort time.
- **`lock_utils.abort_running_execution`** — now returns `success` (calls reached the host)
  and `aborted` (the host actually stopped something) as separate values, and fans out to
  `/host/testcase/abortRunning` (unconditionally, since testcases hold no lock),
  `/host/campaigns/abortRunning` and `/host/script/abort`, plus
  `/host/deployment/abortRunning` for `deployment_execution`.
- **`lock_utils.abort_and_force_unlock`** (new) — single implementation of the
  abort-then-force sequence that was duplicated across three routes
  (`server_control_routes.py`, `server_script_routes.py`,
  `server_campaign_execution_routes.py`) with inconsistent failure semantics. The split is
  now explicit: `strict=True` for script/campaign execute (a new run is about to start —
  refuse on abort failure) and `strict=False` for `/forceUnlock` (a human is reclaiming the
  device — always clear the lock rather than leave them wedged behind an unreachable host).
- **`server_control_routes.py` `/takeover`** — logs a warning when the abort stopped nothing,
  and best-effort aborts a running testcase when the device has no execution lock.
- **`testcase_executor.py`** — the abort flag was only polled at the top of the tracked block
  loop (`:1126`), so a loop body or nested graph ran to completion regardless. The
  execution_id now rides on the context (`testcase_execution_id`) and `_is_aborted()` is
  polled in `_execute_graph`'s node loop and `_execute_loop_block`'s iteration loop.

## Verification

Static only — **this has not been run against a live host or device.**

1. Traced the full chain by reading the code: constructor signature → `self.device_id`
   default → `_register_running_process` key → `abort_running_script` lookup → `lock_utils`
   success determination. The key mismatch is unambiguous from the sources.
2. Confirmed `/host/testcase/abortRunning` and `/host/campaigns/abortRunning` exist, are
   mounted at the assumed prefixes (`host_testcase_routes.py:12`,
   `host_campaign_routes.py:20`), and return the `{success, aborted}` shape the new
   fan-out reads.
3. Confirmed `force_unlock` on a device with no lock returns `success=True, released=False`,
   so routing the no-lock case through `abort_and_force_unlock` is safe.
4. `py_compile` clean on all seven touched files.

**Still to confirm on a deployed host:** schedule a run, force take control mid-execution,
and check the script actually dies — `journalctl` should show the abort with `aborted=True`
rather than the new "aborted nothing" warning.

## Notes / left alone

- **Testcases still take no device lock.** Acquiring one is easy; releasing it is not —
  testcases have no `taskComplete` callback, so release needs either a server-side completion
  callback or a hook off the host socket event. Done wrong it leaks zombie locks, which is
  the existing deployment-queue failure mode. Left as a design decision.
- **The synchronous testcase path is still unabortable.** `execute_testcase_from_graph` →
  `_execute_graph` never registers in `self._executions`, so there is no flag to set. Making
  it abortable means registering it.
- **Plain `/takeControl` still does not abort testcases** — only `/takeover` does. Aborting
  someone's testcase on an ordinary take-control is a behaviour change worth opting into
  deliberately.
- **The registry holds one process per device**, so concurrent runs on a single device remain
  unkillable except for the last one registered.
- **`terminate()`/`kill()` target only the direct child**, so a script that spawns its own
  subprocesses can still leave orphans.
