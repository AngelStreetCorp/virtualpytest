# BUG-0413 — MCP navigate_to_node, action and verification tools never returned the screenshot

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0413                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_server / MCP |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

`navigate_to_node(include_screenshot=true)` on the production MCP endpoint answered with the text result only: no image block. The model then told the user that the screenshot did not come back. The tool also defaulted to no screenshot, so a plain "open X" gave the model no way to see the result.

## Root cause

`include_screenshot` on the navigation, action and verification tools built its image through `mcp/utils/screenshot_capture.py`, which fetched the capture from the public base URL the MCP client had called. That is the same dead path BUG-0388 removed from `capture_screenshot`: the server VM cannot route `/host/<name>/stream/...` itself, so the fetch failed and the image was silently skipped.

## Fix

- `screenshot_capture.image_block_from_url()` fetches the bytes from the host that holds them (`_fetch_screenshot_bytes`, i.e. `call_host()`), the path `capture_screenshot` already uses; the old public-URL fetch and its helpers are removed. MIME type follows the bytes (PNG or JPEG).
- `navigate_to_node` and `verify_node`: `include_screenshot` now defaults to true (code, docstring and generated definition), so "open the search results page" or "verify the home node" returns the resulting screen.

## Verification

- `python3 -m pytest -m unit tests/backend_server/test_mcp_inline_screenshot.py`.
- After deploy: `navigate_to_node` over `/server/mcp` with and without `include_screenshot` returns an `image` content block.
