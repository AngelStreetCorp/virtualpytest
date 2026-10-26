# BUG-0356 — A passing exploration saved as a testcase kept one zap out of three and got invented checks

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0356                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed                                                        |
| Severity  | High - the saved test did not do what the exploration did, and failed on replay |
| Area      | `features/ai-test/backend_server/server_testprompt_routes.py` (`_trace_to_graph`, `to-graph`, explore trace) |
| Fixed in  | build 90145 |
| Commit    | `065b8ae9df`                                                 |

---

## Symptom

"Live: zap 3 times" (`stb_tv`) passed in Explore on stb3: `home → live → live_chup ×3`, with `verify_node(live)`
after each zap. **Save as testcase** proposed `home → live → live_chup` once, then
`press_key(CHANNEL_UP)`, `DetectZapping(key_release_timestamp=0)`, `waitForIconToAppear(play)`, twice. The replay of
that testcase failed on both boxes.

## Root cause

1. `_trace_to_graph` collapsed consecutive navigations to the same node. That is harmless for a screen, but
   navigating to an action node (`live_chup`) *is* the action: three zaps became one.
2. `verify_node` was not traced, so the checks the agent judged the criteria on were lost. `to-graph` then always
   asked the AI builder to add checks for the acceptance criteria, and it filled the gap with key presses and
   checks the box can't pass (DetectZapping without a key timestamp, a play icon `stb_tv` never shows).
3. The agent reports every tool call that returned as `success=True`, so a tool's own failure (`isError`, e.g.
   "❌ Node verification failed") would have been traced as a passed step.

## Fix

- Every traced step is kept, repeats included.
- `verify_node` is traced and becomes a verification block holding that screen's saved checks (`_node_checks`,
  from the whole tree incl. subtrees, keyed by label and id).
- When the trace carries a check, `to-graph` returns the trace graph directly: no LLM call. Only an exploration that
  checked nothing still goes to the AI builder.
- A tool result with `isError` is not traced.

Tests: `tests/backend_server/test_testprompt_trace_to_graph.py`.

## Verification

Deployed 2026-10-04 (server .103 + vpt-pi1). Prompt `c3b97222` on stb3: Explore passed, `to-graph` returned
`home, live, verify live, (live_chup, verify live) ×3` with no `text.plan` call in the server journal, saved as
testcase `b26bc274`. Run graph replayed it with 0 LLM calls and **passed** on stb3 (vpt-pi1) and on stb4 (vpt-pi3).
