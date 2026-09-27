# BUG-0170 — Atlas router offers screen/device tools without the tools that feed them, so web chats fail on guessed calls

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0170                                                     |
| Reported  | 2026-09-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_server agent router / MCP tool definitions           |
| Fixed in  | Unreleased (the cut sets the build — never copy VERSION.txt)  |
| Commit    | b4b81aa22                                                    |

---

## Symptom

Prompt on `host-clone-1` / `youtube-web`: *Open YouTube in the browser, search for "Raspberry Pi"
and tell me the title of the first result.* (session `d70b2d10`, 2026-09-27 18:28). The answer
was right, but the chat showed three red tool failures first:

1. `analyze_screen_for_action(elements=[], intent="search box")` →
   `No elements provided. Call dump_ui_elements first.`
2. `execute_device_action(command="dump_ui_elements")` → `Unknown command: dump_ui_elements`
3. `execute_device_action(command="type_text", text="Raspberry Pi")` → `Unknown command: type_text`

It then put the query in the URL (`navigate` to `/results?search_query=…`) and read the page.

## Root cause

In router mode Atlas gets at most 12 tools, picked per message by keyword score
(`_select_router_tools_for_message` in `backend_server/src/agent/core/manager.py`). This prompt
scored `analyze_screen_for_action` and `execute_device_action` but neither `dump_ui_elements`
(the only source of `elements`) nor `list_actions` (the only source of valid command names).

- Without `dump_ui_elements` the model could only send `elements=[]`, or try the tool name as a
  device command.
- Without `list_actions` it relied on the `execute_device_action` description. That listed only
  `click_element`, `click_element_by_id` and `navigate` for web. Playwright has no
  `click_element_by_id`, and its text command is `input_text` with a `selector`, so the model
  guessed `type_text`.

This is not a regression. The keyword router dates from 2026-06-24 and the description from the
initial snapshot.

## Fix

- `manager.py`: `_ATLAS_ROUTER_TOOL_PREREQUISITES` maps `analyze_screen_for_action` /
  `analyze_screen_for_verification` to `dump_ui_elements`, and `execute_device_action` to
  `list_actions`. Selection keeps these next to their dependent, just as `read_doc` and
  `search_docs` are kept, and still stays within 12 tools.
- `backend_server/src/mcp/tool_definitions/action_definitions.py`: the web section documents
  `input_text` (`selector` + `text`), `press_key` and `scroll`. It drops `click_element_by_id`,
  names `type_text` as absent, and says to call `list_actions` rather than guess.

## Verification

- `tests/backend_server/test_agent_minimax_quirks.py::test_router_tools_include_prerequisites`
  fails before the fix and passes after it.
- Re-run the same prompt on prod against `host-clone-1` / `youtube-web`: the tool list logged
  as `[AGENT] Tool names:` includes `dump_ui_elements` and `list_actions`, and there are no
  `Unknown command` / `No elements provided` failures.
