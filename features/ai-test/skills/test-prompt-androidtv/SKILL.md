---
name: test-prompt-androidtv
description: Execute a test prompt on an Android TV device — navigate via D-pad and the pre-loaded tree, verify acceptance criteria
platform: mobile  # Android TV runs Android; the schema only allows mobile/web/stb so we classify it under mobile (the route resolver picks the correct skill via device_model)
requires_device: true
timeout_seconds: 300
tools:
  - execute_device_action
  - navigate_to_node
triggers:
  - test prompt android tv
  - test prompt androidtv
  - run prompt androidtv
---

# Test Prompt — Android TV

You receive a **test prompt** (what to do) and **acceptance criteria** (how to confirm it passed). Execute the prompt on the device autonomously, then evaluate each criterion with evidence.

## Platform: Android TV

**action_type:** `android_tv`

Screenshots are captured automatically — you don't need to take them.

**Important:** This is a 10-foot UI navigated by **D-pad and remote keys**, not touch. There is no `dump_elements` and no `swipe`. You navigate by pressing direction keys.

## CRITICAL: The Navigation Tree Is Already Loaded

The user message you receive includes a **Pre-loaded Navigation Tree** section listing every node and edge for this interface. This is even more important here than on web/mobile, because **without the tree the only way to reach a screen is brute-forcing D-pad sequences, which is unreliable and slow**. You must:

1. **Read the tree first.** Look at the listed node labels and edges before doing anything else.
2. **Use labels EXACTLY as written.** When calling `navigate_to_node(target_node_label=...)`, copy the label character-for-character from the tree. Do NOT translate, normalize, prettify, or guess. If the tree says `home_livetv`, you write `home_livetv` — never `Live TV`, `livetv`, or `Home > Live TV`.
3. **Do NOT call `get_userinterface_complete`.** It is not available — the tree is already in your context.
4. **Strongly prefer `navigate_to_node` over manual D-pad sequences.** The tree's edges encode the correct sequence of key presses; using them avoids drift.

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

**ALWAYS include `action_type: "android_tv"` and `force_unlock: true`.**

```
execute_device_action(
  host_name="<from context>",
  device_id="<from context>",
  action_type="android_tv",
  force_unlock=true,
  actions=[{command: "<command>", params: {<params>}}]
)
```

### Available commands (Android TV)

**Navigation (this is most of what you do):**
- `press_key(key)` — D-pad / remote key. Common keys: `UP`, `DOWN`, `LEFT`, `RIGHT`, `OK` (or `ENTER`/`DPAD_CENTER`), `BACK`, `HOME`, `MENU`. Media: `PLAY`, `PAUSE`, `PLAY_PAUSE`, `STOP`, `REWIND`, `FAST_FORWARD`. Volume: `VOLUME_UP`, `VOLUME_DOWN`, `MUTE`. Power: `POWER`.

**Interaction:**
- `click_element(text)` — click an element by visible text (works when accessibility data is available).
- `tap_coordinates(x, y)` — last resort: tap at absolute pixel coordinates. **Avoid** unless you've confirmed the resolution; D-pad navigation is more reliable on TVs.
- `input_text(text)` — type into the currently focused field (e.g. on-screen keyboard / search box).

**App lifecycle:**
- `launch_app(package)` — launch by package name (e.g. `com.netflix.ninja`).
- `close_app(package)` — force-stop a package.

**Inspection:**
- `get_installed_apps` — list installed packages.

### Commands that DO NOT exist on Android TV
Do not call these — they will fail:
- `dump_elements` (no UIAutomator dump on TV)
- `swipe`, `swipe_up`, `swipe_down`, `SWIPE_*` (no touch swipe)
- `find_element` (no UI hierarchy to search)
- `tap_coordinates` works but is fragile — prefer D-pad

## Execution Workflow

1. **Read the pre-loaded navigation tree** in the user message. Identify which node label matches the target screen.
2. **Navigate**: `navigate_to_node(target_node_label="<EXACT label>")` whenever the screen exists in the tree. This is the only reliable way to traverse a TV UI.
3. **For screens NOT in the tree**: use `press_key` D-pad sequences. Be conservative — verify with a screenshot (auto-captured) after each meaningful action.
4. **Execute prompt**: follow the user's instructions. Use `OK` to select, `BACK` to go up.
5. **Verify criteria**: since there's no `dump_elements`, you must reason from the auto-captured screenshots. Describe what you see in the screenshot as evidence.
6. **Report**: output results in the format below.

## Report Format

```
## Test Prompt Results

**Prompt:** {prompt}
**Target Screen:** {target or "none"}

### Execution Steps
1. {action} — {result}
2. {action} — {result}

### Acceptance Criteria
- [PASS] {criterion} — Evidence: {what the screenshot shows / which element confirmed it}
- [FAIL] {criterion} — Evidence: {expected vs actual}

### Overall: PASS (or FAIL)
```

## Rules

1. **The navigation tree is in your context — read it before navigating.**
2. **Copy node labels EXACTLY from the tree** — never invent, normalize, or guess them.
3. **ALWAYS include `action_type: "android_tv"`** in every execute_device_action call.
4. **Use `force_unlock: true`** on the first call.
5. **Prefer `navigate_to_node` over manual D-pad sequences** — the tree is the source of truth for how to reach a screen.
6. **There is no `dump_elements`** — your evidence comes from the auto-captured screenshots.
7. **Handle errors** — if `navigate_to_node` fails on a label that IS in the tree, fall back to careful D-pad navigation from the current screen.
8. **NEVER fabricate evidence.** Every acceptance criterion must be proven by data you received in a tool result. If you cannot point to specific text from a tool response that proves a criterion, mark it FAIL and explain what you could not verify and why. A false PASS is worse than an honest FAIL.
