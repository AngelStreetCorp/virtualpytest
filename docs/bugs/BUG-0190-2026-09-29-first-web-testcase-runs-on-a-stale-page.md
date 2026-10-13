# BUG-0190 — A web testcase started on whatever page an earlier command left open, and skipped the app's entry step

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                          |
|-----------|------------------------------------------------------------------------------------------------|
| ID        | BUG-0190                                                                                       |
| Reported  | 2026-09-29                                                                                     |
| Status    | In progress — fix on branch `fix/testcase-fresh-start`, not merged                             |
| Severity  | High (web testcases: false FAIL, and false PASS with 0 actions, whenever the browser was left open before the run) |
| Area      | `backend_host/src/services/navigation/navigation_executor.py`, `backend_host/src/services/testcase/testcase_executor.py` |
| Fixed in  | Unreleased                                                                                     |
| Commit    | `3f2877d33`                                                                                    |

---

## Symptom

A pipeline tests the public TodoMVC demo (`https://demo.playwright.dev/todomvc`) on a `host_vnc`
web host. Before running testcases it maps the app itself, driving the browser over REST
(`POST /host/web/executeCommand`, `POST /host/action/executeBatch`). The mapping ends with Chrome
still open on `todomvc/#/completed` — the "Completed" filter. Then it runs the testcases one
after the other with MCP `execute_testcase`.

The first testcase was "add the todo *Feed the cat* and check it appears in the list":

1. **Navigate to: home** — PASS in 0.1 s, **no actions**. There is no "Entry → home" hop in the
   report: VPT never opened the app's URL and never cleared its storage.
2. **Navigate to: with-cat-todo** — types *Feed the cat* into `.new-todo` and presses Enter. The
   todo *is* created (the footer says "1 item left"), but the page is still filtered on
   Completed, so a new, active todo is hidden. `waitForElementToAppear('Feed the cat')` gives up
   after 10 s → **FAIL**.

The second testcase of the same batch had the same shape and passed: its step 1 took 22 s and
shows the hop **Entry → home** — `navigate_to_url`, a script clearing localStorage,
sessionStorage and cookies, `navigate_to_url` again, then `todos` verified.

The same mechanism produced **false passes** earlier: runs recorded as PASSED with 0 actions,
because every check they made was satisfied by the stale screen.

## Root cause

Line numbers below are on `main` at `23828e62d` (before the fix).

### What VPT does when a testcase starts

1. **Position is set to "unknown".** `execute_testcase_from_graph` and its async twin (the one MCP
   `execute_testcase` reaches) set `nav_context['current_node_id'] = None` —
   `testcase_executor.py:422` and `:965`. The third entry point, `execute_testcase` by name
   (`:528`, used by campaigns through `POST /host/testcase/<id>/execute`), does not reset the
   position at all (`:667-670`): it inherits whatever the previous run left.
2. **The first navigation block runs.** `_execute_navigation_block` (`:1820`) calls
   `ExecutionOrchestrator.execute_navigation` (`:1892` / `:1903`), which calls
   `NavigationExecutor.execute_navigation` (`navigation_executor.py:916`).
3. **"Starting from entry"** is logged (`:1170`) — but that is only a log line. Nothing has moved
   yet, and the next block decides whether entry is ever used.
4. **Probe: am I already at the target?** With no position, VPT runs the target node's own
   verifications, capped at 5 s (`POSITION_PROBE_TIMEOUT_MS`, `:62`; the probe is `:1402-1412`).
   If they pass it logs `✅ Already at target` (`:1416`), records a step with `'actions': []` and
   `already_at_destination: True` (`:1434-1447`), and returns success with
   `already_at_target=True` (`:1456-1468`). **No path is computed, so the entry edge never
   runs.** That recorded step is the "PASS, 0 actions" in the report.
5. **Probe: am I at home?** If the target probe fails and the target is not home, VPT probes the
   `home` node the same way (`:1472-1512`). If that passes it sets the position to home and
   paths from there — which **also** skips the entry edge.
6. **Only when both probes fail** does pathfinding start at the entry node (`:1519`).

### Why "home" passes on the wrong page

The TodoMVC tree verifies `home` with `waitForElementToAppear('todos')` — the page header. Every
TodoMVC view shows it: `#/`, `#/active`, `#/completed`. A verification can only say the screen
*looks like* a node. It cannot say the app *state* behind it (the URL's filter, the todos in
localStorage) is what the entry edge would have produced. On this tree the entry edge is the one
step that resets that state, and the probe skipped it.

### Why only the first testcase of a batch

At the end of every testcase and script, `finalize_execution_context` closes the browser
(`shared/src/lib/executors/script_executor.py:2407` → `_close_web_browser_if_needed`, `:2328`),
unless `VPT_KEEP_BROWSER_OPEN=true`. So testcases 2..N start with no browser: the probe relaunches
Chrome on a blank page, `todos` is not found, ~5 s are wasted, and navigation starts from entry.

Only a testcase that follows *someone else's* use of the browser finds a live page — REST
`web/executeCommand` or `action/executeBatch`, MCP `execute_device_action`, a person at the
controls, or the KPI service (see [BUG-0179](BUG-0179-2026-09-28-goto-waits-300s-for-an-orphan-chromium.md)).
A verification attaches to that browser as it is, and the probe trusts the page.

The by-name (campaign) path has a sharper version of this: the previous testcase's position is
kept, and if it is less than 30 s old it is trusted without any check (`:1134-1167`), even though
finalize closed the browser in between.

### Where to look in logs

The navigation lines are printed *inside* the testcase's block, whose stdout is captured into that
step's logs (`_execute_block`, `testcase_executor.py:1555`). They are in the report's execution
logs, not in `journalctl` — the host journal for the failing run shows no navigation line at all.

## Fix

### What changed

Line numbers below are on the branch.

- `NavigationExecutor.execute_navigation(..., start_from_entry=False)` — `navigation_executor.py:939`.
  When `True`, and the call has no pre-computed `navigation_path` and is not a recovery, it first
  forgets the tracked position (node, label, tree, timestamps — before the stale-position check,
  so that check cannot spend a verification timeout either), logs
  `Testcase fresh start: navigating from entry (position probes skipped)` (`:1136`), skips both
  probes (`:1426`), and lets pathfinding start at the entry node.
- `ExecutionOrchestrator.execute_navigation` passes it through (`execution_orchestrator.py:32`).
- `TestCaseExecutor` arms it at testcase start in **all three** entry points —
  `context.start_from_entry_pending = self._starts_from_entry(device)`,
  `testcase_executor.py:450`, `:699`, `:997`. `_execute_navigation_block` hands it to the
  **first navigation only** and clears it (`:1926`). An **action block** that runs before the
  first navigation clears it too (`:1630`): the testcase is setting the device up itself, so its
  first navigation starts from wherever those actions leave it.
- `_starts_from_entry(device)` (`:133`) is `True` when the device has a web controller — the same
  devices whose browser VPT closes at the end of every run — and `VPT_KEEP_BROWSER_OPEN` is not set.

The rule in one sentence: **a web testcase that has not touched the device yet starts its first
navigation from the entry edge.**

### Options considered

| Option | Verdict |
|---|---|
| **(a)** Force the entry edge on a testcase's first navigation for every device type, through a one-shot flag on the device, with a new opt-out env var. | Mechanism kept, scope and plumbing changed. Android/TV would change (below). A device-level flag can leak into the next unrelated navigation when a testcase has no navigation block, so it needs a cleanup hook. The draft applied the flag *after* the stale-position check and missed the by-name entry point. |
| **(b)** Close the browser at testcase start, mirroring the end-of-run close. Web only. | Fixes this case, but every web testcase still pays two doomed probes (target, then home: up to 10 s) against a blank browser, and correctness rests on the relaunched browser opening blank. |
| **(c)** (a)'s mechanism, **web only**, as an explicit parameter set by the testcase executor. | **Chosen.** Nothing to leak (the pending state lives on the run's context), no new env var, no change for Android/TV. |

**Why web only.**

- Web already promises a fresh start: VPT closes the browser after every run. Forcing entry there
  only removes probes that cannot succeed on a fresh browser — never slower, usually 5-10 s faster.
- Android, TV and set-top boxes make no such promise: the app is left as it is between runs, and
  the probe is a deliberate time saver (the `POSITION_PROBE_TIMEOUT_MS` comment records 101 s of
  probing on a phone before the cap). Campaign chains on TV can rely on the app still being where
  the previous testcase left it. Forcing entry would relaunch the app for every testcase — and on
  a paired phone `launch_app` without `reset` puts the app back exactly as it was
  (`tests/backend_host/test_phone_launch_reset.py`), so the relaunch would not even guarantee a
  clean state.
- Extending it later is a one-line change to `_starts_from_entry`.

### Opt-out

Set `VPT_KEEP_BROWSER_OPEN=true` in the host's environment. That existing setting already means
"carry the browser from one run to the next", which is the one case where a run is meant to pick
up where the last one stopped — so with it, testcases probe first, as before. No new variable.

### What changes for users

- **Web** (device models `host_vnc`, `web`, `runner_host`): the first navigation of every testcase
  takes the entry edge. Reports show the "Entry → …" hop where they used to show a 0-action
  "Navigate to" step. The probe's time is gone; the entry edge's time is added only when the
  browser was left open (when VPT had closed it, entry ran anyway).
- A web testcase whose first target is **not reachable from the entry node** now fails with
  "No unified path found". It already failed that way whenever the browser had been closed; it
  only passed when the probe happened to find the device already there.
- A `host_vnc` device driving a **desktop** (pyautogui) tree counts as web under this rule: its
  entry edge runs at testcase start.
- Frontend **QuickTest** single-step runs on web also start from entry.
- **Android, TV, set-top box**: no change.

## Verification

**Unit tests** — `python -m pytest tests/backend_host/test_testcase_fresh_start.py -q`: 17 pass.
Against `main`, 16 fail; the one that passes there is the test reproducing the old behaviour
(a passing probe returns `already_at_target` with 0 actions).

**On a host after deploy:**

1. Leave the browser on a non-home page, e.g. `POST /host/web/executeCommand` with
   `navigate_to_url` → `https://demo.playwright.dev/todomvc/#/completed`.
2. Run a web testcase whose first block navigates to `home` (MCP `execute_testcase`).
3. **Report:** step 1 "Navigate to: home" has the sub-step **Entry → home** with its
   `navigate_to_url` and storage-clearing script, and 1 hop instead of 0 actions.
4. **Execution logs** (the report's logs, not `journalctl`):
   `Testcase fresh start: navigating from entry (position probes skipped)`, and no
   `No current position - checking if already at target`.
5. **Database:** `execution_results` rows for the run's `script_result_id` start with the tree's
   entry edge (in the trees that pipeline builds, `edge-entry-node-to-home`).
6. **Opt-out:** with `VPT_KEEP_BROWSER_OPEN=true` the log shows
   `No current position - checking if already at target` again.
