---
name: test-prompt-stb
description: Execute a test prompt on a set-top box — navigate via IR remote and the pre-loaded tree, verify with screenshot evidence
platform: stb
requires_device: true
timeout_seconds: 300
think_budget_seconds: 120
max_tool_calls: 40
tools:
  - execute_device_action
  - navigate_to_node
  - localize
  - verify_node
triggers:
  - test prompt stb
  - test prompt set top box
  - run prompt stb
---

# Test Prompt — Set-Top Box (IR Remote)

You receive a **test prompt** (what to do) and **acceptance criteria** (how to confirm it passed). Execute the prompt on the device autonomously, then evaluate each criterion with evidence.

## Platform: STB

**action_type:** `infrared`

Screenshots are captured automatically — you don't need to take them.

**Where am I? — `localize` first (TASK-107).** After a step (an OK, a goto, a failed goto) call `localize(host_name, device_id, userinterface_name)`: it answers in one line, with no image — `node` (which saved screen), `live`, `signal`, `overlay`, `known_screen` or `unknown`. `navigate_to_node` already appends that verdict and attaches a screenshot only when it does not confirm the target. Take a screenshot only when the verdict is `unknown`, `overlay` or `known_screen`, or when you need to read text on the screen.

**Important:** STBs are controlled by **IR remote only**. The controller exposes a single command — `press_key` — and supports only the keys defined in the device's IR config (e.g. `samsung.json`). There is no touch, no UI hierarchy dump, no app launching, no keyboard. **All navigation flows through the navigation tree and IR key presses.** Verification is **screenshot-based** (the agent must reason from the auto-captured frames).

## CRITICAL: The Navigation Tree Is Your Map

The user message you receive includes a **Pre-loaded Navigation Tree** section listing every node and edge for this interface. On STBs this tree is **the only structured information you have** — you cannot dump elements, you cannot query the OS, you cannot search the screen. Without the tree you would be guessing IR sequences blindly. You must:

1. **Read the tree first.** Look at the listed node labels and edges before doing anything else.
2. **Use labels EXACTLY as written.** When calling `navigate_to_node(target_node_label=...)`, copy the label character-for-character from the tree. Do NOT translate, normalize, prettify, or guess. If the tree says `home_guide`, you write `home_guide` — never `Guide`, `TV Guide`, or `home guide`.
3. **Do NOT call `get_userinterface_complete`.** It is not available — the tree is already in your context.
4. **Use `navigate_to_node` for every transition possible.** Manual `press_key` sequences should only fill the last-mile gaps inside a screen (e.g. moving the highlight one cell over to select a specific channel after `navigate_to_node` brought you to the guide).

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

**ALWAYS include `action_type: "infrared"`.**

```
execute_device_action(
  host_name="<from context>",
  device_id="<from context>",
  action_type="infrared",
  actions=[{command: "press_key", params: {key: "<KEY_NAME>"}}]
)
```

### Available command (STB)

**`press_key(key)` — the only command.** Send one IR key per call. Valid `key` names depend on the loaded IR config; common ones across Samsung / LG / vendor configs include:

- **Navigation:** `UP`, `DOWN`, `LEFT`, `RIGHT`, `OK` (or `ENTER` / `SELECT`), `BACK`, `EXIT`, `HOME`, `MENU`, `INFO`
- **Channel / volume:** `CH_UP`, `CH_DOWN`, `VOL_UP`, `VOL_DOWN`, `MUTE`
- **Numeric:** `0`, `1`, `2`, `3`, `4`, `5`, `6`, `7`, `8`, `9`
- **Media:** `PLAY`, `PAUSE`, `STOP`, `REWIND`, `FAST_FORWARD`, `RECORD`
- **Power / source:** `POWER`, `SOURCE`, `INPUT`
- **Color buttons:** `RED`, `GREEN`, `YELLOW`, `BLUE`
- **Misc:** `GUIDE`, `EPG`, `LIST`

If you call a key that the device's IR config doesn't define, the call will fail with an error listing the available keys for that device. Read the error and pick a defined key.

### Commands that DO NOT exist on STB
Do not call these — they will fail:
- `dump_elements` (no UI hierarchy on a TV signal)
- `click_element`, `tap_coordinates` (no touch / no element model)
- `swipe`, `find_element`, `input_text`
- `launch_app`, `close_app` (STB apps are not addressable by package)

## Execution Workflow

1. **Read the pre-loaded navigation tree** in the user message. Identify which node label matches the target screen.
2. **Navigate**: `navigate_to_node(target_node_label="<EXACT label>")` whenever the screen exists in the tree.
3. **For fine-grained moves inside a screen** (highlighting a particular channel, scrolling a guide), use `press_key` with directional keys.
4. **Pace yourself.** STBs are slow — IR commands can take 200-500ms to register. Don't fire bursts; let each action complete before the next.
5. **Verify criteria**: you have NO `dump_elements`. Your evidence comes from the auto-captured screenshots — describe what you see in the most recent screenshot to support each criterion.
6. **Report**: output results in the format below.

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
- [PASS] {criterion} — Evidence: {what the screenshot shows}
- [FAIL] {criterion} — Evidence: {expected vs actual}

### Overall: PASS (or FAIL)
```

Every acceptance criterion is PASS or FAIL. A criterion you could not verify is FAIL, with the
reason. The last line is exactly `### Overall: PASS` (every criterion PASS) or `### Overall: FAIL`:
nothing else ("PARTIAL PASS", "UNABLE TO VERIFY" are not verdicts).


## Rules

1. **The navigation tree is in your context — read it before navigating.** It is the only structured map you have on this platform.
2. **Copy node labels EXACTLY from the tree** — never invent, normalize, or guess them.
3. **ALWAYS include `action_type: "infrared"`** in every execute_device_action call.
4. **Never pass `force_unlock`.** The run holds the user's Take Control and the tools act under it; `force_unlock` would take the device away from the user.
5. **`press_key` is your only command** — anything else will fail.
6. **Send keys one at a time** — don't try to chain multiple keys in a single action.
7. **Evidence is screenshots** — describe what you see, since you cannot dump or query.
8. **Handle errors** — if `navigate_to_node` fails on a label that IS in the tree, fall back to manual `press_key` navigation from the current screen.
9. **NEVER fabricate evidence.** Every acceptance criterion must be proven by data you received in a tool result. If you cannot point to specific text from a tool response that proves a criterion, mark it FAIL and explain what you could not verify and why. A false PASS is worse than an honest FAIL.

## Set-top box asleep? (read `docs/agent/devices/STB_STANDBY.md`)

A dark capture means the box is asleep, not broken; never blame the box.
- Asleep = SMPTE colour bars, or near-black with a tiny identical file size. Garbled frames while waking are normal.
- IR box: POWER once, wait 60 s; a first press that does nothing is normal; second POWER 60 s later. POWER and HOME toggle: never twice in a row.
- BLE box, active standby: poll `get_pairing_status`; the link returns by itself in about 30 s.
- BLE box, deep standby (link still down after ~30 s, `resume_state: failed`): send `cold_wake` (action `ble_cold_wake`, WoBLE). It is NOT pairing. Poll `get_pairing_status` about 25 s, then capture until a real picture.
- Never Start Pairing, in particular never after a reboot. Still dark after two POWER presses or two `cold_wake`: report `env: no signal` and stop.
