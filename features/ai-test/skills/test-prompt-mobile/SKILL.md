---
name: test-prompt-mobile
description: Execute a test prompt on an Android mobile/tablet device — navigate using the pre-loaded tree, interact via ADB, verify acceptance criteria
platform: mobile
requires_device: true
timeout_seconds: 300
tools:
  - execute_device_action
  - navigate_to_node
triggers:
  - test prompt mobile
  - test prompt android
  - run prompt mobile
---

# Test Prompt — Android Mobile / Tablet

You receive a **test prompt** (what to do) and **acceptance criteria** (how to confirm it passed). Execute the prompt on the device autonomously, then evaluate each criterion with evidence.

## Platform: Android Mobile

**action_type:** `android_mobile`

Screenshots are captured automatically — you don't need to take them.

## CRITICAL: The Navigation Tree Is Already Loaded

The user message you receive includes a **Pre-loaded Navigation Tree** section listing every node and edge for this interface. You must:

1. **Read the tree first.** Look at the listed node labels and edges before doing anything else.
2. **Use labels EXACTLY as written.** When calling `navigate_to_node(target_node_label=...)`, copy the label character-for-character from the tree. Do NOT translate, normalize, prettify, or guess. If the tree says `home_settings`, you write `home_settings` — never `Settings`, `settings`, or `home settings`.
3. **Do NOT call `get_userinterface_complete`.** It is not available — the tree is already in your context.
4. If the screen the user wants is in the tree, use `navigate_to_node`. If it isn't, use `execute_device_action` with the commands below.

## How to navigate

```
navigate_to_node(
  host_name="<from context>",
  device_id="<from context>",
  target_node_label="<EXACT label from the pre-loaded tree>",
  userinterface_name="<from context>"
)
```

## How to call execute_device_action

**ALWAYS include `action_type: "android_mobile"` and `force_unlock: true`.**

```
execute_device_action(
  host_name="<from context>",
  device_id="<from context>",
  action_type="android_mobile",
  force_unlock=true,
  actions=[{command: "<command>", params: {<params>}}]
)
```

### Available commands (mobile)

**Inspection — call this BEFORE acting on an unfamiliar screen:**
- `dump_elements` — return the full UI hierarchy: every element's text, content_desc, resource_id, class_name, and screen bounds. This is your primary inspection tool.
- `find_element(search_term)` — search across text, content_desc, resource_id, class_name; returns matching elements with their bounds.
- `take_screenshot` — capture a screenshot of the current screen and attach it to the step report. You will NOT receive the image — only a confirmation. Use this when you want the human reviewer to have visual evidence of the current screen state (e.g. when `dump_elements` fails and you need to report FAIL with a screenshot for context).
- `get_installed_apps` — list installed packages.

**Interaction:**
- `click_element(text or element_id)` — click an element by visible text. Supports pipe-separated fallbacks: `"Sign In|Login|Anmelden"`.
- `tap_coordinates(x, y)` — tap at absolute pixel coordinates (use after `dump_elements` gives you bounds).
- `input_text(text)` — type into the currently focused field.
- `press_key(key)` — Android keycodes: `BACK`, `HOME`, `MENU`, `UP`, `DOWN`, `LEFT`, `RIGHT`, `OK`, `VOLUME_UP`, `VOLUME_DOWN`, `POWER`.
- `swipe(from_x, from_y, to_x, to_y, duration)` — full swipe with duration in ms.
- `swipe_up` / `swipe_down` / `swipe_left` / `swipe_right` — directional swipes (params optional).
- `SWIPE_UP` / `SWIPE_DOWN` / `SWIPE_LEFT` / `SWIPE_RIGHT` — uppercase shorthand variants with no params.

**App lifecycle:**
- `launch_app(package)` — launch by package name (e.g. `com.android.settings`).
- `close_app(package)` — force-stop a package.

## Execution Workflow

1. **Read the pre-loaded navigation tree** in the user message. Identify which node label matches the target screen.
2. **Navigate**: `navigate_to_node(target_node_label="<EXACT label>")` for known screens; `execute_device_action` with `dump_elements` + click/tap for screens not in the tree.
3. **Execute prompt**: follow the user's instructions. Always `dump_elements` before clicking on an unfamiliar screen so you know what's actually on it.
4. **Verify criteria**: use `dump_elements` (or `find_element` for a specific item) to inspect the page content. Match the acceptance criteria against the dumped element text.
5. **Report**: output results in the format below.

## Report Format

```
## Test Prompt Results

**Prompt:** {prompt}
**Target Screen:** {target or "none"}

### Execution Steps
1. {action} — {result}
2. {action} — {result}

### Acceptance Criteria
- [PASS] {criterion} — Evidence: {what you found in dump_elements}
- [FAIL] {criterion} — Evidence: {expected vs actual}

### Overall: PASS (or FAIL)
```

## Rules

1. **The navigation tree is in your context — read it before navigating.**
2. **Copy node labels EXACTLY from the tree** — never invent, normalize, or guess them.
3. **ALWAYS include `action_type: "android_mobile"`** in every execute_device_action call.
4. **Use `force_unlock: true`** on the first call.
5. **`dump_elements` is your eyes** — always dump before tapping coordinates or clicking unfamiliar elements. Never tap blind.
6. **Prefer `click_element` over `tap_coordinates`** when you have visible text — coordinates are screen-resolution-dependent.
7. **Handle errors** — if `navigate_to_node` fails on a label that IS in the tree, fall back to `execute_device_action`.
8. **NEVER fabricate evidence.** Every acceptance criterion must be proven by data you received in a tool result. If you cannot point to specific text from a tool response that proves a criterion, mark it FAIL and explain what you could not verify and why. A false PASS is worse than an honest FAIL.
9. **One dump per screen.** If `dump_elements` returns element data, use it — do not call it again on the same screen. If it returns no data, retry once, then report FAIL.
