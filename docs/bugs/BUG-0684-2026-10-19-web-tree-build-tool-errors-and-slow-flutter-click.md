# BUG-0684 — Building a web tree wasted a turn on every tool error and 15 s on every Flutter click

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0684                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host web controller / MCP tools / agent tool bridge |
| Fixed in  | build 90145 |
| Commit    | `8e7e681c5`                                                  |

---

## Symptom

TASK-135 phase 2 classified every wasted tool call of the five Sonnet `build-tree-web` runs (`scripts/bench_tree_build.py waste --series sonnet`):
59 wasted calls, about 100 s per run. Besides the waste, a `click_element(text)` on the Flutter web app took about 18 s, and so did every edge
that used it (`navigate_to_node` ~18 s per step), about a third of each run's wall time.

| Error the agent got | Calls | Runs |
|---|---|---|
| `click_element: element_id parameter is required` (it passed `xpath`, which the tool description offers) | 7 | 5/5 |
| `Unknown command: click_element_by_id` | 5 | 5/5 |
| `update_edge`: `null value in column "source_node_id"` (edge given with `source`/`target`, or without endpoints) | 4 | 4/5 |
| `execute_javascript`: `SyntaxError: Illegal return statement` | 1 | 1/5 |
| `dump_ui_elements`: `host_name required` | 1 | 1/5 |

## Root cause

- `PlaywrightWebController.click_element` tried five native selectors with `page.click(sel, timeout=3000)` each before its DOM-dump fallback.
  On a Flutter page none of them match (the labels are `aria-label`s on `flt-semantics`), so every click waited out 15 s first.
- `execute_command('click_element')` read `element_id`, `selector` or `text`, never `xpath`; a bare id (`kc-login`) was searched as text.
- `page.evaluate` rejects a top-level `return`.
- `TreeTools.update_edge` copied `source_node_id`/`target_node_id` straight from the edge it was given.
- The agent tool bridge never fills `host_name`/`device_id`; the model dropped them on one call.

## Fix

- `backend_host/src/controllers/web/playwright.py`: native selectors are skipped when `locator.count()` is 0 (no wait); `[id="<term>"]` is tried;
  `xpath` is accepted (`xpath=` prefix); a top-level `return` runs as a function body; an unknown command says what to use instead.
- `backend_server/src/mcp/tools/tree_tools.py`: `update_edge` reads `source`/`target` too, and keeps the stored endpoints when none is given.
- `backend_server/src/agent/core/tool_bridge.py`: device tools called without `host_name` get the chat's own host and device.
- The `build-tree-web` skill was rewritten from the same analysis (command catalogue, no read-backs, one dump per screen).

## Verification

Unit tests: `tests/backend_host/test_web_click_and_js.py`, `tests/backend_server/test_mcp_tree_tools.py` (update_edge cases),
`tests/backend_server/test_tool_bridge_device_context.py`. Live, measured 2026-10-19: a `click_element` by label on the Flutter menu
executes in 2.0-3.3 s on host-clone-2 after the deploy (4.3 s and 3.0 s with a 1 s wait), against 10-11.6 s on host-clone-1 before it
(12.1-13.6 s with a 3 s wait), same app and labels.
