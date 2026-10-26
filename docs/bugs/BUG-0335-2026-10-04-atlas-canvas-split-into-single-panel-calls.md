# BUG-0335 — Atlas rendered a canvas as three single-panel calls; the chat showed only the last

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                      |
|-----------|--------------------------------------------|
| ID        | BUG-0335                                   |
| Reported  | 2026-10-04                                 |
| Status    | Fixed (pending deploy)                     |
| Severity  | Medium — two of three requested charts were lost |
| Area      | frontend/src/pages/AgentChat.tsx, backend_server/src/mcp/tools/analytics_tools.py, backend_server/src/agent/core/manager.py |
| Fixed in  | build 90145 |
| Commit    | see branch task43-w10-canvas-merge         |

---

## Symptom

"Build a canvas with pass rate, duration trend, and failing cases" made Atlas call `render_analytics_artifact` three times (bar, line, table), each with one panel. The Analytics tab keeps only the latest artifact, so the user saw only the table.

## Root cause

The tool docstring said "Call it once per requested chart", contradicting the canvas `panels=[...]` form; the frontend replaced the artifact on every `show_content`.

## Fix

- Frontend: `analyticsMerge.ts` folds artifacts of the same agent turn (same user-message count) into one canvas; the same title+source replaces its panel; a new turn or conversation starts fresh.
- Prompt: docstring, router hint and the single-visualization `_shown` reply say a canvas / several charts is ONE call with `panels=[...]`.

## Verification

`tests/frontend/analyticsMerge.test.tsx`; `test_router_prompt_says_a_canvas_is_one_call_with_panels` and `test_render_tool_docstring_and_shown_reply_say_one_call_for_several_charts` in `tests/backend_server/test_agent_minimax_quirks.py`.
