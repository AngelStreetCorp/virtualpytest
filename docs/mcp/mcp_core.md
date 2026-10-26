# VirtualPyTest MCP Server

This page is the reference for the MCP server. It lets an AI assistant such as Claude or ChatGPT control your devices over a standard web connection.

The details below are for the people who set it up and build with it: tool names, settings, examples and error codes.

## Overview

<div data-technical>

**MCP (Model Context Protocol) Server** for VirtualPyTest enables external LLMs (Claude, ChatGPT, etc.) to control and automate physical devices through a standardized HTTP protocol.

**Endpoint**: `https://dev.virtualpytest.com/server/mcp`  
**Authentication**: Bearer token (required)  
**Transport**: HTTP/HTTPS

</div>

## Core Capabilities

<div data-technical>

The MCP server exposes **77 tools** for complete device automation:

</div>

### **Control Tools** (CRITICAL - MUST BE FIRST)

<div data-technical>

- **`take_control`** - Lock device & generate navigation cache (REQUIRED FIRST)

</div>

### **Action Tools**

<div data-technical>

- **`list_actions`** - List available actions for a device
- **`execute_device_action`** - Execute remote/ADB/web/desktop commands (async; MCP waits for completion)

</div>

### **Navigation Tools**

<div data-technical>

- **`list_navigation_nodes`** - List available navigation nodes in a tree
- **`navigate_to_node`** - Navigate through UI trees with pathfinding (async; MCP waits for completion)

</div>

### **Verification Tools**

<div data-technical>

- **`list_verifications`** - List available verification types for a device
- **`verify_device_state`** - Verify UI elements, video, text, ADB states (async; MCP waits for completion)

</div>

### **TestCase Tools**

<div data-technical>

- **`save_testcase`** - Save test case graph to database
- **`list_testcases`** - List all saved test cases
- **`load_testcase`** - Load saved test case by ID
- **`execute_testcase`** - Start a test case; returns its `execution_id` at once (does not wait)
- **`get_testcase_execution_status`** - Read a test case run; waits up to `wait_seconds` (max 50) for it to end
- **`execute_testcase_by_id`** - Load and start a saved test case in one call (deprecated wrapper)

</div>

### **Script Tools**

<div data-technical>

- **`list_scripts`** - List all available Python scripts
- **`execute_script`** - Start a Python script with CLI parameters; returns its `execution_id` at once (does not wait)
- **`get_script_execution_status`** - Read a script run; waits up to `wait_seconds` (max 50) for it to end

</div>

### **AI Tools**

<div data-technical>

- **`generate_test_graph`** - Generate tests from natural language (handles disambiguation)

</div>

### **Screenshot Tools**

<div data-technical>

- **`capture_screenshot`** - Capture screenshots for AI vision analysis (returns base64)

</div>

### **Transcript Tools**

<div data-technical>

- **`get_transcript`** - Transcript of a device for the last `minutes` (default 10, max 120) or an
  `hour` [+ `chunk_index`], and **why it is empty** when it is. `device_id` + `host_name` required.
  Returns a summary line + JSON: `status` (`ok` | `unavailable` | `empty` | `error`), `reason`,
  `message`, `transcription_enabled`, `service_active`, `audio`, `window`, `language`,
  `segments [{time, text}]`, `text`. `unavailable` = host not set up to transcribe
  (`service_inactive`, `transcription_disabled`); `empty` = nothing to transcribe
  (`no_audio_stream`, `silent_audio`, `no_speech`, `no_audio_recorded`, `processing_pending`);
  `error` = a real fault (`audio_status_missing`, `audio_check_stale`, `transcription_mode_unknown`,
  `mp3_missing`, `transcript_missing`, `host_not_found`, `host_unreachable`, `request_failed`) and is returned as an
  MCP error. Path: `/server/transcript/status` (auto proxy, `call_host()`) ->
  `/host/transcript/status` (`backend_host/src/lib/utils/transcript_status.py`). No translation
  (the former `target_language` never worked, BUG-0293).

</div>

### **Device & System Tools**

<div data-technical>

- **`get_device_info`** - Get device capabilities and status
- **`get_execution_status`** - Compatibility fallback status lookup for async executions
- **`list_services`** - List available systemd services
- **`view_logs`** - View systemd service logs via journalctl

</div>

### **Primitive Tools** (NEW - For AI-Driven Exploration)

<div data-technical>

- **`create_node`** - Create node in navigation tree
- **`update_node`** - Update node properties
- **`delete_node`** - Delete node from tree
- **`create_edge`** - Create edge with navigation actions
- **`update_edge`** - Update edge actions
- **`delete_edge`** - Delete edge from tree
- **`create_subtree`** - Create subtree for recursive exploration
- **`dump_ui_elements`** - Dump UI elements from current screen
- **`get_node`** - Get specific node by ID
- **`get_edge`** - Get specific edge by ID
- **`execute_edge`** - Execute edge actions directly (NEW)

</div>

### **UserInterface Management Tools** (NEW - For App Model Creation)

<div data-technical>

- **`create_userinterface`** - Create new app UI model (e.g., Netflix, YouTube)
- **`list_userinterfaces`** - List all app models for the team
- **`get_userinterface_complete`** - Get complete tree with all nodes/edges
- **`list_nodes`** - List all nodes in a navigation tree
- **`list_edges`** - List all edges in a navigation tree
- **`delete_userinterface`** - Delete a userinterface model

</div>

### **Node Verification Tools** (NEW)

<div data-technical>

- **`verify_node`** - Execute node verifications without navigation (NEW)

</div>

### **Requirements Management Tools** (NEW - Phase 2025-11)

<div data-technical>

- **`create_requirement`** - Create new requirement with app_type/device_model
- **`list_requirements`** - List all requirements with filters
- **`get_requirement`** - Get requirement details by ID
- **`update_requirement`** - Update requirement fields (app_type, device_model for reusability)
- **`link_testcase_to_requirement`** - Link testcase to requirement for coverage
- **`unlink_testcase_from_requirement`** - Unlink testcase from requirement
- **`get_testcase_requirements`** - Get all requirements linked to testcase
- **`get_requirement_coverage`** - Get coverage details for requirement
- **`get_coverage_summary`** - Get overall coverage metrics and breakdowns
- **`get_uncovered_requirements`** - Get requirements without test coverage

</div>

## MCP Integration Options

<div data-technical>

VirtualPyTest MCP tools can be accessed in **3 ways**:

</div>

### 1. **Cursor IDE (Native MCP)**

<div data-technical>

Direct integration via `~/.cursor/mcp.json` - Claude calls MCP tools directly.

</div>

### 2. **Claude Desktop / MCP Clients (Native MCP)**

<div data-technical>

Any MCP-compatible client that supports HTTP transport.

</div>

### 3. **MCP Playground (OpenRouter Function Calling)** NEW

<div data-technical>

Web interface using OpenRouter (Qwen/Phi-3) with function calling to simulate MCP.

</div>

## Prerequisites
### Important: Action Wait Times

<div data-technical>

All device actions require proper wait times to prevent timing issues and ensure reliable automation.

**Quick Reference:**
- App launch: 8000ms (8 seconds)
- Navigation/clicks: 2000ms (2 seconds)
- Back button: 1500ms (1.5 seconds)
- Text input: 1000ms (1 second)
- Video operations: 5000ms (5 seconds)

**Critical:** The `wait_time` field goes INSIDE `params`, NOT as top-level.

**See:** [Action Tools - Wait Time Guidelines](mcp_tools_action.md#⏱️-action-wait-time-guidelines) for complete standards and examples.

</div>

### Installation

<div data-technical>

```bash
cd backend_server
pip install -r requirements.txt
```

**Required packages:**
- `mcp>=1.0.0` - MCP protocol support
- `jsonschema>=4.0.0` - Input validation (NEW)
- `requests>=2.31.0` - HTTP client
- `flask>=2.3.0` - Web framework

</div>

### Security Configuration

<div data-technical>

**1. Generate a secure secret:**
```bash
python3 -c "import secrets; print(f'vpt_mcp_{secrets.token_urlsafe(32)}')"
```

**2. Add to project root `.env`:**
```bash
MCP_SECRET_KEY=<your-mcp-secret-key>
```

**3. Configure Cursor (`~/.cursor/mcp.json`):**
```json
{
  "mcpServers": {
    "virtualpytest": {
      "url": "https://dev.virtualpytest.com/server/mcp",
      "transport": {
        "type": "http"
      },
      "headers": {
        "Authorization": "Bearer <your-mcp-secret-key>"
      }
    }
  }
}
```

** Important:** Secret must match in both `.env` and `mcp.json`!

**4. Restart:**
- Restart backend_server (to load project root `.env`)
- Restart Cursor (Cmd+Q, reopen)

</div>

## Quick Start
### 1. Verify MCP Endpoint

<div data-technical>

The MCP server runs as an HTTP endpoint on your backend_server:

```bash
# Test health endpoint (requires auth)
curl -H "Authorization: Bearer <your-mcp-secret-key>" \
     https://dev.virtualpytest.com/server/mcp/health

# Expected response:
# {"status": "healthy", "mcp_version": "1.0.0", "tools_count": 75}
```

</div>

### 2. Discover Available Commands (NEW!)

<div data-technical>

Before executing commands, discover what's available on your device:

```python
# Step 0: Take control first (ALWAYS REQUIRED)
take_control({
    "tree_id": "main_navigation",
    "device_id": "device1",
    "host_name": "host1"
})

# Step 1: Discover available actions
list_actions({
    "device_id": "device1",
    "host_name": "host1"
})
# Returns: Categorized list (remote, adb, web, desktop) with commands & params

# Step 2: Discover available verifications
list_verifications({
    "device_id": "device1",
    "host_name": "host1"
})
# Returns: Categorized list (image, text, adb, video) with methods & params

# Step 3: Discover available navigation nodes
list_navigation_nodes({
    "tree_id": "main_navigation"
})
# Returns: List of nodes with labels, IDs, types, positions

# Now you know exactly what commands/verifications/nodes are available!
```

</div>

### 3. Example LLM Workflow (via Cursor)

<div data-technical>

**Simplified workflow with discovery:**
```python
# Step 1: ALWAYS take control first
take_control({
    "tree_id": "main_navigation"  # Uses default host/device/team
})

# Step 2: Discover what's available (optional but recommended)
actions = list_actions({})  # Uses defaults
nodes = list_navigation_nodes({"tree_id": "main_navigation"})

# Step 3: Execute commands
execute_device_action({
    "actions": [
        {"command": "swipe_up", "params": {}, "delay": 500}
    ]
})
# Returns: execution_id; MCP waits until completion

# Step 4: Navigate to target
navigate_to_node({
    "tree_id": "main_navigation",
    "userinterface_name": "example_mobile",
    "target_node_label": "home_saved"
})
# Returns: Success with path taken after async completion

# Step 5: Verify element exists
verify_device_state({
    "userinterface_name": "example_mobile",
    "verifications": [{
        "command": "waitForElementToAppear",
        "params": {"search_term": "Replay", "timeout": 5000},
        "verification_type": "adb"
    }]
})
# Returns: Verification results (passed/failed)

# Step 6: Capture screenshot for vision analysis
capture_screenshot({})  # All params optional with defaults
# Returns: base64 image for AI vision

# Step 7: Release control when done (ALWAYS!)
release_control({})  # Uses default host/device/team
```

**Using defaults (recommended):**
```python
# All parameters are optional if using defaults:
# - device_id: 'device1'
# - host_name: 'host1'  
# - team_id: 'team_1'

take_control({"tree_id": "main_navigation"})
list_actions({})
execute_device_action({"actions": [...]})
navigate_to_node({"tree_id": "...", "userinterface_name": "...", "target_node_label": "..."})
verify_device_state({"userinterface_name": "...", "verifications": [...]})
release_control({})
```

</div>

## Smart Defaults & Configuration
### Default Values (NEW in 2025)

<div data-technical>

The MCP server now provides smart defaults for common parameters, making tool calls more convenient:

```python
# Defaults from shared/src/lib/config/constants.py
DEFAULT_TEAM_ID = os.getenv('DEFAULT_TEAM_ID', 'team_1')
DEFAULT_HOST_NAME = os.getenv('DEFAULT_HOST_NAME', 'host1')
DEFAULT_DEVICE_ID = os.getenv('DEFAULT_DEVICE_ID', 'device_1')
```

</div>

### Optional Parameters

<div data-technical>

These parameters are now **optional** in most tool calls:
- `team_id` (defaults to `team_1` or `$DEFAULT_TEAM_ID`)
- `host_name` (defaults to `host1` or `$DEFAULT_HOST_NAME`)
- `device_id` (defaults to `device_1` or `$DEFAULT_DEVICE_ID`)

</div>

### Example: Simplified Tool Calls

<div data-technical>

**Before (verbose):**
```python
take_control({
    "host_name": "host1",
    "device_id": "device_1",
    "team_id": "team_1",
    "tree_id": "main_navigation"
})
```

**After (concise with defaults):**
```python
take_control({
    "tree_id": "main_navigation"  # Other params use defaults
})
```

</div>

### Custom Defaults

<div data-technical>

Override defaults via environment variables:

```bash
# .env (project root)
DEFAULT_TEAM_ID=my_team
DEFAULT_HOST_NAME=my_host
DEFAULT_DEVICE_ID=my_device
```

</div>

## Input Validation
### JSON Schema Validation (NEW)

<div data-technical>

All tool inputs are validated against JSON Schema **before** execution:

**Benefits:**
-  Invalid data rejected immediately
-  Clear validation error messages
-  Type safety (string, integer, boolean, etc.)
-  Required field enforcement
-  Array/object structure validation

**Example Validation Error:**
```json
{
  "content": [{
    "type": "text",
    "text": "Validation failed for take_control: 'tree_id' must be string, got integer"
  }],
  "isError": true
}
```

</div>

### Error Categories

<div data-technical>

The MCP server categorizes errors for better handling:

```python
class ErrorCategory(str, Enum):
    VALIDATION = "validation"      # Invalid input (jsonschema)
    TIMEOUT = "timeout"            # Request timeout
    NETWORK = "network"            # Network error
    BACKEND = "backend"            # Backend API error
    NOT_FOUND = "not_found"        # Resource not found
    UNAUTHORIZED = "unauthorized"   # Auth failure
    UNKNOWN = "unknown"            # Unexpected error
```

**Example Error Response:**
```json
{
  "content": [{
    "type": "text",
    "text": "Error: Device not found"
  }],
  "isError": true,
  "_error_category": "not_found",
  "_error_details": {
    "device_id": "invalid_device",
    "host_name": "host1"
  }
}
```

</div>

## Async Execution Completion

<div data-technical>

Actions, navigation and verifications are short: their tools wait for the end of the run.

Test cases and scripts can run for minutes or hours, so their tools return an `execution_id` at
once and a status tool reads the run. A single MCP call never stays open for a whole run, which a
proxy in front of the server would cut off (Cloudflare answers 524 after 100 s).

```python
run = execute_testcase({"testcase_name": "Home Verification", "host_name": "host1", "device_id": "device1"})
execution_id = run["structuredContent"]["execution_id"]

status = get_testcase_execution_status({"execution_id": execution_id, "host_name": "host1"})
while not status["structuredContent"]["done"]:      # each call waits up to wait_seconds (default 20, max 50)
    status = get_testcase_execution_status({"execution_id": execution_id, "host_name": "host1"})

status["structuredContent"]["status"]   # completed | failed | aborted
status["structuredContent"]["passed"]   # True / False
```

Scripts: `execute_script` + `get_script_execution_status({"execution_id": ...})`, same shape.
Status shape and rules: [TestCase Tools](mcp_tools_testcase.md#get_testcase_execution_status).

`get_execution_status` remains for other async operations (`operation_type`: `action`, `ai`).

</div>

## Architecture

<div data-technical>

```
backend_server/src/mcp/
├── mcp_server.py          # Main MCP server (synchronous)
├── tools/
│   ├── control_tools.py   # take_control, release_control
│   ├── action_tools.py    # execute_device_action, list_actions
│   ├── navigation_tools.py # navigate_to_node, list_navigation_nodes
│   ├── verification_tools.py # verify_device_state, list_verifications, dump_ui_elements
│   ├── testcase_tools.py  # execute_testcase, save/load/list testcases
│   ├── ai_tools.py        # generate_test_graph
│   ├── screenshot_tools.py # capture_screenshot
│   ├── transcript_tools.py # get_transcript
│   ├── device_tools.py    # get_device_info, get_execution_status
│   ├── logs_tools.py      # view_logs, list_services
│   ├── script_tools.py    # execute_script
│   ├── tree_tools.py      # create/update/delete node/edge, create_subtree (NEW)
│   └── userinterface_tools.py # create/list/delete userinterface, list_nodes/edges (NEW)
├── config/
│   └── tools_config.json  # Tool definitions & schemas
└── utils/
    ├── api_client.py      # Reusable HTTP client (raw responses)
    ├── mcp_formatter.py   # MCP response formatting (7 error categories)
    └── input_validator.py # JSON Schema validation
```

</div>

### Architecture Principles (2025 Update)

<div data-technical>

** Clean Separation of Concerns:**
- **API Client** - Returns raw responses, reusable outside MCP
- **MCPFormatter** - Converts raw responses to MCP format
- **InputValidator** - Validates all inputs against JSON Schema
- **Tool Classes** - Pure business logic, minimal boilerplate

** Production-Ready Quality:**
- **Synchronous Execution** - No asyncio overhead
- **Input Validation** - All parameters validated before execution
- **Error Categorization** - 7 error types (validation, timeout, network, backend, not_found, unauthorized, unknown)
- **Smart Defaults** - Optional `team_id`, `host_name`, `device_id` with sensible fallbacks
- **No Legacy Code** - Clean implementation, no backward compatibility cruft

** Composable Primitives (v4.0.0):**
- **Stateless Tools** - No complex state management
- **Atomic Operations** - Each tool does ONE thing
- **LLM Orchestration** - LLM decides workflow, not hardcoded
- **Reusable Everywhere** - Same primitives for exploration, debugging, refactoring

</div>

## Architecture & API Flow
### HTTP MCP Architecture

<div data-technical>

```
Cursor (Your Mac)
    ↓ HTTPS with Bearer token
https://dev.virtualpytest.com/server/mcp  (HTTP endpoint)
    ↓ Local calls
Backend Server routes
    ↓ SSH/HTTP
Backend Host (remote)
    ↓
Physical Devices
```

</div>

### API Flow Example

<div data-technical>

```
1. Cursor makes HTTP POST request:
   POST https://dev.virtualpytest.com/server/mcp
   Headers: Authorization: Bearer <token>
   Body: {
     "tool": "take_control",
     "params": {
       "host_name": "ubuntu-host-1",
       "device_id": "device1",
       "team_id": "team_abc123",
       "tree_id": "main_navigation"
     }
   }

2. MCP endpoint validates Bearer token

3. Calls: POST /server/control/takeControl

4. Backend locks device + generates cache

5. Returns: {
     "content": [{
       "type": "text",
       "text": "{\"session_id\": \"xyz\", \"cache_ready\": true}"
     }]
   }
```

</div>

## Security
### Bearer Token Authentication

<div data-technical>

All MCP endpoints require Bearer token authentication:

```bash
Authorization: Bearer <your_secret_key>
```

**How It Works:**

1. **Generate random token** (cryptographically secure random string):
   ```bash
   python3 -c "import secrets; print(f'vpt_mcp_{secrets.token_urlsafe(32)}')"
   ```

2. **Store in both places:**
   - Backend: `MCP_SECRET_KEY` in `.env`
   - Cursor: `Authorization: Bearer <token>` in `mcp.json`

3. **Validation is simple string comparison:**
   ```
   Cursor sends: Authorization: Bearer vpt_mcp_abc123...
   Backend reads token from header
   Backend compares: received_token == MCP_SECRET_KEY
   If match → Allow ✅
   If not → 403 Forbidden ❌
   ```

No encryption, no JWT, no database - just a **shared secret** with HTTPS transport security.

</div>

### Security Features

<div data-technical>

 **Bearer Token Required** - All endpoints protected  
 **Environment Variable** - Secret stored in `.env`, not hardcoded  
 **401 Unauthorized** - Missing auth header  
 **403 Forbidden** - Invalid token  
 **Team-based Access** - All operations require `team_id`  
 **Device Locking** - Prevents concurrent access  
 **Session Tracking** - Audit trail for all operations  

</div>

### Protected Endpoints

<div data-technical>

- `POST /mcp` - Tool execution
- `GET /mcp/tools` - List available tools
- `GET /mcp/health` - Health check

</div>

### Rotating Secrets

<div data-technical>

```bash
# 1. Generate new secret
python3 -c "import secrets; print(f'vpt_mcp_{secrets.token_urlsafe(32)}')"

# 2. Update project root .env
MCP_SECRET_KEY=<new_secret>

# 3. Restart backend_server

# 4. Update ~/.cursor/mcp.json
"Authorization": "Bearer <new_secret>"

# 5. Restart Cursor
```

</div>

### Best Practices

<div data-technical>

1.  **Never commit secrets** to git
2.  **Use strong random secrets** (32+ characters)
3.  **Different secrets per environment** (dev/prod)
4.  **Rotate secrets periodically** (every 90 days)
5.  **Keep Cursor config local** (~/.cursor/mcp.json is not synced)

</div>

## Monitoring

<div data-technical>

MCP server logs all operations:

```bash
tail -f mcp_server.log
```

Available tools on startup:
```
[INFO] VirtualPyTest MCP Server initialized with 75 tools
[INFO] Available tools:
  - take_control: Lock device and generate cache
  - release_control: Release device lock
  - execute_device_action: Execute commands
  - create_node: Create node in navigation tree
  - dump_ui_elements: Dump UI elements from screen
  - create_requirement: Create requirement with app_type/device_model
  - update_requirement: Update requirement fields for reusability
  ...
```

</div>

## Troubleshooting
### Authentication Errors

<div data-technical>

**"Missing Authorization header"**
- Add `headers` section to Cursor MCP config
- Ensure Bearer token is included
- Format: `Authorization: Bearer <token>`

**"Invalid MCP authentication token"**
- Check secret matches in both `.env` and `mcp.json`
- Restart backend_server after changing project root `.env`
- Restart Cursor after changing `mcp.json`

**"Invalid Authorization header format"**
- Ensure format is: `Bearer <token>` (space after "Bearer")
- Check for extra spaces or newlines

</div>

### MCP Tools Not Showing in Cursor

<div data-technical>

- Restart Cursor completely (Cmd+Q, then reopen)
- Check `~/.cursor/mcp.json` exists and is valid JSON
- Verify URL is correct: `https://dev.virtualpytest.com/server/mcp`
- Test health endpoint manually with curl

</div>

### Device Operation Errors

<div data-technical>

**"Device not found"**
- Ensure `take_control` was called first
- Check device_id is correct
- Verify host is registered

**"Cache not ready"**
- Call `take_control` with `tree_id` parameter
- Wait for `cache_ready: true` response

**"Device locked by another session"**
- Another user/LLM has control
- Wait for release or use different device

</div>

## Complete Example

<div data-technical>

```python
# Full automation workflow
from mcp_client import MCPClient

client = MCPClient()

# 1. Take control (CRITICAL FIRST STEP)
control = client.call_tool("take_control", {
    "host_name": "ubuntu-host-1",
    "device_id": "device1",
    "team_id": "team_abc123",
    "tree_id": "main_navigation"
})
print(f"Control acquired: {control['session_id']}")

# 2. Navigate to target
nav = client.call_tool("navigate_to_node", {
    "tree_id": "main_navigation",
    "userinterface_name": "example_androidtv",
    "target_node_label": "Settings",
    "device_id": "device1",
    "team_id": "team_abc123"
})
print(f"Navigation: {nav['message']}")

# 3. Capture screenshot for vision
screenshot = client.call_tool("capture_screenshot", {
    "device_id": "device1",
    "team_id": "team_abc123"
})
image_base64 = screenshot['screenshot_base64']

# 4. Analyze screenshot with vision AI
# (Use image_base64 with Claude/GPT-4V)

# 5. Execute verification
verify = client.call_tool("verify_device_state", {
    "device_id": "device1",
    "team_id": "team_abc123",
    "userinterface_name": "example_androidtv",
    "verifications": [
        {
            "type": "image",
            "method": "DetectReference",
            "params": {"reference_id": "settings_icon"},
            "expected": True
        }
    ]
})
print(f"Verification: {verify['results']}")

# 6. Release control (ALWAYS AT END)
client.call_tool("release_control", {
    "host_name": "ubuntu-host-1",
    "device_id": "device1",
    "team_id": "team_abc123"
})
print("Control released")

</div>
