# Testcase Graph JSON Template

## Overview

This document defines the **graph_json** structure used for creating test cases in VirtualPyTest. Test cases are represented as directed graphs with nodes (blocks) and edges (transitions), following a Blockly-style visual programming model.

## Core Structure

```json
{
  "nodes": [...],
  "edges": [...],
  "scriptConfig": {...}
}
```

---

## 1. Nodes Array

Each node represents a block in the test case flow. All test cases must have:
- **start node** - Entry point
- **success node** - Test passed endpoint
- **failure node** - Test failed endpoint (optional but recommended)
- **functional nodes** - Navigation, verification, action, or condition blocks

### Node Types

#### Start Node (Required)
```json
{
  "id": "start",
  "type": "start",
  "data": {},
  "position": {"x": 0, "y": 0}
}
```

#### Success Node (Required)
```json
{
  "id": "success",
  "type": "success",
  "data": {},
  "position": {"x": 100, "y": 600}
}
```

#### Failure Node (Optional)
```json
{
  "id": "failure",
  "type": "failure",
  "data": {},
  "position": {"x": 300, "y": 600}
}
```

#### Navigation Block
Navigates to a specific node in the navigation tree.

```json
{
  "id": "uuid-here",
  "type": "navigation",
  "data": {
    "label": "GotoHome",
    "block_label": "navigation_1:home",
    "target_node_id": "node-uuid-from-tree",
    "target_node_label": "home"
  },
  "position": {"x": 0, "y": 100}
}
```

**Fields:**
- `label`: Display name for the block
- `block_label`: Format `navigation_N:node_label` where N is sequence number
- `target_node_id`: UUID of the node in navigation tree (from create_node or list_navigation_nodes)
- `target_node_label`: String label of the target node (e.g., "home", "search")

#### Verification Block
Executes verification commands (ADB, web, OCR, image).

```json
{
  "id": "uuid-here",
  "type": "verification",
  "data": {
    "label": "VerifyHomeScreen",
    "command": "waitForElementToAppear",
    "action_type": "verification",
    "verification_type": "adb",
    "params": {
      "element_id": "Home",
      "timeout": 5000
    },
    "blockOutputs": [
      {
        "name": "result",
        "type": "boolean",
        "description": "Verification result"
      }
    ]
  },
  "position": {"x": 0, "y": 200}
}
```

**Common verification_type values:**
- `adb` - Android ADB verifications (waitForElementToAppear, check_text_on_screen, getMenuInfo)
- `web` - Web element verifications
- `text` - OCR text verifications
- `image` - Image comparison verifications

**Common commands:**
- `waitForElementToAppear` - Wait for element with element_id or text
- `check_text_on_screen` - Check if text exists on screen
- `getMenuInfo` - Extract UI element information

#### Action Block
Executes device actions (click, swipe, type, etc.).

```json
{
  "id": "uuid-here",
  "type": "action",
  "data": {
    "label": "ClickSearchTab",
    "command": "click_element",
    "action_type": "adb",
    "params": {
      "element_id": "Search",
      "wait_time": 2000
    }
  },
  "position": {"x": 0, "y": 300}
}
```

**Common action_type values:**
- `adb` - Android ADB actions
- `remote` - IR remote actions
- `web` - Web automation actions
- `standard_block` - Built-in actions (wait, condition evaluation)

**Common commands:**
- `click_element` - Click on element by element_id
- `type_text` - Type text into input field
- `press_key` - Press Android key (BACK, HOME, etc.)
- `swipe_up` / `swipe_down` - Swipe gestures
- `wait` - Wait for specified time

#### Condition Block (Evaluate)
Evaluates conditions to create branching logic.

```json
{
  "id": "uuid-here",
  "type": "evaluate_condition",
  "data": {
    "label": "CheckDeviceType",
    "command": "evaluate_condition",
    "action_type": "standard_block",
    "params": {
      "condition": "equal",
      "left_operand": "{device_model_name}",
      "operand_type": "str",
      "right_operand": "android_mobile"
    }
  },
  "position": {"x": 0, "y": 150}
}
```

**Condition types:**
- `equal` - Left equals right
- `greater_than` - Left > right
- `less_than` - Left < right
- `greater_equal` - Left >= right
- `less_equal` - Left <= right

---

## 2. Edges Array

Edges connect nodes and define the execution flow.

### Edge Types

#### Success Edge
Connect blocks on successful execution.

```json
{
  "id": "uuid-here",
  "type": "success",
  "source": "source-node-id",
  "target": "target-node-id",
  "sourceHandle": "success"
}
```

#### Failure Edge
Connect blocks on failed execution (from verifications or conditions).

```json
{
  "id": "uuid-here",
  "type": "failure",
  "source": "source-node-id",
  "target": "target-node-id",
  "sourceHandle": "failure"
}
```

### Common Source Handles
- `success` - Standard success output
- `failure` - Standard failure output
- `success-hitarea` - For start node

---

## 3. Script Config

Configuration for the test case execution.

```json
{
  "scriptConfig": {
    "inputs": [
      {
        "name": "device_model_name",
        "type": "string",
        "default": "android_mobile",
        "required": true,
        "protected": true
      },
      {
        "name": "host_name",
        "type": "string",
        "default": "host1",
        "required": true,
        "protected": true
      },
      {
        "name": "device_name",
        "type": "string",
        "default": "device1",
        "required": true,
        "protected": true
      },
      {
        "name": "userinterface_name",
        "type": "string",
        "default": "netflix_mobile",
        "required": true,
        "protected": true
      }
    ],
    "outputs": [],
    "metadata": {
      "mode": "append",
      "fields": []
    },
    "variables": []
  }
}
```

**Required inputs:**
- `device_model_name`: Device type (android_mobile, android_tv, web, host_vnc)
- `host_name`: Host where device is connected (e.g., host1)
- `device_name`: Device identifier (e.g., device1)
- `userinterface_name`: UI model name (e.g., netflix_mobile)

**Variables:** Define reusable variables that can store block outputs and be referenced as `{variable_name}` in params.

---

## 4. Complete Example: Simple Navigation Test

```json
{
  "nodes": [
    {
      "id": "start",
      "type": "start",
      "data": {},
      "position": {"x": 0, "y": 0}
    },
    {
      "id": "nav-to-home",
      "type": "navigation",
      "data": {
        "label": "NavigateToHome",
        "block_label": "navigation_1:home",
        "target_node_id": "home-node-uuid",
        "target_node_label": "home"
      },
      "position": {"x": 0, "y": 100}
    },
    {
      "id": "verify-home",
      "type": "verification",
      "data": {
        "label": "VerifyHomeScreen",
        "command": "waitForElementToAppear",
        "action_type": "verification",
        "verification_type": "adb",
        "params": {
          "element_id": "Home",
          "timeout": 5000
        }
      },
      "position": {"x": 0, "y": 200}
    },
    {
      "id": "success",
      "type": "success",
      "data": {},
      "position": {"x": 0, "y": 300}
    },
    {
      "id": "failure",
      "type": "failure",
      "data": {},
      "position": {"x": 200, "y": 300}
    }
  ],
  "edges": [
    {
      "id": "edge-start-nav",
      "type": "success",
      "source": "start",
      "target": "nav-to-home",
      "sourceHandle": "success-hitarea"
    },
    {
      "id": "edge-nav-verify",
      "type": "success",
      "source": "nav-to-home",
      "target": "verify-home",
      "sourceHandle": "success"
    },
    {
      "id": "edge-verify-success",
      "type": "success",
      "source": "verify-home",
      "target": "success",
      "sourceHandle": "success"
    },
    {
      "id": "edge-verify-failure",
      "type": "failure",
      "source": "verify-home",
      "target": "failure",
      "sourceHandle": "failure"
    }
  ],
  "scriptConfig": {
    "inputs": [
      {
        "name": "device_model_name",
        "type": "string",
        "default": "android_mobile",
        "required": true,
        "protected": true
      },
      {
        "name": "host_name",
        "type": "string",
        "default": "host1",
        "required": true,
        "protected": true
      },
      {
        "name": "device_name",
        "type": "string",
        "default": "device1",
        "required": true,
        "protected": true
      },
      {
        "name": "userinterface_name",
        "type": "string",
        "default": "netflix_mobile",
        "required": true,
        "protected": true
      }
    ],
    "outputs": [],
    "metadata": {
      "mode": "append",
      "fields": []
    },
    "variables": []
  }
}
```

---

## 5. Best Practices

### Testcase Naming and Reusability (CRITICAL)

**KEY CONCEPT**: The userinterface model (navigation tree) is what makes testcases reusable across different apps.

#### Generic vs App-Specific Testcases

**✅ GENERIC Testcases** (Reusable across apps with same structure):
- Use **generic names and descriptions** that apply to any app
- Reference generic node labels (home, search, content_detail, player)
- Examples:
  - `BasicVideoPlayback` - "Navigate from home to player and verify video starts"
  - `MainTabNavigation` - "Navigate through all main tabs and verify each screen"
  - `ContentSearch` - "Search for content and verify results appear"
  - `BackButtonNavigation` - "Verify back button works from multiple screens"

**❌ APP-SPECIFIC Testcases** (Only for unique features):
- Use app-specific names only when the functionality is unique to that app
- Examples:
  - `NetflixProfileSwitch` - "Switch between Netflix profiles"
  - `YouTubeMiniPlayer` - "Verify YouTube mini-player functionality"
  - `NetflixDownloadManagement` - "Manage downloaded content in Netflix"

#### How Reusability Works

1. **Same testcase graph_json** can run on different apps (Netflix, YouTube, Hulu)
2. **Only change**: `userinterface_name` in scriptConfig
3. **Navigation tree** for each app defines app-specific navigation paths
4. **Generic node labels** (home, search, player) map to different screens per app

**Example**: `BasicVideoPlayback` testcase
- **Netflix**: home → content_detail → player (navigates using Netflix UI elements)
- **YouTube**: home → content_detail → player (navigates using YouTube UI elements)
- **Hulu**: home → content_detail → player (navigates using Hulu UI elements)
- **Same testcase, different userinterface_name, different navigation tree**

#### Naming Convention

**Format**: `[Category]_[Number]_[GenericAction]`

Examples:
- `Playback_001_BasicVideoPlayback` ✅ (generic)
- `Nav_001_MainTabNavigation` ✅ (generic)
- `Search_001_ContentSearch` ✅ (generic)
- `Netflix_Playback_001_NetflixVideoPlayback` ❌ (unnecessarily app-specific)

**Description Format**: Generic, no app names unless truly app-specific
- ✅ "Navigate from home to player and verify video starts"
- ❌ "Navigate Netflix home to Netflix player and play Netflix video"

### Node IDs
- Use UUID v4 for all functional nodes
- Reserved IDs: `start`, `success`, `failure`

### Positioning
- Start at (0, 0) for start node
- Space nodes vertically by ~100-150px
- Place success/failure nodes at bottom with similar Y coordinates

### Labels
- Use descriptive labels for clarity: "NavigateToSearchTab" not "nav1"
- block_label format: `navigation_N:target` or `verification_N` or `action_N`

### Error Handling
- Always connect failure paths from verifications and conditions
- Route failures to either retry logic or failure node
- Use failure node to mark test as failed

### Navigation Blocks
- **CRITICAL**: Use `target_node_label` that matches the node label from your navigation tree (e.g., "home", "search", "content_detail")
- **CRITICAL**: Use `target_node_id` that matches the database UUID from `list_navigation_nodes()` for the node
- The navigation block will use the navigation tree's edges to pathfind to the target
- Verifications embedded in nodes will execute automatically during navigation

### Action vs Navigation
- Use **navigation blocks** when moving between screens defined in the navigation tree
- Use **action blocks** for one-off actions not part of navigation (e.g., pause video, scroll)
- Navigation blocks leverage the tree's edges and verifications
- Action blocks execute raw commands without tree context

### Verification Placement
- Add verifications after navigation to confirm arrival
- Add verifications after actions to confirm state changes
- Set appropriate timeouts (5000ms for screens, 10000ms for slow operations)

---

## 6. Netflix Android Mobile Example

For a test that navigates home → search → content_detail:

```json
{
  "nodes": [
    {
      "id": "start",
      "type": "start",
      "data": {},
      "position": {"x": 0, "y": 0}
    },
    {
      "id": "nav-home",
      "type": "navigation",
      "data": {
        "label": "NavigateToHome",
        "block_label": "navigation_1:home",
        "target_node_id": "home-uuid-from-tree",
        "target_node_label": "home"
      },
      "position": {"x": 0, "y": 100}
    },
    {
      "id": "nav-search",
      "type": "navigation",
      "data": {
        "label": "NavigateToSearch",
        "block_label": "navigation_2:search",
        "target_node_id": "search-uuid-from-tree",
        "target_node_label": "search"
      },
      "position": {"x": 0, "y": 200}
    },
    {
      "id": "action-type-search",
      "type": "action",
      "data": {
        "label": "TypeSearchQuery",
        "command": "type_text",
        "action_type": "adb",
        "params": {
          "text": "Stranger Things",
          "wait_time": 1000
        }
      },
      "position": {"x": 0, "y": 300}
    },
    {
      "id": "action-click-result",
      "type": "action",
      "data": {
        "label": "ClickFirstResult",
        "command": "click_element",
        "action_type": "adb",
        "params": {
          "element_id": "Search Result 1",
          "wait_time": 2000
        }
      },
      "position": {"x": 0, "y": 400}
    },
    {
      "id": "verify-content-detail",
      "type": "verification",
      "data": {
        "label": "VerifyContentDetailLoaded",
        "command": "waitForElementToAppear",
        "action_type": "verification",
        "verification_type": "adb",
        "params": {
          "element_id": "Play",
          "timeout": 5000
        }
      },
      "position": {"x": 0, "y": 500}
    },
    {
      "id": "success",
      "type": "success",
      "data": {},
      "position": {"x": 0, "y": 600}
    },
    {
      "id": "failure",
      "type": "failure",
      "data": {},
      "position": {"x": 200, "y": 600}
    }
  ],
  "edges": [
    {"id": "e1", "type": "success", "source": "start", "target": "nav-home", "sourceHandle": "success-hitarea"},
    {"id": "e2", "type": "success", "source": "nav-home", "target": "nav-search", "sourceHandle": "success"},
    {"id": "e3", "type": "success", "source": "nav-search", "target": "action-type-search", "sourceHandle": "success"},
    {"id": "e4", "type": "success", "source": "action-type-search", "target": "action-click-result", "sourceHandle": "success"},
    {"id": "e5", "type": "success", "source": "action-click-result", "target": "verify-content-detail", "sourceHandle": "success"},
    {"id": "e6", "type": "success", "source": "verify-content-detail", "target": "success", "sourceHandle": "success"},
    {"id": "e7", "type": "failure", "source": "verify-content-detail", "target": "failure", "sourceHandle": "failure"}
  ],
  "scriptConfig": {
    "inputs": [
      {"name": "device_model_name", "type": "string", "default": "android_mobile", "required": true, "protected": true},
      {"name": "host_name", "type": "string", "default": "host1", "required": true, "protected": true},
      {"name": "device_name", "type": "string", "default": "device1", "required": true, "protected": true},
      {"name": "userinterface_name", "type": "string", "default": "netflix_mobile", "required": true, "protected": true}
    ],
    "outputs": [],
    "metadata": {"mode": "append", "fields": []},
    "variables": []
  }
}
```

---

## 7. Summary Checklist

When creating graph_json manually:

- ✅ Include `start`, `success`, and `failure` nodes
- ✅ Use UUID v4 for all functional node IDs
- ✅ Use correct node `type` (navigation, verification, action, evaluate_condition)
- ✅ Set `target_node_label` in navigation blocks to match tree node labels
- ✅ Use actual `element_id` values from UI dump in verification/action params
- ✅ Connect all nodes with edges (success/failure paths)
- ✅ Include `scriptConfig` with required inputs
- ✅ Set reasonable position coordinates for visual layout
- ✅ Use descriptive labels for readability
- ✅ Route failure edges from verifications to failure node or retry logic

---

## 8. Common Mistakes to Avoid

❌ **Using generate_test_graph** - Always construct graph_json manually
❌ **Missing start/success/failure nodes** - All three are required
❌ **Wrong target_node_label** - Must exactly match navigation tree node labels
❌ **Guessing element_ids** - Always use dump_ui_elements to get real IDs
❌ **Forgetting failure edges** - Verifications need both success and failure paths
❌ **Wrong verification_type** - Use "adb" for android_mobile, not "remote" or "web"
❌ **Missing scriptConfig inputs** - All 4 required inputs must be present
❌ **Reusing node IDs** - Each functional node needs a unique UUID

---

This template is the authoritative reference for manually constructing test case graphs in VirtualPyTest.

