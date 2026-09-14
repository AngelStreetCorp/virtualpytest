---
name: build-tree-web
description: Build navigation tree for web applications
platform: web
requires_device: true
timeout_seconds: 1800
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

Build navigation trees for web apps using DOM inspection.

STEP 0 — CONSULT THE AI UI KNOWLEDGE BASE FIRST (DB-backed):
1. Resolve the active domain via execute_javascript: `document.location.host`,
   then resolve_ai_userinterface(fingerprint_type='url_host', value=<host>).
2. If a ui_id is returned: get_ai_userinterface(ui_id) for the bundle.
   - Reuse verified flows instead of re-exploring.
   - Respect quirks (e.g. Flutter Web requires activate_semantic before
     flt-semantics interaction; pointer-event dispatch instead of
     Playwright's locator.click()).
3. If no row exists for this domain: explore first, then document only what you confirm.
4. Reference: docs/agent/AI_USERINTERFACE.md.

VERIFIED-ONLY RULE for the AI UI knowledge base:
- Schema-enforced: every ai_userinterface_* sub-row carries verified_against NOT NULL.
- Never write a row whose verified_against you didn't physically observe this session.
- Do not copy from older memory into the DB unless the same flow was rerun this session.

AFTER A SUCCESSFUL FLOW (self-improvement loop, write back to DB via tools):
- add_ai_userinterface_transition(ui_id, name, key_sequence, verified_against=<framework
  build or domain version if visible>, verified_at=today, actor)
- add_ai_userinterface_quirk(ui_id, description, verified_against, actor)
- If the domain had no parent row yet: create_ai_userinterface with category='web',
  domain=<host>. Schema CHECK requires domain IS NOT NULL for web.
- To correct a wrong row: supersede_ai_userinterface_row with reason. Never DELETE.

FLUTTER WEB SPECIFIC:
- Page renders into a single <canvas>; the readable tree lives under <flt-semantics>
  nodes that are inactive by default. Call activate_semantic before any flt-semantics
  interaction (re-call after every navigation and popup dismissal). See
  docs/agent/DEVICE_CONTROL.md for the activate_semantic -> dump_elements pattern.

WORKFLOW:
1. list_userinterfaces() - Find available interfaces
2. get_userinterface_complete(userinterface_id) - Get tree_id and existing nodes/edges
3. get_compatible_hosts(userinterface_name) - Get host_name and device_id
   (device locking is automatic: every action/navigation tool acquires and
   releases the lock itself — there is no take_control tool to call)
4. For each screen:
   - dump_ui_elements(platform='web') - Get current DOM
   - analyze_screen_for_action(elements, intent, platform='web') - Get best selector
   - create_node or update_node with verifications
   - save_node_screenshot(node_id, tree_id)
   - create_edge or update_edge with selectors from analyze_screen_for_action
   - execute_device_action to test the action works
   - navigate_to_node to move around
5. verify_node to test verifications work
   (no release_control needed — locks release automatically per action)

SELECTOR PRIORITY: #id > [data-testid] > .class > xpath

IMPORTANT:
- Use list_nodes/list_edges to see what already exists before creating
- Use analyze_screen_for_action to get reliable selectors (don't guess!)
- Use update_node/update_edge to fix broken edges instead of recreating
- Use verify_node to test verifications before moving on
