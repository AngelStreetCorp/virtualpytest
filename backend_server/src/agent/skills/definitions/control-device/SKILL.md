---
name: control-device
description: Control devices with direct hardware actions
requires_device: true
timeout_seconds: 1800
tools:
  - get_device_info
  - list_actions
  - execute_device_action
  - dump_ui_elements
  # AI UI knowledge base (read-only; full read+write in build-tree-* skills)
  - list_ai_userinterfaces
  - get_ai_userinterface
  - resolve_ai_userinterface
triggers:
  - execute action
  - device action
  - click
  - tap
  - swipe
  - press key
  - available actions
  - show device
  - get device
  - dump ui
  - show ui
  - inspect screen
---

# Control Device

Control physical devices with raw hardware actions (click, swipe, press).

WORKFLOW:
1. get_device_info() → find available devices
2. list_actions() → see valid actions for the device
3. execute_device_action() → use ONLY actions from step 2, match parameters exactly

UI TOOLS:
- list_userinterfaces: List all available interfaces (Do not use for dump ui)
- dump_ui_elements: Dump current screen UI elements (does not require list_userinterfaces)

IR / BLE remotes (no UI dump available):
- dump_ui_elements does NOT work for IR/BLE controllers — they are one-way (send only).
- Read the screen via the stream capture pipeline (see docs/agent/DEVICE_SCREENSHOTS.md).
- When walking a known menu (e.g. RIGHT × 5 to reach a tab), batch the same-key presses
  and only screenshot at branch points (after OK or after a direction change).
- Render after OK can take >2 s on STB UIs; do not retry OK within that window.

AI UI knowledge base (DB-backed; see docs/agent/AI_USERINTERFACE.md):
- resolve_ai_userinterface maps a runtime fingerprint (e.g. SOFTWARE VERSION
  for STB, foreground_package for Android) to a known ui_id.
- get_ai_userinterface returns verified screens, flows, quirks for that ui_id.
- Read this BEFORE navigating to avoid re-discovering known sequences.
- Write access is in the dedicated `ai-userinterface` skill (this one is read-only).
- ⚠ DO NOT confuse `ai_userinterfaces` slugs (example-5.02 / netflix-8 / exampletv-ch)
  with the production `userinterfaces` (google_tv / sauce-demo). They are separate
  systems sharing only a name fragment. Calling navigate_to_node or preview_userinterface
  with an ai_userinterfaces slug returns 404 — use get_ai_userinterface instead.
