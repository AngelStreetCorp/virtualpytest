# BUG-0172 — The agent could not read a web page: dump_ui_elements asked for a remote controller and the model never saw the elements or script results

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0172                                                     |
| Reported  | 2026-09-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_server MCP tools / backend_host Playwright controller |
| Fixed in  | Unreleased (the cut sets the build — never copy VERSION.txt)  |
| Commit    | 3431decfe                                                    |

---

## Symptom

This was found by re-running the BUG-0170 prompt (*Open YouTube in the browser, search for
"Raspberry Pi" and tell me the title of the first result*, `host-clone-1` / `youtube-web`,
session `3a3c98ee`). The first attempt took 450 s:

- `dump_ui_elements(platform="web")` → `UI dump failed: No remote controller found for device host`,
  followed by `analyze_screen_for_action(elements=[])` → `No elements provided`.
- `input_text` was sent without a `selector`, because the model had no elements to take one from.
- About 20 `execute_javascript` calls returned "completed", but none of them showed the value
  the script returned. The model kept rewriting the script, and finally got the title through
  `crawl_app`.

## Root cause

Three gaps between the agent tools and the web controller. None of them is a regression: each
path is unchanged since the initial snapshot.

1. `dump_ui_elements` (`backend_server/src/mcp/tools/verification_tools.py`) always called
   `/server/remote/dumpUi`, which asks the device for its **remote** controller. A `host_vnc`/web
   device has av, verification, web and desktop controllers, and its web verification controller
   *is* the Playwright web controller (`controller_manager.py` skips `verification:web`). Its DOM
   dump is Playwright's `dump_elements`, which the web terminal runs through
   `/server/web/executeCommand`. The tool received `platform="web"` and ignored it.
2. The agent forwards only the text blocks of a tool result to the model
   (`agent/core/manager.py`). `dump_ui_elements` put its elements in a side key and returned only
   "N elements (M clickable)" as text, on every platform.
3. `PlaywrightWebController.execute_javascript` returned the value under `result`, but the host
   action executor forwards only `output_data`, so the value never reached `execute_device_action`.

## Fix

- `dump_ui_elements` with `platform='web'` runs `dump_elements` through `/server/web/executeCommand`.
  It keeps visible elements only, as `{id, selector, tagName, textContent, name/type/placeholder/aria-label/title/role/href}`.
  Mobile/TV still use `/server/remote/dumpUi`.
- Both paths append the element list (compact JSON, capped at 15 000 chars) to the text the model reads.
- `execute_javascript` also returns `output_data: {'result': <value>}`, which
  `execute_device_action` already prints under "Output:".

## Verification

- `tests/backend_server/test_mcp_dump_ui_elements.py` fails before the fix and passes after it.
- Re-run the same prompt on prod: `dump_ui_elements` returns the YouTube DOM with
  `input[name="search_query"]`, and `execute_javascript` results show up as `Output: {"result": …}`.
