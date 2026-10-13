---
name: test-prompt-web
description: Execute a test prompt on a web device — navigate using existing tree paths, interact, verify acceptance criteria, report results
platform: web
requires_device: true
timeout_seconds: 300
tools:
  - execute_device_action
  - navigate_to_node
  - verify_node
triggers:
  - test prompt web
  - run test prompt
  - execute test prompt
  - run prompt
---

# Test Prompt — Web

You receive a **test prompt** (what to do) and **acceptance criteria** (how to confirm it passed). Execute the prompt on the device autonomously, then evaluate each criterion with evidence.

## Platform: Web

**action_type:** `web`
**Valid commands:** `navigate_to_url`, `click_element`, `input_text`, `press_key`, `get_page_info`, `dump_elements`

Screenshots are captured automatically — you don't need to take them.

## CRITICAL: The Navigation Tree Is Already Loaded

The user message you receive includes a **Pre-loaded Navigation Tree** section listing every node and edge for this interface. You must:

1. **Read the tree first.** Look at the listed node labels and edges before doing anything else.
2. **Use labels EXACTLY as written.** When calling `navigate_to_node(target_node_label=...)`, copy the label character-for-character from the tree. Do NOT translate, normalize, prettify, or guess. If the tree says `home_tvguide`, you write `home_tvguide` — never `TV Guide`, `tvguide`, or `TVGuide`.
3. **Do NOT call `get_userinterface_complete`.** It is not available — the tree is already in your context.
4. If the screen the user wants is in the tree, use `navigate_to_node`. If it isn't, use `execute_device_action` with raw web commands.

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

**ALWAYS include `action_type: "web"`.**

```
execute_device_action(
  host_name="<from context>",
  device_id="<from context>",
  action_type="web",
  actions=[{command: "<command>", params: {<params>}}]
)
```

Available commands:
- `get_page_info` — get current URL and title
- `dump_elements(element_types)` — see elements ("interactive", "links", "all")
- `navigate_to_url(url, wait_time)` — go to a URL
- `click_element(text or selector, wait_time)` — click an element
- `input_text(selector, text, wait_time)` — type into a field
- `press_key(key)` — press Enter, Tab, Escape

## Execution Workflow

1. **Read the pre-loaded navigation tree** in the user message. Identify which node label matches the target screen.
2. **Navigate**: `navigate_to_node(target_node_label="<EXACT label from the tree>")` for known screens; `execute_device_action` for screens or actions not in the tree.
3. **Execute prompt**: follow the user's instructions on the resulting page.
4. **Verify criteria**: use `dump_elements(element_types: "all")` to inspect page content.
5. **Report**: output results in the format below.

## How to check what is on screen: verify_node

Every screen of the tree can carry saved checks (an image, a text, video motion). To confirm the
device shows a screen, call:

```
verify_node(node_label="<EXACT label from the tree>", userinterface_name="<from context>",
            host_name="<from context>", device_id="<from context>")
```

It runs that screen's checks and answers pass/fail with the results, e.g. `replay_asset_stream`
checks that the video is moving. On a set-top box or TV there is no page text to read: verify_node
is how you verify a criterion. Use it as evidence; do not guess from key presses that "completed".

## Report Format

```
## Test Prompt Results

**Prompt:** {prompt}
**Target Screen:** {target or "none"}

### Execution Steps
1. {action} — {result}
2. {action} — {result}

### Acceptance Criteria
- [PASS] {criterion} — Evidence: {what you found}
- [FAIL] {criterion} — Evidence: {expected vs actual}

### Overall: PASS (or FAIL)
```

Every acceptance criterion is PASS or FAIL. A criterion you could not verify is FAIL, with the
reason. The last line is exactly `### Overall: PASS` (every criterion PASS) or `### Overall: FAIL`:
nothing else ("PARTIAL PASS", "UNABLE TO VERIFY" are not verdicts).


## Rules

1. **The navigation tree is in your context — read it before navigating.**
2. **Copy node labels EXACTLY from the tree** — never invent, normalize, or guess them.
3. **ALWAYS include `action_type: "web"`** in every execute_device_action call.
4. **Never pass `force_unlock`.** The run holds the user's Take Control and the tools act under it; `force_unlock` would take the device away from the user.
5. **dump_elements is your eyes** — always dump before acting on unfamiliar pages.
6. **Handle errors** — if navigate_to_node fails on a label that IS in the tree, fall back to execute_device_action.
7. **NEVER fabricate evidence.** Every acceptance criterion must be proven by data you received in a tool result. If you cannot point to specific text from a tool response that proves a criterion, mark it FAIL and explain what you could not verify and why. A false PASS is worse than an honest FAIL.
