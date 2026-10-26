# BUG-0837 — A run that dies leaves a phantom failure on the dashboard for ever

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                    |
|-----------|------------------------------------------|
| ID        | BUG-0837                                 |
| Reported  | 2026-10-22                               |
| Status    | Fixed (pending deploy)                   |
| Severity  | High                                     |
| Area      | backend_host (deployment_scheduler)      |
| Fixed in  | build 90145 |
| Commit    | TBD                                      |

---

## Symptom

The dashboard reports runs that failed with **no error message and no duration**, and a single
browser game script fails every single time it runs while the host's own log shows it really
executing for minutes. Seen 2026-10-22: `game_tetris` had produced 110-row-or-more phantom failures
platform-wide; 28 of them in 24 h, 19 of those on one host. Every row claimed `0.02 ms`, while a
healthy run of the same script takes 112–140 s, and the host journal showed the script pressing
keys and running Playwright the whole time.

## Root cause

Two defects, one above the other.

**1. The recovery path can never fire for the case it exists for.**

`record_script_execution_start` opens every run with a placeholder row (`execution_time_ms IS NULL`,
`success = False`, `completed_at = started_at`, `error_msg = NULL`) and
`update_script_execution_result` closes it when the script finishes. When a run dies first, the host's
sweeper `_mark_stale_execution_failed` closes the deployment **and** its linked script result — but
only `if script_result_id` (`backend_host/src/services/deployment_scheduler.py`).

`deployment_executions.script_result_id` is not written at dispatch: it is regex-scraped out of the
**finished** run's stdout (`SCRIPT_RESULT_ID:<uuid>`). For exactly the runs the sweeper is built for,
that column is therefore always `NULL`, the guard is always false, and the placeholder is orphaned.
The deployment side got closed with a real reason; the `script_results` side kept `success = False`
and no reason, for ever.

Confirmed in the data: 8 of the reaped executions for this script had `script_result_id IS NULL`, and
10 of 22 orphaned rows had no deployment link at all.

**2. Nothing sweeps the rows no execution links.**

A run started outside the deployment path has no `deployment_executions` row, so no sweeper reaches
it even in principle. The queue watchdog only drains rows the scheduler itself queued, and the
server-side reconciler deliberately excludes `execution_time_ms IS NULL` rows as in-flight
(`backend_server/src/routes/server_deployment_routes.py:789`) — correct for a young row, wrong for
an old one. 110 such rows had accumulated since 2026-03-03, every one of them counted as a failure.

## Fix

`backend_host/src/services/deployment_scheduler.py`:

- **Recover the orphan instead of requiring the id.** New `_find_orphaned_script_result()` resolves the
  placeholder the same way the server-side reconciler does — same host, same bare script name,
  un-finalized, inside a window around the execution start — and returns the single closest match, so
  a dead execution closes its own row and nobody else's. `_mark_stale_execution_failed` falls back to
  it whenever the scraped id is absent. When the run *did* print an id, that id is still used and no
  lookup query is issued.
- **Sweep what no execution links.** New `_sweep_orphaned_script_results()` closes this host's
  `execution_time_ms IS NULL` rows older than `ORPHANED_SCRIPT_RESULT_GRACE_SECONDS` (7200 s), writing
  an `error_msg` that says the run never reported a verdict rather than leaving a blank failure. It is
  registered as an APScheduler interval job (`ORPHANED_SCRIPT_RESULT_SWEEP_SECONDS`, 300 s) beside the
  queue watchdog. The 2 h grace sits deliberately above the longest legitimate run (90 min for
  `game_clashofclans_llm`), so a slow but healthy run is never rewritten.
- Both call sites of `_mark_stale_execution_failed` now select `deployments.script_name` (and
  `scheduled_at`), which the recovery lookup needs.

## Verification

- `pytest tests/backend_host/ -k deployment_scheduler` — 20 passed. The 7 new tests in
  `tests/backend_host/test_deployment_scheduler_orphan_results.py` fail on the pre-fix source
  (5 failed, 2 passed), so they discriminate.
- `ruff check --select E9,F63,F7,F82` on the changed Python files — clean.
- On a host after deploy: a run killed mid-flight closes its `script_results` row with a reason
  instead of leaving a blank failure, and the phantom count for the script stops growing.
- Note: `tests/backend_host/test_monitor_profile_routes.py` fails to import on this machine
  (`pyarrow requires NumPy 2.0 or newer, found 1.26.4`). Pre-existing and unrelated; identical on
  `main`.