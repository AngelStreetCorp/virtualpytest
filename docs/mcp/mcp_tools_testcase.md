# MCP Testcase Tools

[← Back to MCP Documentation](./README.md)

---

### 🧪 TestCase Management

#### save_testcase

Save test case graph to database.

**✅ RECOMMENDED FOR AI AGENTS:** Use this tool to save test cases you've built yourself.
Build the `graph_json` with nodes and edges (see [Graph Validation](#graph-validation-rules) for format),
then save with this tool. Use `list_navigation_nodes()` for valid `target_node_id` values,
`list_actions()` for valid action commands, and `list_verifications()` for valid verification commands.

**⚠️ VALIDATION:** Graph structure is validated before saving. See [Graph Validation](#graph-validation-rules) for required format.

**Parameters:**
```json
{
  "testcase_name": "Home Screen Test",   // REQUIRED
  "graph_json": {                        // REQUIRED - from generate_test_graph
    "nodes": [...],
    "edges": [...],
    "scriptConfig": {...}
  },
  "description": "Verify home screen elements",  // Optional
  "userinterface_name": "example_mobile",  // Optional
  "folder": "smoke_tests",               // Optional - for organization
  "tags": ["regression", "critical"],    // Optional - for filtering
  "team_id": "team_1"                    // Optional (defaults to 'team_1')
}
```

**Returns:**
```json
{
  "success": true,
  "testcase_id": "tc-abc-123",
  "action": "created"
}
```

**Validation Errors:**
If graph structure is invalid, returns:
```json
{
  "error": "Graph validation failed:\n❌ Navigation node 'nav-1' missing 'target_node' (UUID)\n❌ Edge 'e-1' has invalid type 'default'"
}
```

---

#### list_testcases

List all saved test cases.

**Parameters:**
```json
{
  "team_id": "team_1",                   // Optional (defaults to 'team_1')
  "include_inactive": false              // Optional (default: false)
}
```

**Returns:**
```json
{
  "testcases": [
    {
      "testcase_id": "tc-abc-123",
      "testcase_name": "Home Screen Test",
      "description": "Verify home screen elements",
      "userinterface_name": "example_mobile",
      "folder": "smoke_tests",
      "tags": ["regression", "critical"],
      "created_at": "2025-01-01T00:00:00Z",
      "updated_at": "2025-01-02T00:00:00Z"
    }
  ],
  "total": 42
}
```

---

#### load_testcase

Load saved test case by ID.

**Parameters:**
```json
{
  "testcase_id": "tc-abc-123",           // REQUIRED
  "team_id": "team_1"                    // Optional (defaults to 'team_1')
}
```

**Returns:**
```json
{
  "success": true,
  "testcase": {
    "testcase_id": "tc-abc-123",
    "testcase_name": "Home Screen Test",
    "graph_json": {
      "nodes": [...],
      "edges": [...],
      "scriptConfig": {...}
    },
    "userinterface_name": "example_mobile"
  }
}
```

---

#### execute_testcase

Execute test case graph on device.

**⚠️ PREREQUISITE:** `take_control()` must be called first.

**Parameters:**
```json
{
  "graph_json": {                        // REQUIRED - from generate_test_graph or load_testcase
    "nodes": [...],
    "edges": [...],
    "scriptConfig": {...}
  },
  "device_id": "device1",                // Optional (defaults to 'device1')
  "host_name": "host1",              // Optional (defaults to 'host1')
  "userinterface_name": "example_mobile",  // Optional
  "testcase_name": "My Test",            // Optional - for logging
  "team_id": "team_1"                    // Optional (defaults to 'team_1')
}
```

**Returns:** Execution results after async completion (max 5 minutes).

**Example:**
```python
# Generate graph from prompt
graph = generate_test_graph({
    "prompt": "Navigate to home and verify Replay button",
    "userinterface_name": "example_mobile"
})

# Execute the generated graph
execute_testcase({
    "graph_json": graph['graph'],
    "testcase_name": "Home Verification"
})
# MCP waits until execution completes
# Returns: ✅ Execution completed: SUCCESS (2.3s)
```

---

#### execute_testcase_by_id

MCP convenience wrapper to load and execute saved test case by ID in one call.

**⚠️ PREREQUISITE:** `take_control()` must be called first.

**Parameters:**
```json
{
  "testcase_id": "tc-abc-123",           // REQUIRED
  "device_id": "device1",                // Optional (defaults to 'device1')
  "host_name": "host1",              // REQUIRED
  "userinterface_name": "example_mobile",  // Optional - overrides testcase's interface
  "team_id": "team_1"                    // Optional (defaults to 'team_1')
}
```

**Returns:** Execution results after async completion.

**Example:**
```python
# Execute saved test case in one call
execute_testcase_by_id({
    "testcase_id": "tc-abc-123",
    "host_name": "host1"
})
# Automatically loads + executes + waits for completion
# Returns: ✅ Execution completed: SUCCESS
```

---

## Graph Validation Rules

### Overview

The `save_testcase` tool validates graph structure **before saving** to catch errors early. This prevents invalid graphs from being stored in the database.

### Required Graph Structure

```json
{
  "nodes": [
    {"id": "start", "type": "start", ...},
    {"id": "nav-1", "type": "navigation", "data": {...}},
    {"id": "success", "type": "success", ...},
    {"id": "failure", "type": "failure", ...}
  ],
  "edges": [
    {"id": "e-1", "source": "start", "target": "nav-1", "type": "success"},
    {"id": "e-2", "source": "nav-1", "target": "success", "type": "success"},
    {"id": "e-3", "source": "nav-1", "target": "failure", "type": "failure"}
  ],
  "scriptConfig": {...}
}
```

### Node Type Requirements

#### Navigation Node ✅
**REQUIRED FIELDS:**
- `data.target_node_id` (UUID from navigation tree) - **REQUIRED**
- `data.target_node_label` (string label like "home", "player") - **REQUIRED**

**Example:**
```json
{
  "id": "nav-player",
  "type": "navigation",
  "data": {
    "label": "NavigateToPlayer",
    "target_node_id": "fb860f60-1f04-4b45-a952-5debf48f20c5",  // UUID (REQUIRED)
    "target_node_label": "player"  // String label (REQUIRED)
  }
}
```

**❌ WRONG:**
```json
{
  "type": "navigation",
  "data": {
    "target_node_label": "player"  // ❌ Missing target_node_id
  }
}
```

**❌ WRONG (Deprecated):**
```json
{
  "type": "navigation",
  "data": {
    "target_node": "fb860f60-..."  // ❌ Use target_node_id instead
  }
}
```

#### Action Node ✅
**REQUIRED FIELDS:**
- `data.command`
- `data.action_type`

**Example:**
```json
{
  "id": "action-back",
  "type": "action",
  "data": {
    "label": "ExitPlayer",
    "command": "press_key",
    "params": {"key": "BACK"},
    "action_type": "adb"
  }
}
```

#### Verification Node ✅
**REQUIRED FIELDS:**
- `data.verification_type`
- `data.command`

**Example:**
```json
{
  "id": "verify-player",
  "type": "verification",
  "data": {
    "label": "VerifyPlayerActive",
    "command": "waitForElementToAppear",
    "params": {"text": "Pause", "timeout": 10000},
    "verification_type": "adb",
    "action_type": "verification"
  }
}
```

### Edge Requirements

**REQUIRED FIELDS:**
- `source` (valid node ID)
- `target` (valid node ID)
- `type` = `"success"` OR `"failure"`

**✅ CORRECT:**
```json
{"id": "e-1", "source": "start", "target": "nav-1", "type": "success"}
```

**❌ WRONG:**
```json
{"id": "e-1", "source": "start", "target": "nav-1", "type": "default"}  // ❌ Invalid type
```

### Common Validation Errors

#### Error 1: Missing target_node_id
```
❌ Navigation node 'nav-player' missing 'target_node_id' (UUID from navigation tree).
```

**Fix:** Get the node UUID from the navigation tree and use it:
```python
# Get navigation tree nodes
tree = list_navigation_nodes(userinterface_name='netflix_mobile')
# Find the player node UUID
player_uuid = "fb860f60-1f04-4b45-a952-5debf48f20c5"

# Use it in navigation node (BOTH fields required)
{
  "type": "navigation",
  "data": {
    "target_node_id": player_uuid,  // ✅ UUID (REQUIRED)
    "target_node_label": "player"   // ✅ String label (REQUIRED)
  }
}
```

#### Error 2: Invalid Edge Type
```
❌ Edge 'e-1' has invalid type 'default'.
   Must be 'success' or 'failure'.
```

**Fix:** Use only `"success"` or `"failure"`:
```json
{"type": "success"}  // ✅ Correct
{"type": "failure"}  // ✅ Correct
{"type": "default"}  // ❌ Wrong
```

### How to Get Node UUIDs

**Method 1: List Navigation Nodes**
```python
nodes = list_navigation_nodes(userinterface_name='netflix_mobile')
# Returns: [{node_id: "fb860...", label: "player"}, ...]
```

**Method 2: Get Complete UserInterface**
```python
ui = get_userinterface_complete(userinterface_id='ui-abc-123')
# Returns full tree with all node UUIDs
```

**Method 3: Use AI Generation**
The `generate_test_graph` tool automatically uses correct UUIDs from the navigation tree.

### Best Practices

1. **Use AI Generation**: `generate_test_graph` handles UUIDs automatically
2. **Validate Early**: Errors caught at save time, not execution time
3. **Reference Navigation Tree**: Don't duplicate navigation logic in test cases
4. **Use Descriptive Labels**: Help humans understand the test flow

### Related Documentation

- **Navigation Autonomy**: See [mcp.md - Navigation Autonomy Concept](./README.md#navigation-autonomy-concept)
- **AI Generation**: See [mcp_tools_ai.md](mcp_tools_ai.md)
- **Navigation Tree**: See [mcp_tools_tree.md](mcp_tools_tree.md)
- **Detailed Analysis**: See `docs/LESSONS_LEARNED_testcase_validation.md`
