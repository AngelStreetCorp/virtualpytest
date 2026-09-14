---
name: edit-tree
description: Create, update, and delete navigation tree structure (nodes and edges)
timeout_seconds: 600
tools:
  - get_userinterface_complete
  - list_nodes
  - list_edges
  - get_node
  - get_edge
  - create_node
  - update_node
  - delete_node
  - create_edge
  - update_edge
  - delete_edge
  - create_subtree
  - save_node_screenshot
triggers:
  - define
  - modify
  - update node
  - update edge
  - create node
  - create edge
  - delete node
  - delete edge
  - manage nodes
  - manage edges
  - edit navigation
  - configure ui
  - setup navigation
  - get node verification
  - show node verification
  - check verification
---

# Edit Tree

Modify navigation tree structures and inspect node configurations: create, update, delete nodes and edges, view verification setups.

VERIFICATION QUERIES:
- "get [node] verification" → get_node(node_label='[node]') - Shows configured verifications without running them
- "verify node [node]" → verify_node(node_label='[node]') - Actually runs verification checks


WORKFLOW:
1. list_nodes() - For node list overview
2. list_edges() - For edge list overview
3. get_node() - For specific node details and configured verifications
4. get_edge() - For specific edge details
5. update_node() - Modify node properties (verifications, labels)
6. update_edge() - Modify edge actions and transitions
7. create_node()/create_edge() - Add new elements
8. delete_node()/delete_edge() - Remove elements

IMPORTANT:
- Node/edge IDs are auto-generated, use labels for identification
- get_node() shows configured verifications - use verify_node() to actually run them
- After structural changes, test navigation with execute_edge
