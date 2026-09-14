---
name: build-tree-stb
description: Build navigation tree for STB/TV apps using D-pad
platform: stb
requires_device: true
timeout_seconds: 2400
tools:
  - list_userinterfaces
  - get_userinterface_complete
  - list_nodes
  - list_edges
  - preview_userinterface
  - navigate_to_node
  - get_device_info
  - get_compatible_hosts
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
  - explore stb
  - explore tv
  - build tv tree
  - stb navigation
  - automate stb
---

# Build Tree Stb

Build navigation trees for STB/TV using screenshots and D-pad.

⚠ **TWO UI SYSTEMS — keep them straight.** This skill writes to the production
`userinterfaces` + `navigation_trees` tables (executable graph). The AI-learned
narrative knowledge base is a SEPARATE system (`ai_userinterfaces` tables,
slugs like `example-5.02` / `netflix-8` / `exampletv-ch`). Calling
`navigate_to_node(userinterface_name='example-5.02')` will 404 because that
slug only exists in `ai_userinterfaces`. To read the learned knowledge, use
the `ai-userinterface` skill or its tools (`get_ai_userinterface`,
`resolve_ai_userinterface`). See `docs/agent/AI_USERINTERFACE.md`.

STEP 0 — CONSULT THE AI UI KNOWLEDGE BASE FIRST (DB-backed):
1. Resolve the device's UI: call resolve_ai_userinterface with
   fingerprint_type='software_version_glob' and value=<SOFTWARE VERSION read
   from the About screen>. If matched, use the returned ui_id.
2. If a ui_id is known: get_ai_userinterface(ui_id) returns the bundle (parent
   plus active screens / flows / quirks / known_hardware / fingerprints).
   - Reuse verified flows by key_sequence instead of re-exploring known paths.
   - Respect quirks (e.g. OK render >2 s, HOME absorbed in modals).
3. If no match: explore first, then document only what you physically confirm.
4. Reference: docs/agent/AI_USERINTERFACE.md.

VERIFIED-ONLY RULE for the AI UI knowledge base:
- Schema-enforced: every ai_userinterface_* sub-row has verified_against NOT NULL.
- Never write a row whose verified_against you didn't physically observe this session.
- Unknowns go in ai_userinterfaces.unknown_todo on the parent record, never as
  fake "verified" sub-rows.

AFTER A SUCCESSFUL FLOW (self-improvement loop, write back to DB via tools):
- add_ai_userinterface_transition(ui_id, name, key_sequence, verified_against=<build>,
  verified_at=today, from_screen, to_screen, actor)
- add_ai_userinterface_quirk(ui_id, description, verified_against, actor) for any
  new quirk observed
- add_ai_userinterface_known_hardware for a new hardware model that rendered this UI
- add_ai_userinterface_fingerprint for a new fingerprint pattern observed
- If the UI had no parent row yet: create_ai_userinterface(data, actor) populated
  only with what you actually verified. Schema CHECK enforces category invariants.
- To correct a wrong row (yours or a prior agent's): supersede_ai_userinterface_row
  with reason. Never DELETE — the audit trail is the safety net.
- Batch same-direction key presses (RIGHT × 5 to cross a tab bar);
  only capture_screenshot at branch points (after OK or a direction change).

Note: No UI dump available - use screenshots and AI vision.
   - capture_screenshot - Get current screen
   - create_node or update_node (visual verifications)
   - save_node_screenshot(node_id, tree_id)
   - create_edge or update_edge with D-pad actions (press_key: UP/DOWN/LEFT/RIGHT/OK/BACK)
   - execute_device_action to test the action works
   - navigate_to_node to move around
6. verify_node to test verifications work
   (no release_control needed — locks release automatically per action)

IMPORTANT:
- Use list_nodes/list_edges to see what already exists before creating
- Use update_node/update_edge to fix broken edges instead of recreating
- Use verify_node to test verifications before moving on
