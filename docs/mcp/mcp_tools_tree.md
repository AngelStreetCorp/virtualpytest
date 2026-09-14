# MCP Tree Tools - Primitive Navigation Tree Management

## Overview

The **11 primitive tools** provide atomic building blocks for navigation tree management. Unlike specialized workflows, these tools can be **composed** by the LLM for any purpose:

- ✅ **AI exploration** - Build trees automatically
- ✅ **Manual tree building** - Create nodes/edges one by one
- ✅ **Debugging & fixing** - Update broken edges after testing
- ✅ **Tree refactoring** - Restructure existing trees
- ✅ **Quality assurance** - Validate tree structure

## Architecture Philosophy

**Stateless Primitives > Stateful Workflows**

```
❌ OLD: Specialized exploration tools
   start_exploration() → continue_exploration() → finalize_exploration()
   (Rigid workflow, limited to exploration only)

✅ NEW: Composable primitives
   dump_ui_elements() + create_node() + execute_device_action() + create_edge()
   (Flexible composition, works for any workflow)
```

## The 11 Primitive Tools

### **Tree Structure Management**

1. **`create_node`** - Add node to tree
2. **`update_node`** - Modify node properties
3. **`delete_node`** - Remove node
4. **`create_edge`** - Add edge with actions
5. **`update_edge`** - Fix edge actions
6. **`delete_edge`** - Remove edge
7. **`create_subtree`** - Create subtree for deeper exploration
8. **`get_node`** - Get specific node by ID
9. **`get_edge`** - Get specific edge by ID

### **Edge & Node Execution**

10. **`execute_edge`** - Execute edge actions directly
11. **`verify_node`** - Execute node verifications without navigation

### **UI Inspection**

12. **`dump_ui_elements`** - See what's on screen (critical for debugging)

---

## 🎯 AI Exploration Workflows

### Workflow 1: Manual Tree Building (Test-First)

```python
# LLM orchestrates primitives for exploration

# 1. Inspect current screen
elements = dump_ui_elements(device_id="device1", platform="mobile")
# Returns: ["Home Tab", "Settings Tab", "TV Guide Tab", ...]

# 2. Create root node
create_node(
    tree_id="main_tree",
    label="home",
    position={"x": 0, "y": 0}
)

# 3. For each navigation target
for target in ["Settings Tab", "TV Guide Tab"]:
    # 3a. Test navigation first
    execute_device_action(actions=[
        {"command": "click_element", "params": {"text": target}}
    ])
    
    # 3b. Verify we moved
    verify_device_state(verifications=[...])
    
    # 3c. If success, create node + edge
    node_id = target.lower().replace(" tab", "")
    
    create_node(
        tree_id="main_tree",
        node_id=node_id,
        label=node_id
    )
    
    create_edge(
        tree_id="main_tree",
        source_node_id="home",
        target_node_id=node_id,
        action_sets=[
            {
                "id": f"home_to_{node_id}",
                "actions": [{"command": "click_element", "params": {"text": target}}]
            },
            {
                "id": f"{node_id}_to_home",
                "actions": [{"command": "press_key", "params": {"key": "BACK"}}]
            }
        ]
    )
    
    # 3d. Navigate back
    execute_device_action(actions=[{"command": "press_key", "params": {"key": "BACK"}}])

# Result: 3 nodes + 3 edges, all tested and working!
```

### Workflow 2: Debug & Fix Failed Edge

```python
# Edge from home → settings fails

# 1. Navigate to source
navigate_to_node(target_node_label="home")

# 2. Dump UI to see actual element names
elements = dump_ui_elements(device_id="device1")
# Returns: [{"text": "Settings Tab", "clickable": true, ...}, ...]

# 3. LLM analyzes: "Ah! It's 'Settings Tab', not 'Settings'"

# 4. Update edge with correct element name
update_edge(
    tree_id="main_tree",
    edge_id="edge_home_settings",
    action_sets=[
        {
            "id": "home_to_settings",
            "actions": [{"command": "click_element", "params": {"text": "Settings Tab"}}]
        },
        {
            "id": "settings_to_home",
            "actions": [{"command": "press_key", "params": {"key": "BACK"}}]
        }
    ]
)

# 5. Test fix
navigate_to_node(target_node_label="settings")
# ✅ Works now!
```

### Workflow 3: Recursive Subtree Exploration

```python
# Explore main tree + subtrees automatically

# === LEVEL 1: Main Tree ===
main_tree_id = "abc-123"

# 1. Inspect & create main tree
elements = dump_ui_elements()
for element in elements:
    create_node(tree_id=main_tree_id, label=element)
    create_edge(tree_id=main_tree_id, ...)

# === LEVEL 2: Subtrees ===
for node in ["settings", "tvguide", "replay"]:
    # 2. Create subtree
    result = create_subtree(
        parent_tree_id=main_tree_id,
        parent_node_id=node,
        subtree_name=f"{node}_subtree"
    )
    subtree_id = result['subtree_tree_id']
    
    # 3. Navigate to parent
    navigate_to_node(tree_id=main_tree_id, target_node_label=node)
    
    # 4. Inspect subtree screen
    elements = dump_ui_elements()
    
    # 5. Create subtree nodes/edges (SAME primitives, different tree_id!)
    for element in elements:
        create_node(tree_id=subtree_id, label=f"{node}_{element}")
        create_edge(tree_id=subtree_id, ...)
    
    # 6. Navigate back
    navigate_to_node(target_node_label="home")

# Result: Complete 2-level tree automatically!
```

### Workflow 4: Iterative Refinement

```python
# Create → Test → Fix → Re-test loop

# 1. Create structure (fast creation)
create_node(...)
create_edge(...)

# 2. Test edge
result = navigate_to_node(target_node_label="settings")

# 3. If failed, debug
if not result.success:
    # See what's actually on screen
    elements = dump_ui_elements()
    
    # Find correct element
    correct_element = find_similar(elements, "settings")
    
    # Update edge
    update_edge(edge_id="...", action_sets=[...correct_element...])
    
    # Re-test
    result = navigate_to_node(target_node_label="settings")
    
    if result.success:
        print("✅ Fixed!")
    else:
        # Still failing, delete node
        delete_node(node_id="settings")
        print("⚠️ Skipped problematic node")
```

---

## 🛠️ Tool Reference

### create_node

Create a node in navigation tree.

**Parameters:**
```json
{
  "tree_id": "main_tree",        // REQUIRED
  "label": "settings",            // REQUIRED
  "node_id": "settings",          // Optional - auto-generated if omitted
  "type": "screen",               // Optional - default: "screen"
  "position": {"x": 100, "y": 200}, // Optional
  "data": {}                      // Optional - custom metadata
}
```

**Returns:**
```json
{
  "node": {
    "id": "settings",
    "label": "settings",
    "type": "screen",
    "position": {"x": 100, "y": 200}
  }
}
```

---

### update_node

Update existing node properties (including verifications).

**Parameters:**
```json
{
  "tree_id": "main_tree",
  "node_id": "settings",
  "updates": {
    "label": "settings_main",
    "position": {"x": 150, "y": 200},
    "verifications": [
      {
        "command": "waitForElementToAppear",
        "params": {"search_term": "Settings", "timeout": 10},
        "verification_type": "adb"
      }
    ]
  }
}
```

**Supported Fields:**
- `label` - Node display name
- `position` - {x, y} coordinates
- `type` - Node type (screen, menu, etc.)
- `data` - Custom metadata object
- `verifications` - Array of verification objects (NEW in v4.2.0)

**Note:** The `verifications` field allows you to add or replace node verifications. Use `verify_node` to test verifications after updating.

---

### delete_node

Delete node and connected edges.

**Parameters:**
```json
{
  "tree_id": "main_tree",
  "node_id": "old_node"
}
```

---

### create_edge

Create edge with navigation actions.

**Action Wait Time Requirements:**
Each action in action_sets MUST include a 'wait_time' field (milliseconds) INSIDE params.
Use standard wait times: launch_app (8000), click_element (2000), press_key (1500).

**Parameters:**
```json
{
  "tree_id": "main_tree",
  "source_node_id": "home",
  "target_node_id": "settings",
  "action_sets": [
    {
      "id": "home_to_settings",
      "actions": [
        {"command": "click_element", "params": {"text": "Settings Tab", "wait_time": 2000}}
      ]
    },
    {
      "id": "settings_to_home",
      "actions": [
        {"command": "press_key", "params": {"key": "BACK", "wait_time": 1500}}
      ]
    }
  ]
}
```

---

### ⏱️ Edge Action Wait Times

When creating edges, each action requires appropriate wait times for reliable navigation:

#### Common Edge Patterns

**Tab Navigation:**
```json
{"command": "click_element", "params": {"element_id": "Search Tab", "wait_time": 2000}}
```
- Standard 2-second wait for tab animation + screen transition

**Back Button:**
```json
{"command": "press_key", "params": {"key": "BACK", "wait_time": 1500}}
```
- 1.5 seconds for back navigation (faster than forward)

**App Launch (Entry → Home):**
```json
{"command": "launch_app", "params": {"package": "com.example.app", "wait_time": 8000}}
```
- 8 seconds for app initialization + splash screen + home render

**Content Load (Home → Detail):**
```json
{"command": "click_element", "params": {"element_id": "Movie Card", "wait_time": 3000}}
```
- 3 seconds for heavy page with images/metadata

**Video Start (Detail → Player):**
```json
{"command": "click_element", "params": {"element_id": "Play", "wait_time": 5000}}
```
- 5 seconds for player initialization + buffering

**💡 See:** [Action Tools - Wait Time Guidelines](mcp_tools_action.md#⏱️-action-wait-time-guidelines) for complete reference.

---

### update_edge

Update edge actions (for fixing broken navigation).

**Parameters:**
```json
{
  "tree_id": "main_tree",
  "edge_id": "edge_home_settings",
  "action_sets": [
    // New action sets
  ]
}
```

---

### delete_edge

Delete edge from tree.

**Parameters:**
```json
{
  "tree_id": "main_tree",
  "edge_id": "edge_old"
}
```

---

### create_subtree

Create subtree for deeper exploration.

**Parameters:**
```json
{
  "parent_tree_id": "main_tree",
  "parent_node_id": "settings",
  "subtree_name": "settings_subtree"
}
```

**Returns:**
```json
{
  "subtree": {
    "id": "subtree-abc-123",
    "name": "settings_subtree"
  },
  "subtree_tree_id": "subtree-abc-123"  // Use this for create_node in subtree!
}
```

---

### get_node

Get a specific node by ID.

Returns full node details including position, data, and verifications.
Use this to inspect node structure before updating or to verify node creation.

**Parameters:**
```json
{
  "tree_id": "main_tree",
  "node_id": "settings"
}
```

---

### get_edge

Get a specific edge by ID.

Returns full edge details including action_sets, handles, and metadata.
Use this to inspect edge structure before updating or to verify edge creation.

**Parameters:**
```json
{
  "tree_id": "main_tree",
  "edge_id": "edge_home_settings"
}
```

---

### execute_edge

Execute a specific edge's action set without full navigation (frontend: useEdge.ts executeActionSet).

**Parameters:**
```json
{
  "edge_id": "edge-entry-node-to-home",    // REQUIRED - Edge identifier
  "tree_id": "ae9147a0-07eb-44d9-be71-aeffa3549ee0",  // REQUIRED - Navigation tree ID
  "action_set_id": "actionset-1762771271791",  // Optional - uses default if omitted
  "device_id": "device1",                  // Optional - defaults to 'device1'
  "host_name": "host1",                // Optional - defaults to 'host1'
  "team_id": "team_1"                      // Optional - uses default
}
```

**Returns:**
```json
{
  "success": true,
  "message": "Edge executed: Entry→home\n   Direction: forward (entry-node → home)\n   Action Set: actionset-1762771271791\n   Actions: 1 executed\n   Result: Action execution completed: 1/1 passed"
}
```

**Example:**
```python
# Execute the entry→home edge in netflix_mobile
execute_edge({
    "edge_id": "edge-entry-node-to-home",
    "tree_id": "ae9147a0-07eb-44d9-be71-aeffa3549ee0"
})
# Returns: ✅ Edge executed with launch_app action
```

**Use Cases:**
- **Test Individual Edges** - Verify edge actions work without full navigation
- **Debug Edge Actions** - Test specific edges after updating them
- **Manual Edge Execution** - Execute edges directly from UI or scripts

**Frontend Equivalent:**
This tool mirrors the frontend's `executeActionSet` function from `useEdge.ts` (line 104-161), which executes edge actions with navigation context for proper metrics recording.

---

### verify_node

Execute embedded verifications for a specific node without navigation (frontend: Navigation_NodeEditDialog.tsx "Run" button).

**Parameters:**
```json
{
  "node_id": "home",                       // REQUIRED - Node identifier
  "tree_id": "ae9147a0-07eb-44d9-be71-aeffa3549ee0",  // REQUIRED - Navigation tree ID
  "userinterface_name": "netflix_mobile",  // REQUIRED - User interface name
  "device_id": "device1",                  // Optional - defaults to 'device1'
  "host_name": "host1",                // Optional - defaults to 'host1'
  "team_id": "team_1"                      // Optional - uses default
}
```

**Returns:**
```json
{
  "success": true,
  "message": "Verification completed: 1/1 passed\n   Node: home\n   ✅ waitForElementToAppear: Element 'Startseite' found"
}
```

**Example:**
```python
# Verify home node in netflix_mobile
verify_node({
    "node_id": "home",
    "tree_id": "ae9147a0-07eb-44d9-be71-aeffa3549ee0",
    "userinterface_name": "netflix_mobile"
})
# Returns: ✅ Verification completed: 1/1 passed
```

**How It Works:**
1. Gets the node's embedded verifications
2. Calls `/server/verification/executeBatch` directly (same as frontend's "Run" button)
3. Polls for async completion (up to 30s)
4. Returns verification results with pass/fail details

**Use Cases:**
- **Test Node Verifications** - Verify node checks work independently
- **Debug Verification Logic** - Test specific node verifications after updating them via `update_node`
- **Manual Verification** - Execute verifications directly from MCP or scripts
- **Quality Assurance** - Validate verifications before full navigation testing

**Frontend Equivalent:**
This tool mirrors the frontend's "Run" button in `Navigation_NodeEditDialog.tsx` (line 195), which calls `useVerification.handleTest()` → `/server/verification/executeBatch` (line 247 in `useVerification.ts`).

**Note:** 
- If the node has no verifications, the tool returns: "ℹ️ Node has no verifications to run"
- This does NOT trigger navigation - it executes verifications directly on the current screen
- For navigation-based verification, use `navigate_to_node` which automatically runs verifications

---

### dump_ui_elements

Dump UI elements from current screen.

**Parameters:**
```json
{
  "device_id": "device1",           // Optional - defaults to 'device1'
  "host_name": "host1",         // Optional - defaults to 'host1'
  "platform": "mobile",             // Optional - 'mobile', 'web', 'tv'
  "team_id": "team_1"              // Optional - uses default
}
```

**Returns:**
```json
{
  "elements": [
    {
      "text": "Settings Tab",
      "resource-id": "tab_settings",
      "clickable": true,
      "bounds": "[0,0][100,50]"
    },
    {
      "text": "TV Guide Tab",
      "resource-id": "tab_tvguide",
      "clickable": true,
      "bounds": "[100,0][200,50]"
    }
  ],
  "total": 45,
  "clickable_count": 12
}
```

---

**Related Documentation:**
- [Action Tools](mcp_tools_action.md) - For execute_device_action
- [Navigation Tools](mcp_tools_navigation.md) - For navigate_to_node
- [Verification Tools](mcp_tools_verification.md) - For verify_device_state
- [UserInterface Tools](mcp_tools_userinterface.md) - For app model creation
- [Core Documentation](mcp_core.md) - Architecture and setup

