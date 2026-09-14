---
name: navigate-tree
description: Navigate apps using predefined userinterface tree
requires_device: true
timeout_seconds: 900
tools:
  - list_userinterfaces
  - preview_userinterface
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

WORKFLOW:
1. navigate_to_node(target_node_label='home') - Navigate to screen using pathfinding
2. execute_edge(edge_label='home -> search') - Execute specific edge actions
3. get_node(node_label='search') - Get node details including configured verifications
4. verify_node(node_label='search') - Actually run and check current screen state
