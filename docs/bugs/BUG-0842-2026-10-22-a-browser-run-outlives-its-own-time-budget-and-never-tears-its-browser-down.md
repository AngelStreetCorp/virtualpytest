# BUG-0842 — A browser script run can hang for ever: it outlives its own time budget and never tears its browser down

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0842                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High (one browser per hour is never released; the host fills up and the run never reports a result) |
| Area      | backend_host / testing                                       |
| Fixed in  | build 90145 |
| Commit    | `7f8c54460` (fix/e66-browser-run-budget-teardown) · `6645f45b0` + `81dcc5177` (fix/e66b-driver-reap-honest-report) |

---

## Symptom

A scheduled `game_tetris.py` run on `host-clone-2` starts, launches its Chrome, plays for a couple
of minutes, then **goes silent and never finishes**. It is still alive long past its own budget,
and the browser it launched stays on its port for ever.

```
$ ps -o pid,stat,etime,time,rss,cmd -p <pid>
  PID STAT     ELAPSED   TIME  RSS  CMD
373317 Ssl        20:16  00:00:02 288708  python .../game_tetris.py --max_pieces 300 --max_duration 900 --device host
```

`--max_duration 900` is a 15-minute hard stop and is documented as such. The run was measured at
**20 minutes and still running**, holding a Chromium on port 9300 and a Playwright driver as
children. The hourly schedule then starts the next one, which does the same thing: one browser per
hour, none of them released. That is the accumulation BUG-0760 recorded on this host.

The run never reaches teardown, so the end-of-run browser close never happens — there is no
`Closing web browser after test execution...` line in the journal for any Tetris run, while the
`youtube_video_check` runs on the same host print it every time.

**What the host actually carried, measured 2026-10-24 ~13:50Z on `host-clone-2`.** The "the host
fills up" half of the symptom is **mitigated**: the reclaim pass added for BUG-0760 takes the
browsers back, so the disk sat at **32 % used, 20 GB free** and `ss -ltnp` showed **no** Chromium
listener left. What still leaked was the **Playwright driver**, because it holds no port and every
port-based count on the host was blind to it:

```
$ ps -o pid,ppid,etime,rss,cmd -p <driver pid>
  PID    PPID     ELAPSED   RSS  CMD
1287991 1276066  04:49:43   74M  node .../playwright/driver/package/cli.js run-driver
```

Its parent was the long-lived host service (`/opt/virtualpytest/venv/bin/python app.py`), so it
outlived the run that started it and nothing ever reaped it: a leaked ~74 MB driver (plus its
crashpad pair) per hung run, for ever. The same measurement showed a healthy hourly run at
`ELAPSED 12:06` against `--max_duration 900` with its own driver — **a run inside its budget is
healthy and must never be torn down**.

So the leak that remains is **the driver and the run that never reports**: the browser is
reclaimed, the driver is not, and the run itself stays alive past its budget instead of ending
with a verdict.

## Evidence

The last thing a hung run prints, on every occurrence seen:

```
[PLAYWRIGHT]: Page screenshot timed out after 20s
[device_utils] No run page screenshot (the run has no live page to photograph) — falling back to the screen capture
[device_utils] No device shot for this browser run — this host's screen is shared between runs …
⏱ action.after_action_screenshot 20000 ms cmd=press_key
```

…and then nothing, for the rest of the process's life. Its threads at that point:

| thread | wchan | reading |
|---|---|---|
| main | `do_epoll_wait` | idle in an event loop, waiting on something that never comes |
| controller loop | `do_epoll_wait` | idle, not executing the pending work |
| 4 others | `futex_wait_queue` | waiting on a lock/condition |
| 1 | `do_wait` | the asyncio child watcher, reaping the node driver |

So the main thread is waiting on a future the controller loop is never going to satisfy.

## Root cause

`_submit_to_controller_loop()` returns a `concurrent.futures.Future` from
`asyncio.run_coroutine_threadsafe`. Two call sites then **block on it with no timeout**:

- `playwright.py:78` — the `@ensure_controller_loop` decorator, when called from a plain thread;
- `playwright.py:2368` — `execute_command`, when there is no running loop.

```python
fut = self._submit_to_controller_loop(func(self, *args, **kwargs))
if current_loop is None:
    return fut.result()          # no timeout: blocks for ever if the coroutine never finishes
```

If the submitted coroutine raises into a state where it never completes — or the controller loop
dies or is wedged — the caller blocks indefinitely. Nothing in the run path enforces
`--max_duration` from outside that loop, so the budget is never checked again and the run never
returns.

The three facts measured on 2026-10-24 line up with this shape: a live process past its budget,
idle event loops, and a blocked waiter. What the host then carried is the driver's orphan: a
driver waits for its parent, and the run that started it is exactly the process that never
returned.

## Fix

`fix/e66-browser-run-budget-teardown` (`7f8c54460`):

1. **Bounded wait.** Both `fut.result()` sites on the controller-loop path now wait with a bound
   (`CONTROLLER_LOOP_RESULT_TIMEOUT_SECONDS`, 120 s, `VPT_CONTROLLER_LOOP_TIMEOUT`), and the
   failure says the loop did not answer. `execute_command` reports it as a failed command result
   (`{'success': False, 'error': ...}`), because the action path reads a dict, not an exception.
   The async path waits with `asyncio.wait`, which leaves the pending work alone on timeout —
   `asyncio.wait_for` waits for a cancellation a running coroutine never grants, which is the
   hang it was meant to remove.
2. **A watchdog outside the action loop.** The executor stops the run at **the run's own budget**:
   `--max_duration` is read out of the run's parameters and is the ceiling (plus the margin the
   script needs to write its result) when the caller declared none. The platform's own ceiling
   still bounds it, so a script cannot raise its own limit.
3. **Teardown on kill.** A run stopped by the watchdog never reached its own teardown, so the host
   does it: the reclaim pass closes the browser on the run's port and the driver that held it.
4. **Defence in depth.** The reclaim pass now sees an orphaned **driver**: it holds the browser it
   drives through the CDP connection it opened to that browser's debug port, so a driver whose
   connection is gone is holding nothing and belongs to no live run. A driver that still holds a
   browser whose port the registry gives to a live owner is never touched — the port scan's rule,
   asked of the driver instead of the port. Individual pids only, never a process group.

A run that ends reports a result: a timeout with a reason (`timed_out`, `timeout_reason`), never a
hang and never a silent success. A healthy run keeps its old verdict, and a run inside its budget
is never killed.

## Follow-up finding: the reaper reported a reclaim it never performed

The fix above was deployed and **worked**: the reclaim pass found a real orphaned driver on
`host-clone-2` through the real scheduler job and named it. The same live run exposed a defect in
the **reporting**:

```
[leaked_browser_reaper] driver 1442790: its browser is gone, took down 0 process(es)
[reap_leaked_browsers] reclaimed orphaned Playwright driver(s): [1442790]
```

**The driver was still alive** — a minute later and minutes later. "took down 0 process(es)" was
read as a success, and the driver was written into the list of reclaimed drivers.

Two faults fed it, and the second one is the one that mattered:

1. the probe that produced it ran under a different user than the one the reaper runs as, so
   `os.kill` on that driver raised **PermissionError**: a driver the reaper is not allowed to
   signal cannot be reaped, and **saying so** is the whole point of a reaper;
2. **the code hid it.** `PermissionError` is an `OSError`, and the signal loop caught it as one
   and dropped the reason, so `signalled` came back empty with the cause thrown away. Then
   `reap_orphaned_drivers` put the driver into `reaped` because it had **found** it, not because it
   had **taken it down** — and the early return ("this process or its parent") landed in `reaped`
   too. A driver that was never touched was reported as reclaimed.

That is BUG-0089's shape again — a run that never happened recorded as successful — inside the
very fix for a bug about runs that never report.

## What changed (`6645f45b0`)

1. **`reap_browser_tree` does not swallow the reason.** It tells the two apart: a target that is
   already gone (`ProcessLookupError` / ESRCH) is benign — the goal is met — and a target that
   could not be signalled (`PermissionError` / EPERM) is a real failure the operator must see.
   The outcome carries `signalled`, `killed`, `gone` and `failed` (each failure with its cause);
   `pid`, `signalled` and `killed` stay as they were, because the callers read them.
2. **A driver lands in `reaped` only if it really was** — signalled, or already gone. Anything
   else lands in `skipped` **with the reason**: permission denied, or the early-return skip.
3. **The two log lines tell the truth.** "reclaimed orphaned Playwright driver(s)" names only the
   drivers that were really taken down, a driver that could not be signalled is reported as **not
   reaped** with its reason, and "took down 0 process(es)" is never printed as if it were a
   success.

The browser half of the same module had the same lie and gets the same verdict.

The safety rules are untouched: a driver holding a browser a live run owns is never a candidate,
individual positive pids only, never a process group, and the reaper's own process and its parent
are never signalled. **What the reaper may kill did not change** — no escalation, no sudo, no
wider net. This was about reporting, not about killing more.

## Verification

- a Tetris run that is stopped by its watchdog leaves **no** listener on its port;
- the run reports a result (a timeout, not a hang) and the report says why;
- a wedged controller loop produces a bounded error rather than a process that lives for ever;
- measured over N scheduled runs on `host-clone-2`, no run outlives `--max_duration` by more than
  the teardown allowance.

**The budget fix is deployed** (build `main-2026.10.24-89933`) and the live run proved the reclaim
pass works: it found a real orphaned driver on `host-clone-2` through the real scheduler job and
named it. The same run exposed the reporting defect above; that follow-up is on the branch, not
deployed yet.

Checked on the branch:

- `tests/backend_host/test_playwright_controller_loop_timeout.py` — a controller loop that never
  answers produces a bounded error; a loop that answers in time is untouched; `execute_command`
  reports the failure as a command result;
- `tests/shared/test_browser_run_budget_watchdog.py` — the run's own `--max_duration` is the
  ceiling; a declared budget still wins; a run over budget is stopped **and** its browser is torn
  down; the result reports a timeout with a reason; a healthy run keeps its verdict;
- `tests/backend_host/test_playwright_driver_reaper.py` — an orphaned driver is reaped, the driver
  of a live run is not, a driver that just started is not mistaken for an orphan, and the reaper
  signals individual pids only;
- `tests/backend_host/test_driver_reap_honest_report.py` — the six reporting tests of the
  follow-up: a refused signal is reported with its cause, a driver nobody could signal is skipped
  with the reason and never reclaimed, the "reclaimed" line names only the drivers really taken
  down, the browser half does not report a refused signal as a reclaim, a driver that is already
  gone is reported as gone and not as a failure, and the reaper never reports its own process as
  reclaimed. **All six fail on the pre-fix code** (`409fc4db2920`), where the 26 E66 tests still
  pass: the control is the fix, not the test file.

The measurement over N scheduled runs on `host-clone-2` can only be made after the deploy.