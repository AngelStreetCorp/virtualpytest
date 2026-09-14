---
name: build-tree-mobile
description: Build navigation tree for mobile apps with auto-validation
platform: mobile
requires_device: true
timeout_seconds: 1800
tools:
  - navigate_to_node
  - list_userinterfaces
  - get_userinterface_complete
  - list_nodes
  - list_edges
  - preview_userinterface
  - get_compatible_hosts
  - auto_discover_screen
  - dump_ui_elements
  - analyze_screen_for_action
  - analyze_screen_for_verification
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
  - explore mobile
  - explore android
  - build userinterface
  - create userinterface
  - update node
  - edit node
  - update edge
  - save node screenshot
  - edit edge
  - edit subtree
  - create subtree
  - delete subtree
  - create node
  - create edge
  - edit userinterface
  - edit navigation
  - explore app
  - build app
---

# Build Tree Mobile

Build navigation trees for mobile apps.

STEP 0 — CONSULT THE AI UI KNOWLEDGE BASE FIRST (DB-backed):
1. Resolve the foreground app via `adb shell dumpsys window | grep mCurrentFocus`,
   then call resolve_ai_userinterface(fingerprint_type='foreground_package', value=<pkg>).
2. If a ui_id is returned: get_ai_userinterface(ui_id) for the full bundle.
   - Reuse verified flows instead of re-exploring known paths.
   - Respect quirks (e.g. keys absorbed by certain apps).
3. If no row exists for this UI: explore first, then document only what you confirm.
4. Reference: docs/agent/AI_USERINTERFACE.md.

VERIFIED-ONLY RULE for the AI UI knowledge base:
- Schema-enforced: every ai_userinterface_* sub-row carries verified_against NOT NULL.
- Never write a row whose verified_against you didn't physically observe this session.
- Unknowns go in ai_userinterfaces.unknown_todo on the parent record.

AFTER A SUCCESSFUL FLOW (self-improvement loop, write back to DB via tools):
- add_ai_userinterface_transition(ui_id, name, key_sequence, verified_against=<app version>,
  verified_at=today, actor)
- add_ai_userinterface_quirk(ui_id, description, verified_against, actor)
- If the UI had no parent row yet: create_ai_userinterface with category='android-mobile',
  app=<slug>, app_package=<com.example.pkg>. Schema CHECK requires app IS NOT NULL.
- To correct a wrong row: supersede_ai_userinterface_row with reason. Never DELETE.

Note: auto_discover_screen automatically includes validation.

PHASE 1 - DISCOVER & VALIDATE (automatic):
auto_discover_screen(tree_id, host_name, userinterface_name)
→ Creates nodes/edges
→ AUTOMATICALLY validates each edge (forward + backward)
→ Returns validation results including FAILED_ITEMS

PHASE 2 - FIX FAILURES ONLY (if any):
Check the 'failed_items' in auto_discover_screen response.

If there are failures:
1. dump_ui_elements() - See current screen state
2. For each failed edge:
   - If forward failed: analyze_screen_for_action() to find correct selector
   - If backward failed: check if 2x BACK needed (keyboard screens)
3. update_edge() to fix the edge actions
4. Optionally: execute_device_action() to test the fix

⚠️ KEYBOARD SCREENS: Need 2x BACK
When backward validation fails, update_edge with iterator:2:
```
update_edge(
  tree_id=..., edge_id=...,
  action_sets=[
    {...forward...},
    {"id": "x_to_home", "label": "x → home",
     "actions": [{"command": "press_key", "params": {"key": "BACK"}, "iterator": 2}],
     "retry_actions": [], "failure_actions": []}
  ]
)
```

PHASE 3 - SCREENSHOTS (optional, for nodes without them):
For nodes that need screenshots:
- navigate_to_node(target_node_label="...")
- save_node_screenshot(...)

CLEANUP: none needed — device locking is automatic per action (no release_control tool exists).
