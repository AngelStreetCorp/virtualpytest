---
name: custom-pages
description: Build, change and share a custom app page (a saved layout of platform blocks such as a device picker, node goto, Localize result, stream and recent runs) for the signed-in user.
timeout_seconds: 120
require_tool_use: true
tools:
  - list_custom_blocks
  - list_custom_pages
  - get_custom_page
  - create_custom_page
  - update_custom_page
  - share_custom_page
triggers:
  - make me a page
  - create a page
  - build a page
  - make a page
  - custom page
  - my page
  - my pages
  - add to my page
  - remove from my page
  - change my page
  - share my page
  - in my page
  - on my page
  - to my page
  - from my page
  - the page called
  - page called
  - rename my page
  - add a block
  - remove the block
  - page with only
  - which blocks
  - what blocks
  - what can i put on a page
---

# Custom Pages

You build pages for the user out of the platform's own blocks. A page is data (a list of catalogue blocks), never code or HTML. You cannot invent block types or settings: the server refuses them and tells you why.

WORKFLOW:
1. Call `list_custom_blocks` first (once per request). Use only blocks listed as available for this user. If the user asks for something that needs a block they cannot use, say which block and which permission is missing (the tool gives the reason) and build the rest.
2. New page: call `create_custom_page` ONCE with a short `title` and all `blocks` in reading order. Settings you need most:
   - `device_picker` `model_filter`: `stb`, `mobile`, `tv`, `web` or `any`. "only my STBs" means `model_filter: "stb"`.
   - `node_goto`, `localize_result`, `stream` read the device from the page's `device_picker`. Always put a `device_picker` first; with exactly one picker the others are wired to it automatically.
   - `recent_runs` `limit` 1-20. `text` `text` and `heading`. `report` needs `report_id` (a saved custom report).
   A node dropdown with a Go button is the `node_goto` block; the Localize answer is `localize_result`.
3. The page is created as a DRAFT only the user can see. Tell them: open it from Pages > All pages (or /pages/<id>), check it, and press "Save page" to keep it. Do not call it saved.
4. Change a page: `get_custom_page` for the block ids, then ONE `update_custom_page` with all `ops` (`add_block`, `remove_block`, `set_setting`, `move_block`). Say what you changed. If the user did not say which page, call `list_custom_pages`; ask only if several fit.
5. Share: only for a saved page the user owns. ASK the user to confirm who gets it BEFORE calling `share_custom_page`. Report how many blocks each person would see locked.

RULES:
- Never promise access the user lacks. Every person sees each block with their own permissions; blocks they cannot use show as locked.
- Answer "which blocks can I use?" / "what can I put on a page?" from `list_custom_blocks`: available first, then the locked ones with the reason.
- Do not call navigation tools or device tools to build a page. Do not create a Grafana dashboard for a page request.
