---
name: navigate-tree
description: Navigate apps using predefined userinterface tree
requires_device: true
timeout_seconds: 900
think_budget_seconds: 120
max_tool_calls: 40
tools:
  - list_userinterfaces
  - preview_userinterface
  - localize
  - localize_coverage
  - navigate_to_node
  - get_node
  - get_edge
  - verify_node
  - execute_edge
triggers:
  - navigate
  - goto
  - go
  - show userinterface
  - list userinterfaces
  - show nodes
  - show edges
  - list nodes
  - list edges
  - preview userinterface
  - verify node
  - node verification
  - execute edge
  - execute transition
  - run transition
  - perform transition
---

# Navigate Tree

Navigate apps using predefined userinterface tree.

IMPORTANT: tree_id, node_id, and edge_id are auto-resolved - no need to call preview_userinterface first

VERIFICATION QUERIES:
- "get [node] verification" → get_node(node_label='[node]') - Shows configured verifications without running them
- "verify node [node]" → verify_node(node_label='[node]') - Actually runs verification checks

**Where am I? — `localize` first (TASK-107).** After a step (an OK, a goto, a failed goto) call `localize(host_name, device_id, userinterface_name)`: it answers in one line, with no image — `node` (which saved screen), `live`, `signal`, `overlay`, `known_screen` or `unknown`. `navigate_to_node` already appends that verdict and attaches a screenshot only when it does not confirm the target. Take a screenshot only when the verdict is `unknown`, `overlay` or `known_screen`, or when you need to read text on the screen.
`localize_coverage(userinterface_name)` says how much of a tree Localize can name (0% = only signal / live / unknown).

WORKFLOW:
1. navigate_to_node(target_node_label='home') - Navigate to screen using pathfinding
2. execute_edge(edge_label='home -> search') - Execute specific edge actions
3. get_node(node_label='search') - Get node details including configured verifications
4. verify_node(node_label='search') - Actually run and check current screen state

## Set-top box asleep? (read `docs/agent/devices/STB_STANDBY.md`)

A dark capture means the box is asleep, not broken; never blame the box.
- Asleep = SMPTE colour bars, or near-black with a tiny identical file size. Garbled frames while waking are normal.
- IR box: POWER once, wait 60 s; a first press that does nothing is normal; second POWER 60 s later. POWER and HOME toggle: never twice in a row.
- BLE box, active standby: poll `get_pairing_status`; the link returns by itself in about 30 s.
- BLE box, deep standby (link still down after ~30 s, `resume_state: failed`): send `cold_wake` (action `ble_cold_wake`, WoBLE). It is NOT pairing. Poll `get_pairing_status` about 25 s, then capture until a real picture.
- Never Start Pairing, in particular never after a reboot. Still dark after two POWER presses or two `cold_wake`: report `env: no signal` and stop.
