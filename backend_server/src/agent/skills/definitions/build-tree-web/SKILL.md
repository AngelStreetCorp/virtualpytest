---
name: build-tree-web
description: Build navigation tree for web applications
platform: web
requires_device: true
timeout_seconds: 1800
think_budget_seconds: 600
max_tool_calls: 150
tools:
  - list_userinterfaces
  - get_userinterface_complete
  - list_nodes
  - list_edges
  - preview_userinterface
  - navigate_to_node
  - get_device_info
  - get_compatible_hosts
  - dump_ui_elements
  - analyze_screen_for_action
  - analyze_screen_for_verification
  - capture_screenshot
  - create_node
  - update_node
  - delete_node
  - get_node
  - create_edge
  - update_edge
  - auto_layout_tree
  - delete_edge
  - get_edge
  - create_subtree
  - save_node_screenshot
  - execute_device_action
  - list_actions
  - list_verifications
  - verify_node
  # AI UI knowledge base (DB-backed; see docs/agent/AI_USERINTERFACE.md)
  - list_ai_userinterfaces
  - get_ai_userinterface
  - resolve_ai_userinterface
  - get_ai_userinterface_history
  - create_ai_userinterface
  - update_ai_userinterface
  - revert_ai_userinterface
  - add_ai_userinterface_screen
  - add_ai_userinterface_transition
  - add_ai_userinterface_quirk
  - add_ai_userinterface_known_hardware
  - add_ai_userinterface_fingerprint
  - supersede_ai_userinterface_row
triggers:
  - explore web
  - build web tree
  - map website
  - web navigation
  - automate web
---

# Build Tree Web

Build a navigation tree for a web app: one node per screen, one edge per link (forward + back action),
one verification per node that only that screen passes. Time goes into device actions (a click or a
navigate_to_node takes seconds), so every turn must move the tree forward. The rules below come from
measured runs (TASK-135): each one removes turns that were wasted before.

STEP 0 — THE APP'S PLAYBOOK FIRST (AI UI knowledge base, DB-backed):
1. resolve_ai_userinterface(fingerprint_type='url_host', value=<host of the app URL>).
2. If a ui_id comes back: get_ai_userinterface(ui_id). Its pack text (ui_pack_markdown) is this app's
   playbook: login, popups, menu labels, each screen's identity and the click targets that work.
   Follow it over the generic steps below; it was checked on the live app.
3. No row: explore, and write back only what you confirmed (VERIFIED-ONLY RULE below) unless the
   user said the knowledge base is read-only.

STEP 1 — WHERE THE TREE STANDS: get_userinterface_complete(userinterface_name). It gives the tree id,
every node and edge. Never recreate an existing node or edge: fix it with update_node / update_edge.
When the user lists failed edges, fix those before exploring new screens.

STEP 2 — FOR EACH SCREEN (one iteration):
1. Get there with one execute_device_action batch (click + activate_semantic for Flutter + optional
   execute_javascript 'location.href'), include_screenshot=true only when you need to see the page.
2. dump_ui_elements(platform='web') once per screen. Do not dump a screen you already dumped.
3. create_node(node_id, label, verifications=[...]) with the verification inline.
4. create_edge(source_node_id, target_node_id, action_sets=[forward, back]): action set ids
   '<src>_to_<dst>' and '<dst>_to_<src>', each with its actions.
5. Test it: navigate_to_node(target_node_label=<node>, include_screenshot=False), then
   verify_node, then save_node_screenshot. Going back to home with navigate_to_node tests the back action.
Create several nodes and edges in a row when you already know them (one dump of home shows the whole
menu); test them after. Do not read back what you just wrote (no get_node / get_edge after a create).

COMMANDS (web device; no need to call list_actions or list_verifications for these):
- click_element: params {element_id: '#id' | CSS | 'xpath=//...' | visible text or aria-label prefix,
  wait_time: ms}. A bare id like 'kc-login' works too. There is no click_element_by_id.
- input_text: {selector: '#username', text: '...'} (fill replaces what is in the field);
  press_key: {key: 'Enter'}; tap_x_y: {x, y}; navigate_to_url: {url}; activate_semantic: {}.
- execute_javascript: {script: 'location.href'} returns the value; a top-level `return` is fine.
- execute_pyautogui_* are desktop commands (action_type 'desktop'), for browser chrome such as a
  "save password?" bubble, never for the page.
- Verification, language-free FIRST: {command: 'waitForUrlToMatch', verification_type: 'web', params:
  {url_pattern: '/epg/initial', timeout: 10000}}. The path is matched with host, query and the app's
  language segment (/de/ /en/) ignored, `*` is a wildcard (`/watchtv/linearplayer/*`). A tree built
  on translated aria-labels breaks the day the app (or the test account) switches language, so a node's
  FIRST verification is its URL path. Read the path with execute_javascript 'location.pathname' on the
  screen; use the shortest path that only this screen has. Add a waitForElementToAppear on a label only
  as a second check, and only for a screen whose URL is shared with another one (a tab inside a page);
  for those prefer a structural/ id selector over translated words.
  Screens with no URL of their own (dialogs, filters, toggles): waitForElementToAppear on the aria-label
  is all there is; mark it in the doc as language-bound.
- Edge actions follow the same rule: `navigate_to_url` takes a path (`/settings` or `/{lang}/settings`)
  and opens it in the language the app shows now. Never write `/en/...` or a full URL with a language
  segment into a back action. click_element on a translated label is language-bound: prefer a URL
  navigation when the target is a page, or a selector that does not contain words (`a[href$="/epg/initial"]`).
- The entry edge (edge_id 'edge-entry-node-to-home') opens the app: update_edge(edge={edge_id,
  action_sets:[{id:'entry_to_home', actions:[navigate_to_url, activate_semantic]}]}) — source and
  target may be left out, the stored ones are kept.

FLUTTER WEB: the page is a <canvas>; the readable tree lives under <flt-semantics> nodes that are
inactive by default. Call activate_semantic before any dump or click, and again after every
navigation and popup. Labels are aria-labels such as 'TV Guide, Press Enter or Space to Select';
click_element matches their prefix ('TV Guide').

A BUSY DEVICE: "in use by ... (script_execution / deployment_execution / testcase_execution)" is
another job. Wait 30-60 s (one capture_screenshot or a planning turn) and retry the same call; never
force_unlock, it stops someone else's run.

VERIFIED-ONLY RULE for the AI UI knowledge base:
- Every ai_userinterface_* sub-row carries verified_against NOT NULL.
- Never write a row whose verified_against you did not observe this session.
- After a successful flow: add_ai_userinterface_transition / add_ai_userinterface_quirk; a domain
  without a parent row gets create_ai_userinterface(category='web', domain=<host>). Correct a wrong
  row with supersede_ai_userinterface_row; never delete.

BEFORE DONE (every round, once):
1. Every node except entry-node has a screenshot: get_userinterface_complete lists them; for one
   without, navigate_to_node to it, then save_node_screenshot. A player screen is no exception
   (geo-blocked or not, save what it shows).
2. auto_layout_tree(userinterface_name=<ui>): tool-made nodes all sit at (0, 0) and the editor shows
   them stacked; this places them top to bottom. Only positions change. update_node keeps a node's
   stored position and screenshot when you leave them out.

DONE: reply with the nodes and edges built, which were tested and passed, and what is left.

LANGUAGE: build so the tree passes in every UI language. Identify nodes by signals that do not translate (web: URL path; Android: resource_id / activity; STB: focus position / tab index, icon references) and act by keys, URLs or positions; a label only as a second check. Method: docs/agent/navigation/LANGUAGE_FREE_TREES.md.
