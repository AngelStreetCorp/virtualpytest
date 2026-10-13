# BUG-0194 — A web testcase spent more than half its run waiting on timers and on its own report

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                          |
|-----------|------------------------------------------------------------------------------------------------|
| ID        | BUG-0194                                                                                       |
| Reported  | 2026-09-29                                                                                     |
| Status    | Fixed (pending deploy)                                                                         |
| Severity  | Medium (every web testcase ran ~40 % slower than its steps need; a pipeline of 16 took minutes longer) |
| Area      | `backend_host/src/services/navigation/navigation_executor.py`, `backend_host/src/controllers/web/playwright.py`, `backend_host/src/lib/utils/playwright_utils.py`, `backend_host/src/services/testcase/testcase_executor.py`, `shared/src/lib/executors/script_executor.py` |
| Fixed in  | Unreleased                                                                                     |
| Commit    | `cebf3c363` `8495faa62` `4dad94e82` `0d25c22f0`                                                |

---

## Symptom

A five-step web testcase on the public TodoMVC demo (add two todos, complete one, delete it) took
**~104 s from the MCP `execute_testcase` call to its `Result: PASSED` reply**, for about 35 s of
actions. Timestamping every line of its execution log (`⏱ <phase> <ms> ms`, from
`feat/testcase-step-timing`) showed where the rest went, on two runs of the same build:

| Phase | Time |
|---|---|
| "Is the next screen already showing?" probes before hops 2-5 | 20 / 10 / 20 / 10 s = **60 s** |
| Browser start before the first page load | **10.4-12.0 s**, ~7 s of it fixed sleeps |
| Sleep after each typed field (`input_text`) | 3 s × 2 = **6 s** |
| Report tail the caller waited for after the verdict | **5-6 s** (up to ~25 s when the shared storage is slow) |

## Root cause

1. **Uncapped position probe.** Before a hop whose target is one edge away,
   `NavigationExecutor.execute_navigation` checks whether the app is *already* there (a
   position-tracking bug check). It called `verify_node` without the `probe_timeout_ms` cap the
   two other position probes pass, so every leg of the target's verifications waited out its full
   10 s default for a screen that was never there, and 'all' mode ran every leg. The
   stale-position (>30 s) and already-at-target probes had the same gap.
2. **Fixed sleeps around the browser start.** `connect_browser()` first tried to attach to a debug
   port nothing listened on (each try starts a Playwright driver, ~1.6 s, to be refused), then the
   launcher polled the port every 1 s and slept 2 s, `connect()` slept 2 s more and
   `connect_browser()` 2 s more.
3. **input_text post-fill sleep.** `execute_command` passed `params.timeout` (default 3000 ms) to
   `input_text` as a sleep after the fill, on top of the action's own `wait_time`. The fill takes
   ~30 ms and none of the stored web `input_text` actions sets `timeout`.
4. **The caller waited for the report.** The async testcase status became `completed` only after
   `finalize_execution_context` had returned: browser close, video extract, mosaic, ~20 screenshot
   uploads, log / DOM / video / mosaic / HTML / review uploads and the final database write.

## Fix

1. `cebf3c363` — the three probes pass `probe_timeout_ms=POSITION_PROBE_TIMEOUT_MS` (5 s). A showing
   screen answers on the first poll (<200 ms), so only a negative gets shorter. A wrong negative
   either takes the edge that was about to run anyway (one step away) or navigates from entry
   (stale / already-at-target), the trade the two other probes already make.
2. `8495faa62` — the first attach runs only when something listens on the debug port
   (`ChromeManager.port_listening`, a TCP connect); the launcher polls the port every 0.1 s and
   then waits until the endpoint lists a page target (`/json/list`), which `connect()` and
   `connect_browser()` wait on too instead of sleeping. The page wait gives up after 6 s, the old
   sleeps' total, and carries on as they did. WebKit keeps its fixed delays.
3. `4dad94e82` — the implicit post-fill settle is `INPUT_TEXT_SETTLE_MS` = 500 ms; an explicit
   `params.timeout` and the action's `wait_time` are still honoured.
4. `0d25c22f0` — `finalize_execution_context(defer_report=True)` stops after the browser close and
   the final screenshot, writes the verdict (`success`, `execution_time_ms`, `error_msg`,
   `completed_at`) to `script_results` and hands back the rest as `report_tail`; the async worker
   reports `completed` and runs the tail on a background thread, one at a time per device. The
   tail's inputs are frozen first (log text, a copy of the DOM captures, the UI dump file; the
   next run resets and overwrites them) and its prints bypass the next run's log capture
   (`detached_output`). When it ends, `script_results` has its report and log paths and the row
   enters the analysis queue (once). `VPT_TESTCASE_BACKGROUND_REPORT`: `pass` (default, passing
   runs only: a failed run's report is read right after the verdict), `all`, `off`.

## Verification

Same testcase, same lab web host, two runs each (`scripts/debug/time_one_testcase.sh`):

| | Before | After |
|---|---|---|
| Probes | 60.2 / 60.2 s | 30.2 / 30.2 s |
| Browser start | 10.4 / 12.0 s | 5.6 / 6.3 s |
| input_text sleeps | 6.0 / 6.0 s | 1.0 / 1.0 s |
| Status `completed` after | 103.0 / 102.3 s | 58.7 / 57.8 s |
| MCP caller waited | **104.3 / 104.8 s** | **62.0 / 58.7 s** |
| Report paths in `script_results` | with the verdict | 2-6 s after it |

Both PASS. A second testcase that types into two different fields (add, then edit a todo) went
from 69.2 s to 40.9 s. Started back to back so that its run overlapped the previous run's report
tail, its `execution.txt` held no line of the other run and both reports were complete.

Unit tests: `tests/backend_host/test_position_probe_timeout.py`,
`test_playwright_connect_decision.py`, `test_web_input_text_settle.py`,
`test_testcase_background_report.py`.

The remaining probe time (5 s per leg, 2 legs for an 'all' node) could go too: skipping the probe
when the previous hop verified the position less than 30 s ago brought the same testcase to 29 s.
It was not shipped with this fix — if the app is already at the target, the edge runs a second
time. It shipped later, with a 10 s window and the current node checked before the target:
[BUG-0195](BUG-0195-2026-09-30-position-probe-rechecks-a-screen-just-verified.md).
