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

Start a test case (saved, by name, or an unsaved graph) and return its `execution_id` at once. The
tool does **not** wait for the run to end: read the result with `get_testcase_execution_status`.

**Parameters:**
```json
{
  "testcase_name": "My Test",            // REQUIRED - saved testcase name (or a label when graph_json is given)
  "host_name": "host1",                  // REQUIRED - from get_compatible_hosts
  "device_id": "device1",                // REQUIRED - from get_compatible_hosts
  "graph_json": {                        // Optional - unsaved graph from generate_test_graph
    "nodes": [...],
    "edges": [...],
    "scriptConfig": {...}
  },
  "userinterface_name": "example_mobile",  // Optional - defaults to the testcase's interface
  "team_id": "team_1"                    // Optional
}
```

**Returns:** `structuredContent` `{execution_id, kind: "testcase", status: "running", done: false, host_name, device_id, testcase_name}`.

---

#### get_testcase_execution_status

Read the state of a test case started by `execute_testcase` / `execute_testcase_by_id`. Waits up
to `wait_seconds` for the run to end, then answers. Call again while `done` is false.

REUSES `GET /server/testcase/execution/<id>/status` (same as the frontend).

**Parameters:**
```json
{
  "execution_id": "ex-123",              // REQUIRED - from execute_testcase
  "host_name": "host1",                  // REQUIRED - same host as execute_testcase
  "device_id": "device1",                // Optional
  "wait_seconds": 20,                    // Optional - default 20, max 50, 0 answers at once
  "team_id": "team_1"                    // Optional
}
```

**Returns:** the status shape below, plus `current_block_id` while running.

**Status shape** (`structuredContent`, same for both status tools):
```json
{
  "execution_id": "ex-123",
  "kind": "testcase",            // or "script"
  "status": "running",           // running | completed | failed | aborted | unknown
  "done": false,                 // true once status is completed, failed or aborted
  "passed": null,                // true/false once done; completed + false = the test ran and failed
  "report_url": null,
  "logs_url": null,
  "execution_time_ms": null,
  "error": null
}
```
- `unknown` means the status read itself timed out or got a 5xx. The run goes on: read again.
- `isError` is set only when the execution_id is unknown to the server (404). A test that ran and
  FAILED is a result (`completed`, `passed: false`), not a tool error.
- Each status call answers within `wait_seconds` (default 20, max 50), so no MCP request stays open
  longer than a proxy allows (a proxy such as Cloudflare answers 524 after 100 s).

**Example:**
```python
run = execute_testcase({
    "testcase_name": "Home Verification",
    "host_name": "host1",
    "device_id": "device1"
})
execution_id = run["structuredContent"]["execution_id"]

status = get_testcase_execution_status({"execution_id": execution_id, "host_name": "host1"})
while not status["structuredContent"]["done"]:
    status = get_testcase_execution_status({"execution_id": execution_id, "host_name": "host1"})
# status["structuredContent"]["passed"] -> True / False
```

---

#### execute_testcase_by_id

Deprecated wrapper: loads a saved test case by ID and starts it like `execute_testcase`.

**Parameters:**
```json
{
  "testcase_id": "tc-abc-123",           // REQUIRED
  "host_name": "host1",                  // REQUIRED
  "device_id": "device1",                // Optional
  "userinterface_name": "example_mobile",  // Optional - overrides testcase's interface
  "team_id": "team_1"                    // Optional
}
```

**Returns:** same as `execute_testcase` (the `execution_id` at once).

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
