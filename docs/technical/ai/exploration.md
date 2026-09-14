# Automatic AI Exploration - No User Approval

## Overview

Automatic exploration allows AI to generate navigation tree nodes without user approval. Perfect for CI/CD, automated testing, or programmatic tree building.

---

## Main Tree Exploration

### Flow

```bash
# 1. Start exploration (Phase 1: Analysis)
POST /host/ai-generation/start-exploration
{
  "tree_id": "main_tree_uuid",
  "device_id": "device1",
  "userinterface_name": "example_mobile"
}
# Response: { exploration_id: "exp_123", status: "exploring" }

# 2. Poll until status = "awaiting_approval"
GET /host/ai-generation/exploration-status/<exploration_id>?device_id=device1
# Response: { status: "awaiting_approval", plan: { items: [...] } }

# 3. Create nodes/edges (Phase 2a: Structure Creation)
POST /host/ai-generation/continue-exploration?host_name=<host_name>
{
  "exploration_id": "exp_123",
  "device_id": "device1"
}
# Response: { nodes_created: 5, edges_created: 5 }

# 4. Finalize (Remove _temp suffix)
POST /host/ai-generation/finalize-structure
{
  "tree_id": "main_tree_uuid"
}
# Response: { nodes_renamed: 5, edges_renamed: 5 }
```

### Result

```
Main Tree:
├─ home (root)
├─ settings
├─ tv_guide
├─ replay
└─ search
```

---

## Subtree Exploration

### Prerequisites

1. Main tree exists with nodes
2. Device is at the screen you want to explore

### Flow

```bash
# 0. Create subtree for parent node
POST /server/navigationTrees/<main_tree_id>/nodes/home_replay/subtrees
{
  "name": "home_replay_subtree"
}
# Response: { tree: { id: "subtree_uuid" } }

# 1. Navigate device to parent node (use existing navigation)
POST /server/navigation/goto
{
  "target_node": "home_replay"
}

# 2. Start exploration with SUBTREE tree_id
POST /host/ai-generation/start-exploration
{
  "tree_id": "subtree_uuid",  # ← Use subtree ID!
  "device_id": "device1",
  "userinterface_name": "example_mobile"
}

# 3. Poll until ready
GET /host/ai-generation/exploration-status/<exploration_id>?device_id=device1

# 4. Continue exploration
POST /host/ai-generation/continue-exploration?host_name=<host_name>
{
  "exploration_id": "exp_456",
  "device_id": "device1"
}

# 5. Finalize with SUBTREE tree_id
POST /host/ai-generation/finalize-structure
{
  "tree_id": "subtree_uuid"  # ← Same subtree ID
}
```

### Result

```
Main Tree:
└─ home_replay (has subtree)

Subtree "home_replay_subtree":
├─ channels
├─ favorites
└─ search
```

---

## Key Points

### ✅ No User Approval
- Call 4 endpoints in sequence
- System analyzes, creates, and finalizes automatically

### ✅ Tree ID Controls Everything
- `tree_id = main_tree_uuid` → Nodes in main tree
- `tree_id = subtree_uuid` → Nodes in subtree

### ✅ Simple Exploration (1 Level)
- Click → Wait 2s → Back → Verify → Create node/edge
- Fast: ~20-30 seconds for 10 items

### ✅ Navigation is Separate
- You handle navigation to starting screen
- Exploration starts from wherever device is

---

## Endpoints Reference

### Exploration Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/host/ai-generation/start-exploration` | POST | Start AI analysis |
| `/host/ai-generation/exploration-status/<id>` | GET | Check status |
| `/host/ai-generation/continue-exploration` | POST | Create nodes/edges |
| `/host/ai-generation/finalize-structure` | POST | Remove _temp suffix |

### Supporting Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/server/navigationTrees/<tree_id>/nodes/<node_id>/subtrees` | POST | Create subtree |
| `/server/navigation/goto` | POST | Navigate device |

---

## Example: Recursive Exploration

To explore entire tree automatically:

```python
def explore_tree_recursive(tree_id, max_depth=3):
    """
    Explore tree recursively up to max_depth
    
    Args:
        tree_id: Root tree ID
        max_depth: Maximum depth to explore
    """
    queue = [(tree_id, None, 0)]  # (tree_id, parent_node, depth)
    
    while queue:
        current_tree_id, parent_node, depth = queue.pop(0)
        
        if depth >= max_depth:
            continue
        
        # 1. Navigate to parent node (if not root)
        if parent_node:
            navigate_to_node(parent_node)
        
        # 2. Run automatic exploration
        exploration_id = start_exploration(current_tree_id)
        wait_until_ready(exploration_id)
        result = continue_exploration(exploration_id)
        finalize_structure(current_tree_id)
        
        # 3. For each new node, create subtree and add to queue
        if depth + 1 < max_depth:
            for node in result['nodes_created']:
                subtree = create_subtree(current_tree_id, node)
                queue.append((subtree['id'], node, depth + 1))
```

---

## Notes

- **No navigation inside exploration**: Device must be on correct screen before starting
- **Polling required**: Step 2 needs polling until `status = "awaiting_approval"`
- **_temp suffix**: Nodes created with `_temp`, removed in finalize step
- **Subtree naming**: Use `{parent_node}_subtree` convention

---

## See Also

- AI Tree Creation - Full manual exploration workflow
- Navigation Architecture - Navigation system details

