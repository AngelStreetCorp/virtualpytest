# MCP Action Tools

[← Back to MCP Documentation](./README.md)

---

## 🛠️ Tool Reference

### 🔍 Discovery Tools (NEW!)

#### list_actions

List all available actions for a device (categorized by type).

**Parameters:**
```json
{
  "device_id": "device1",        // Optional (defaults to 'device1')
  "host_name": "host1",      // REQUIRED
  "team_id": "team_1"            // Optional (defaults to 'team_1')
}
```

**Returns:**
```json
{
  "device_action_types": {
    "remote": [
      {
        "id": "KEY_HOME",
        "label": "Home Button",
        "command": "KEY_HOME",
        "params": {},
        "description": "Press home button"
      }
    ],
    "adb": [
      {
        "id": "swipe_up",
        "label": "Swipe Up",
        "command": "swipe_up",
        "params": {"distance": 500},
        "description": "Swipe up gesture"
      }
    ],
    "web": [...],
    "desktop": [...]
  },
  "device_model": "Android TV"
}
```

**Use Case:** Discover what actions can be executed before calling `execute_device_action`.

---

#### list_verifications

List all available verification types for a device.

**Parameters:**
```json
{
  "device_id": "device1",        // Optional (defaults to 'device1')
  "host_name": "host1",      // REQUIRED
  "team_id": "team_1"            // Optional (defaults to 'team_1')
}
```

**Returns:**
```json
{
  "device_verification_types": {
    "adb": [
      {
        "command": "waitForElementToAppear",
        "label": "Wait for Element to Appear",
        "params": {
          "search_term": {"type": "string", "required": true},
          "timeout": {"type": "number", "required": false}
        },
        "description": "Wait for UI element to appear",
        "verification_type": "adb"
      }
    ],
    "image": [...],
    "text": [...],
    "video": [...]
  },
  "device_model": "Android TV"
}
```

**Use Case:** Discover what verifications can be performed before calling `verify_device_state`.

---

#### list_navigation_nodes

List all available navigation nodes in a tree.

**Parameters:**
```json
{
  "tree_id": "main_navigation",  // REQUIRED
  "team_id": "team_1",           // Optional (defaults to 'team_1')
  "page": 0,                     // Optional (default: 0)
  "limit": 100                   // Optional (default: 100)
}
```

**Returns:**
```json
{
  "nodes": [
    {
      "id": "node-123",
      "label": "home_saved",
      "type": "screen",
      "position": {"x": 100, "y": 200}
    },
    {
      "id": "node-456",
      "label": "settings",
      "type": "screen",
      "position": {"x": 300, "y": 200}
    }
  ],
  "total": 42
}
```

**Use Case:** Discover available navigation targets before calling `navigate_to_node`.

---

### 🎮 Action Execution

#### execute_device_action

Execute batch of actions on device (remote commands, ADB, web, desktop).
Automatically acquires and releases device lock.

**Locking behavior:**
- If no lock is held: auto-acquires lock before execution, auto-releases after
- If `take_control()` was called first: piggybacks on the existing manual lock (no conflict)
- On failure: error messages now include per-action details (e.g., `"❌ 0/1 failed: navigate_to_url: Connection refused"`)

**Executes direct device commands including:**
- 🚀 **Launch apps** (`launch_app`)
- 📱 **UI interactions** (swipe, click, type)
- 🔑 **Key presses** (`press_key`)
- And more...

**Parameters:**
```json
{
  "device_id": "device1",
  "actions": [
    {"command": "KEY_HOME", "params": {}, "delay": 500},
    {"command": "swipe_up", "params": {"distance": 300}, "delay": 300}
  ],
  "retry_actions": [],          // Optional: Actions to retry on failure
  "failure_actions": [],        // Optional: Actions to execute on failure
  "team_id": "team_1",          // Optional (defaults to 'team_1')
  "include_screenshot": false   // Optional (default false) - set true to embed a screenshot of the resulting screen
}
```

**Returns:** `execution_id`; MCP waits for async completion before returning. When
`include_screenshot: true` is passed, the completed response also includes an **inline
screenshot** of the resulting screen (a base64 `{type:"image"}` content block), on both pass
and fail, so the model can see the outcome (useful to diagnose *why* an action failed). It is
**off by default**; a failed screenshot capture never blocks the action result.

**Common Examples:**

**🚀 Launch App:**
```python
execute_device_action({
    "device_id": "device1",
    "actions": [{
        "command": "launch_app",
        "params": {"package": "com.netflix.mediaclient", "wait_time": 8000}
    }]
})
# MCP waits for async completion
# Returns: ✅ Action execution completed: 1/1 passed
```

**📱 Swipe:**
```python
execute_device_action({
    "actions": [{"command": "swipe_up", "params": {"wait_time": 1000}}]
})
```

**👆 Click Element:**
```python
execute_device_action({
    "actions": [{
        "command": "click_element",
        "params": {"text": "Home", "wait_time": 2000}
    }]
})
```

**⌨️ Type Text:**
```python
execute_device_action({
    "actions": [{
        "command": "type_text",
        "params": {"text": "Hello World", "wait_time": 1000}
    }]
})
```

**🔑 Press Key:**
```python
execute_device_action({
    "actions": [{
        "command": "press_key",
        "params": {"key": "BACK", "wait_time": 1500}
    }]
})
```

**Device Model Specific:**
- **android_mobile/android_tv**: Use ADB/Remote commands
  - Examples: `launch_app`, `swipe_up`, `swipe_down`, `click_element`, `click_element_by_id`, `type_text`, `press_key`
- **web/desktop**: Use web automation commands
  - Examples: `web_click`, `web_type`, `web_navigate`

**💡 Tip:** Call `list_actions()` first to discover all available commands for your device.

---

## ⏱️ Action Wait Time Guidelines

### 🎯 Critical Understanding

**The `wait_time` field goes INSIDE `params`, NOT as a top-level field!**

```json
✅ CORRECT:
{
  "command": "launch_app",
  "params": {
    "package": "com.example.app",
    "wait_time": 8000
  }
}

❌ WRONG:
{
  "command": "launch_app",
  "params": {"package": "com.example.app"},
  "delay": 8000
}
```

The `wait_time` value is in **milliseconds** and represents the wait time **AFTER** the action completes, before executing the next action.

---

### 📋 Standard Wait Times by Operation

| Operation Type | Standard Delay (ms) | Use Case | Reason |
|----------------|---------------------|----------|--------|
| **launch_app** | 8000 (8s) | App initialization | App needs time to load resources, initialize services, render UI |
| **click_element** | 2000 (2s) | Tab navigation, menu items | Screen transition + UI rendering |
| **tap_coordinates** | 2000 (2s) | Screen taps | Screen transition + UI rendering |
| **press_key** (BACK) | 1500 (1.5s) | Back navigation | Faster than forward nav, but still needs UI update |
| **press_key** (other) | 1000 (1s) | Key presses (HOME, MENU) | Quick UI response |
| **type_text** | 1000 (1s) | Text input | Input processing + keyboard animation |
| **swipe** | 1500 (1.5s) | Swipe gestures | Animation completion |
| **scroll** | 1000 (1s) | Scrolling | Scroll animation |

### Heavy Operations (Longer Delays)

| Operation | Delay (ms) | Context |
|-----------|------------|---------|
| **Click "Play" button** | 5000 (5s) | Video player initialization |
| **Search + Results** | 3000 (3s) | Search execution + results rendering |
| **Load content detail** | 3000 (3s) | Heavy page with images/metadata |
| **Login/Authentication** | 4000 (4s) | Network request + validation |

---

### ✅ Example Structure

```json
{
  "command": "launch_app",
  "params": {
    "package": "com.example.app",
    "wait_time": 8000
  }
}
```

**Explanation:** 
- The app starts launching at time 0
- After launch completes, the system waits 8 seconds
- Then the next action executes (at ~8+ seconds)
- This ensures the app is fully initialized and ready

---

### 🚨 Common Mistakes

#### ❌ Mistake 1: wait_time as Top-Level Field
```json
{
  "command": "launch_app",
  "params": {
    "package": "com.example.app"
  },
  "delay": 8000  ← WRONG! Should be wait_time inside params
}
```

#### ❌ Mistake 2: No Wait Time After Heavy Operation
```json
{
  "command": "launch_app",
  "params": {"package": "..."}
  // Missing wait_time = immediate next action = FAILURE!
}
```

#### ❌ Mistake 3: Wait Time Too Short
```json
{
  "command": "launch_app",
  "params": {"package": "...", "wait_time": 2000}  ← TOO SHORT!
}
```

#### ❌ Mistake 4: Using Seconds Instead of Milliseconds
```json
{
  "command": "click_element",
  "params": {"element_id": "...", "wait_time": 2}  ← WRONG! Use 2000
}
```

---

### 🔧 Delay Adjustment Guidelines

#### When to Increase Delays:

1. **Slow Devices:** +2000ms for each operation
2. **Slow Network:** +3000ms for search/load operations
3. **Heavy Content:** +1000-2000ms for image-rich pages
4. **Video Operations:** +2000-3000ms for buffering

#### When Delays Can Be Shorter:

1. **Fast Devices:** -1000ms (but never below minimums)
2. **Simple UI:** -500ms for lightweight screens
3. **Back Navigation:** Already optimized at 1500ms

#### Minimum Safe Wait Times:

```json
{
  "launch_app": 5000,      // Absolute minimum (risky)
  "click_element": 1500,   // Absolute minimum
  "press_key": 1000,       // Absolute minimum
  "type_text": 500         // Absolute minimum
}
```

**Recommendation:** Use standard wait times from table above, increase if failures occur.

---

### 📖 Complete Action Examples

#### Example 1: App Launch
```json
{
  "command": "launch_app",
  "params": {
    "package": "com.netflix.mediaclient",
    "wait_time": 8000
  }
}
```
**Why 8000ms?** App needs time for: splash screen, initialization, home screen render.

---

#### Example 2: Tab Navigation
```json
{
  "command": "click_element",
  "params": {
    "element_id": "Search Tab",
    "wait_time": 2000
  }
}
```
**Why 2000ms?** Tab animation + screen transition + content load.

---

#### Example 3: Video Playback
```json
{
  "command": "click_element",
  "params": {
    "element_id": "Play",
    "wait_time": 5000
  }
}
```
**Why 5000ms?** Video player needs: initialization, buffering, controls setup.

---

#### Example 4: Multiple Sequential Actions
```json
{
  "actions": [
    {
      "command": "launch_app",
      "params": {"package": "com.netflix.mediaclient", "wait_time": 8000}
    },
    {
      "command": "tap_coordinates",
      "params": {"x": 540, "y": 1645, "wait_time": 2000}
    },
    {
      "command": "click_element",
      "params": {"element_id": "Dismiss", "wait_time": 1000}
    }
  ]
}
```
**Execution Timeline:**
- 0s: App launch starts
- 8s: Wait completes, tap coordinates
- 10s: Wait completes, click dismiss
- 11s: Wait completes, ready for next action

---

### ✅ Quick Reference Card

```
┌──────────────────────────────────────────────────────┐
│ QUICK WAIT TIME REFERENCE                            │
├──────────────────────────────────────────────────────┤
│ launch_app           → 8000ms  (8 seconds)          │
│ click_element        → 2000ms  (2 seconds)          │
│ tap_coordinates      → 2000ms  (2 seconds)          │
│ press_key (BACK)     → 1500ms  (1.5 seconds)        │
│ press_key (other)    → 1000ms  (1 second)           │
│ type_text            → 1000ms  (1 second)           │
│ video operations     → 5000ms  (5 seconds)          │
│ search + results     → 3000ms  (3 seconds)          │
├──────────────────────────────────────────────────────┤
│ CRITICAL: wait_time goes INSIDE params!             │
└──────────────────────────────────────────────────────┘
```

---

### 🎓 For AI Models: Key Takeaways

1. **ALWAYS include `wait_time` field** in params for every action
2. **`wait_time` is INSIDE `params`**, not top-level
3. **Use milliseconds** (1 second = 1000ms)
4. **Start with standard wait times** from table
5. **Increase if failures occur** (+2000ms increments)
6. **App launch needs longest wait** (8000ms minimum)
7. **Video operations need 5000ms** minimum
8. **Tab/menu navigation: 2000ms** standard
9. **Back navigation: 1500ms** (faster than forward)
10. **Text input: 1000ms** + extra for search results
