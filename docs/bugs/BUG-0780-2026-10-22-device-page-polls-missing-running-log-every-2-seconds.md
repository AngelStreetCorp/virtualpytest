# BUG-0780 — A stuck deployment row keeps two hosts "busy" and makes the Device page poll a running.log that does not exist every 2 seconds

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0780                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | frontend / backend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-05, CHAOS-06, in `docs/tasks/QA-CHAOS-findings.md`, `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** /device-control, /run/tests target list, run progress strip
- **Viewport / theme:** 1440 px dark and light; 390 px dark

Steps to reproduce:

1. Open Device with nothing running on the lab hosts.
2. Open the console and the network panel and wait about 30 seconds.

**Expected:** No running-log requests for idle hosts and a clean console.

**Actual:** `GET /host/<host>/stream/capture/hot/running.log` is polled every 2 seconds and answers 404 each time (CHAOS-06 also saw a 401 on host-clone-1 and 404 on host-clone-2); the host logs `Running log not found` for each. `getAllHosts` reports the `host` pseudo-device of host-clone-1 and host-clone-2 with `has_running_deployment: true`, so the Run page padlocks their `host_vnc` targets and queues new browser runs behind it. The run progress strip shows the stuck execution as "host reported no script result".

Evidence:

- [ops-05-device-running-log-404.png](../tasks/qa-evidence/ops/ops-05-device-running-log-404.png)
- [desktop-dark-device-control.jpg](../tasks/qa-evidence/chaos/desktop-dark-device-control.jpg)

Related bugs: BUG-0759, BUG-0035.

## Root cause

Two halves, one origin.

**(1) The host reports "busy" forever.** The host decides which of its devices are busy by reading the `deployment_executions` rows with `status = 'running'` (`backend_host/src/lib/utils/host_utils.py:463`, `get_devices_with_running_deployments()`), and publishes the result as `has_running_deployment` on every ping. A row that never flipped out of `running` — the downstream result of BUG-0759, where the run died before it could write its verdict — keeps that device marked busy for ever. The Run page reads the flag (`frontend/src/pages/RunTests.tsx:430`) and padlocks the target, so new browser runs queue behind a run that does not exist. The live-lock reaper next to it (`_check_stale_locks_for_host`) already asks the host `is_busy` and releases stale **locks**, but nothing ever closed the **row** — so the flag stayed true.

**(2) The Device page polled a log that does not exist, for ever.** `frontend/src/hooks/rec/useRunningLog.ts` fetches `running.log` every two seconds while `device.has_running_deployment` is true (`useRunningScriptName.ts:8`, `RecHostStreamModal.tsx:250`). A 404 was treated as "the run has not written its log yet, keep polling", and `MAX_RUNNING_LOG_FAILURES` counted only non-404 answers — so with the stuck flag in place the page asked for a file that was never going to exist, every two seconds, for ever.

The 404 is not wrong in itself: a testcase writes its `running.log` after its first block starts, so a 404 right after a run starts is normal. It is only wrong when it never stops.

## Fix

**The row is closed (server side).** `backend_server/src/routes/server_system_routes.py` — new `_reap_stale_running_deployments_for_host()`, called from the probe that already runs once per minute per host. It looks for `deployment_executions` rows of this host in `running`, and for each one older than two hours it asks the host `GET /host/system/device/<id>/is_busy` — the host's own answer about the jobs it is actually running. When the host says it is not running anything on that device, the row is closed (`status: failed`, `success: false`, and an `error_message` that says what happened). The host then stops reporting the device as busy, the Run page un-padlocks the target, and the Device page stops polling.

Guards, because a real run must never be closed:
- the host must answer (a host that does not answer leaves the row alone);
- the host must say the device is **idle** (a busy device leaves the row alone);
- the row must be more than two hours old (`_STALE_DEPLOYMENT_EXECUTION_GRACE_SECONDS`), which covers "the row says running, the script has not started yet";
- the host is asked once per device, not once per row.

**The poll gives up (frontend side).** `frontend/src/hooks/rec/useRunningLog.ts` — a 404 now counts, but against its own budget: `MAX_RUNNING_LOG_MISSES = 15` misses (thirty seconds at the two-second poll) end the poll. A log that does arrive in that window is still read; a log that never arrives is not asked for for ever. A 200 resets both counters, so a run that is really going keeps its log.

**Hardening after an independent review (2026-10-22).**
- The close is `UPDATE ... WHERE id = ? AND status = 'running'`, so a run that finished between the select and the update is never overwritten.
- `GET /host/system/device/<id>/is_busy` answers busy when any of its sub-checks raises (`check_errors` lists them); the server treats an answer without a boolean `busy` as busy. Only a clear "idle" closes a row.
- A DB campaign runs each step as its own script subprocess, so between steps no process exists. `CampaignExecutor.execute_campaign` now registers the campaign in an in-process registry (`get_in_flight_campaigns()`, cleared in a `finally`) and `is_busy` reports it, so an overnight campaign older than two hours is not reaped while it runs.
- The in-flight registry is in memory only: rows orphaned by a host or scheduler restart are closed at scheduler start by `_sync_from_db` (`deployment_scheduler.py`:425-455).
- Side effect: `busy` is now also true when a sub-check raises, so stale device locks (`lock_utils.py`:905 and the stale-lock probe in `server_system_routes.py`) are kept until the check works again.
- No `team_id` filter: `deployment_executions` has no such column (only `deployments` has one) and the reaper is host-keyed maintenance with no request or team context.

## Verification

Regression tests:

- `tests/frontend/useRunningLog.test.tsx` — "keeps polling while the log has not been written yet" (a 404 does not stop the poll straight away), "stops asking for a log that never arrives" (the poll ends after fifteen misses and stays ended), "reads the log when the host has one". With the source reverted, 1 of the 3 fails; with the fix all 3 pass.
- `tests/backend_server/test_stale_deployment_execution_reaper.py` — 5 tests: a stuck row on an idle device is closed; a row on a device the host is working on is left alone; a fresh row is left alone; a row is kept when the host does not answer; the host is asked once per device. With the source reverted all 5 fail; with the fix all 5 pass.

`tsc --noEmit` is clean and the pre-push ruff gate (`E9,F63,F7,F82`) passes on the changed Python file.

