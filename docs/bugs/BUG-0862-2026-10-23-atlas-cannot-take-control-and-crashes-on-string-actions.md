# BUG-0862 — Atlas could not take control or release, crashed on bare key names, and the FAQ answered commands

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0862                                                          |
| Reported  | 2026-10-23                                                        |
| Status    | Fixed (pending deploy)                                            |
| Severity  | High                                                              |
| Area      | backend_server (Atlas tools, skills, FAQ step) / ai               |
| Fixed in  | build 90145 |
| Commit    | TBD                                                               |

---

## Symptom

TASK-163 stb benchmark (93 prompts, real stb on the rpitest server, 36% pass):

- "Release all stb", "Take control of all devices on host X": the model said `release_control` / `take_control` "is not
  available in my current toolset".
- "Volume up on stb3", "Wake all stb": `execute_device_action` failed with `'str' object has no attribute 'get'`.
- "Press HOME on stb3": answered with no tool call, by the FAQ entry "HOME toggles: press it once only".

## Root cause

1. `take_control` / `release_control` are hidden from MCP discovery, and `ToolBridge.get_tool_definitions` only serves
   discovered tools, so a skill that lists them by name (BUG-0850) still never offered them to the model.
2. `execute_device_action` normalised each action with `action.get(...)`; a model that sends `["VOLUME_UP"]` or
   `{"key": "HOME"}` crashed it.
3. The FAQ step ran for every short message; a command naming a device ("Press HOME on stb3") matched a docs entry.

## Fix

- `ToolBridge.get_tool_definitions` offers a hidden lock tool when a skill names it explicitly.
- `execute_device_action`: a bare string or `{"key": ...}` is a `press_key`; a non-object action is refused with the
  expected format; a lock tool name sent as an action is refused (BUG-0850).
- `quick_step.is_device_command`: an imperative that names a known device skips the FAQ.
- Tests: `tests/backend_server/test_lock_command_error.py`.

Found by TASK-163 (`docs/agent/atlas/USECASES.md`).
