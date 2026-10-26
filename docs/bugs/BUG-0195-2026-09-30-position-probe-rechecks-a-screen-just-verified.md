# BUG-0195 — Before every hop a navigation re-checked where it was, and a look-alike screen skipped the step under test

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                          |
|-----------|------------------------------------------------------------------------------------------------|
| ID        | BUG-0195                                                                                       |
| Reported  | 2026-09-30                                                                                     |
| Status    | Fixed (pending deploy)                                                                         |
| Severity  | High (a testcase could pass without running the action it tests; every multi-step web testcase spent about half its run waiting) |
| Area      | `backend_host/src/services/navigation/navigation_executor.py`, `backend_host/src/services/testcase/testcase_executor.py`, `backend_host/src/routes/host_actions_routes.py` |
| Fixed in  | build 90145 |
| Commit    | `8107abcb0`                                                                                    |

---

## Symptom

Two things, one cause, on web testcases built as a chain of navigation steps (the public TodoMVC
demo: add two todos, toggle all, toggle all back...).

1. **Time.** Before every navigation step after the first, the run waited 5 to 10 seconds with
   nothing happening on screen. Over 16 runs of one acceptance suite the wait happened 46 times
   and took **347 s of 597 s** of test time.
2. **A false pass.** "Toggle all back to active" goes `with-two-todos` → `all-completed` →
   `with-two-todos`. Its last step reported success in 32-41 ms without clicking anything: no row
   for the `all-completed → with-two-todos` edge, the toggle-all click under test never ran, and
   the testcase passed.

## Root cause

Before a hop whose target is one edge away, `NavigationExecutor.execute_navigation` runs a
position-tracking check (added to catch a tracked position that disagrees with the screen): it
verifies the **target** node and, if that passes, assumes the tracked position was wrong, corrects
it and skips the hop.

- The check ran no matter how the device got to its current position — including when the
  previous hop had verified that position a few milliseconds earlier (measured: 23 ms). An earlier
  change already skipped it for a position the frontend supplies; the same skip was never written
  for a position the previous hop just verified.
- The target is not showing yet, so every leg of its verifications waited out the 5 s probe cap
  ([BUG-0194](BUG-0194-2026-09-29-web-testcase-spends-half-its-run-waiting.md)); web legs run one
  after the other and 'all' mode has no early exit.
- `with-two-todos` is verified only by the text `Walk dog`, which the `all-completed` screen shows
  too. The target check "passed" on the wrong screen, and the hop was skipped.
- When the target check failed, the code logged "position tracking is correct, proceeding" and
  took the edge — without ever having checked the current node.
- `last_verified_timestamp` was set at the end of every navigation, even when the destination had
  no verifications or its check had been skipped, so it could not have been used to decide.

## Fix

`8107abcb0`:

1. **Trust a position that was just verified.** The one-step check is skipped while the current
   node's own verifications passed less than `VPT_POSITION_TRUST_SECONDS` ago (host `.env`, default
   10 s, `0` = always check). The skip is logged as `⏱ nav.probe_skipped_recently_verified`.
2. **Only a real verification counts.** A position is marked verified (`last_verified_node_id` +
   `last_verified_timestamp`) only when its verifications ran and passed: the hop that reached it,
   or one of the position checks. Not a destination without verifications, a hop whose check was
   skipped (`verification_mode` end / auto), an action node, a conditional sibling landing, or a
   position set by `update_current_position`; `clear_current_position` drops the mark.
3. **Anything that sends commands ends the trust.** A testcase action block, a standard block that
   can reach the device or the app (`custom_code`, `api_call`, any block not known to be inert;
   `sleep`, `evaluate_condition`, `get_current_time` and `common_operation` keep it), and ad-hoc
   `/host/action/executeBatch` calls (MCP `execute_device_action`, the remote panel) forget the
   mark, so the next one-step hop is checked again.
4. **Where the check still runs, current node first.** Current node showing → take the edge (the
   cheap, expected answer). Not showing → check the target: showing → correct the position and
   skip the hop, as before. Neither showing → the tracked position is cleared and the no-position
   flow re-locates (home, else entry) instead of taking the edge from a screen the device is not
   on. A current node without verifications cannot be disproved and keeps the old behaviour.

The false pass cannot happen through the skip (no check runs) and, where the check runs, it
cannot happen while the current node's own verifications match the screen. A target that shares
all its verifications with the current node is still ambiguous for any check; the tree should
give such nodes a distinguishing verification.

## Verification

Same lab web host, same build before and after except these files; `scripts/debug/time_one_testcase.sh`
through MCP. "Probes" is the time spent in position checks; "hops" the edge rows in
`execution_results`.

| Testcase | Run | Script time | MCP caller waited | Probes | Hops |
|---|---|---|---|---|---|
| delete first of three todos (5 steps) | before ×2 | 46.0 / 44.0 s | 47.0 / 45.1 s | 25.2 / 25.2 s (4 checks) | 5 / 5 |
| | after ×3 | 20.2 / 20.4 / 24.1 s | 23.0 / 22.9 / 26.4 s | 0 (4 skipped) | 5 / 5 / 5 |
| toggle all back to active (5 steps) | before ×2 | 40.9 / 41.0 s | 43.2 / 43.1 s | 25.1 / 25.1 s (4 checks) | **4 / 4** |
| | after ×3 | 19.2 / 17.7 / 22.2 s | 21.0 / 18.9 / 25.0 s | 0 (4 skipped) | **5 / 5 / 5** |

All runs PASS. Before, "toggle all back" ran 4 hops: its last step was a 32 ms target check.
After, the `all-completed → with-two-todos` edge runs every time and the final frame shows both
todos active again ("2 items left"), so the pass is now earned. The first run after a service
restart is included (run 1).

Where the check still runs, it now costs almost nothing: with `VPT_POSITION_TRUST_SECONDS=0` (no
skip) the current-node check answered in 46-141 ms per hop, 0.3-0.4 s per testcase instead of
25 s, both testcases passed in 20.8 / 18.8 s, and "toggle all back" ran its 5 hops.

Unit tests: `tests/backend_host/test_trust_just_verified_position.py` (skip fresh / stale / other
node / env window, what marks a position, action and standard blocks, current-first, neither
showing, current without verifications); updated `test_position_probe_timeout.py` and
`test_testcase_step_timing.py` for the current-first order.
