---
name: ai-userinterface
description: Read and execute against the AI-learned UI knowledge base (tables ai_userinterfaces, ai_userinterface_screens/transitions/verifications/tasks/quirks/known_hardware/fingerprints). Resolve a device's runtime fingerprint to a known ui_id, load the compiled pack (ui_pack_markdown), execute a named task (e.g. read_firmware) using ONLY capture_screenshot + execute_device_action. Also append new verified content after navigation, supersede or revert wrong entries.
platform: null
requires_device: false
timeout_seconds: 600
tools:
  # Read — always safe
  - resolve_ai_userinterface
  - get_ai_userinterface
  - list_ai_userinterfaces
  - get_ai_userinterface_history
  # Write / admin — ONLY when the user explicitly asks to record, correct, or roll back KB data
  - create_ai_userinterface
  - update_ai_userinterface
  - revert_ai_userinterface
  - add_ai_userinterface_screen
  - add_ai_userinterface_transition
  - add_ai_userinterface_verification
  - add_ai_userinterface_task
  - add_ai_userinterface_quirk
  - add_ai_userinterface_known_hardware
  - add_ai_userinterface_fingerprint
  - supersede_ai_userinterface_row
  # Device interaction — the two raw tools are the ENTIRE execution surface
  - get_device_info
  - capture_screenshot
  - execute_device_action
triggers:
  - ai userinterface
  - ai ui
  - ai knowledge base
  - what do we know about
  - resolve fingerprint
  - ai_userinterface
  - knowledge base
  - record what i learned
  - read firmware
  - ui pack
---

# AI UserInterface knowledge base

This skill is the interface to the `ai_userinterfaces` family of tables. Runtime navigation reads the compiled **ui_pack_markdown** on the parent row and executes the pack's task section using only two raw tools: `capture_screenshot` and `execute_device_action`.

See `docs/agent/navigation/AI_USERINTERFACE_MARKDOWN_PACKS.md` for the 5-layer model and `docs/agent/AI_USERINTERFACE_example_EXAMPLE.md` for a filled-in example.

## ⚠ Distinction — two parallel UI systems

| | **`userinterfaces`** (production) | **`ai_userinterfaces`** (this skill) |
|---|---|---|
| Tables | `userinterfaces`, `navigation_trees`, `navigation_nodes`, `navigation_edges` | `ai_userinterfaces`, `ai_userinterface_screens/transitions/verifications/tasks/quirks/known_hardware/fingerprints` |
| Author | Humans via React Flow editor | AI during crawling, then Verifier-tagged, Packager-compiled |
| Purpose | Executable graphs run by production scripts | Narrative pack + verified transitions + assertions + tasks, consumed by Atlas at runtime |
| Slug shape | e.g. `google_tv`, `sauce-demo` | e.g. `example-5.02`, `netflix-8`, `exampletv-ch` |

**If you see a slug like `example-5.02`, call `get_ai_userinterface` (this skill). `navigate_to_node` / `preview_userinterface` will 404.**

## Runtime workflow (execute a task)

Given a user ask like *"read firmware on host1 device3"*:

```
1. resolve_ai_userinterface(fingerprint_type='software_version_glob', value='<read from About, or pass literal>')
   → parent row incl. ui_id (e.g. 'example-5.02')

2. get_ai_userinterface(ui_id) → bundle { parent, screens, transitions, verifications, tasks, quirks, ... }
   → pick `parent.ui_pack_markdown` as your pack text
   → pick the matching task from `tasks[]` by `task_name` (e.g. 'read_firmware') and read `steps_md`

3. Execute steps_md verbatim on the device using ONLY:
   - capture_screenshot(device_id, host_name, vlm=true|false)
   - execute_device_action(device_id, host_name, actions=[...])

4. Reply with the values the task's `returns` promises. Then STOP.
```

**Do not invent navigation.** If the pack's task section does not cover the user's request, the correct response is to report *"no verified task for this ask; please record one"* — not to improvise multi-step navigation.

## Pack step tags

The `steps_md` field uses three step kinds. Respect them literally:

| Tag | Behaviour |
|---|---|
| `[deterministic]` | Emit the stored action batch blind. **No screenshot first.** |
| `[observed]` | `capture_screenshot(vlm=true)`, read focus, compute delta, emit sized batch. |
| `[read]` | `capture_screenshot(vlm=true)`, parse values from the VLM block, reply. No device action. |

Each pack also specifies MCP tool call shapes (exact JSON) and a Safety block (dangerous phrases that trigger STOP, not retry).

## Writing to the knowledge base — READ-BEFORE-WRITE rule

Only write when the user explicitly asks to record, correct, or supersede KB data. If the user asks "navigate / read / run", you are in execute mode — read the pack, do not write.

Before `add_ai_userinterface_transition`: call `get_ai_userinterface` first. If a transition with the same `(from_screen, item_label)` already exists, supersede it with a reason before re-adding — never duplicate.

**`actions` format for transitions** (same rules as before):
- One entry per single press — no shorthand (`× N`, `RIGHT*6`, `repeat:N`), no comma-joined keys
- STB IR (`action_type=infrared`): no `iterator>1` (pulses drop)
- Each entry: `{"command":"press_key","params":{"action_type":"infrared","key":"<NAME>","wait_time":<ms>}}`
- Direction wait 800 ms; OK/BACK/HOME/TVGUIDE wait 4000 ms

**Layer-3 verifications**: `kind` ∈ `{present, regex, value_matches}`, `severity` ∈ `{hard, soft}`. Use `soft` for fields the VLM may not always surface (e.g. SERIAL NUMBER on Example).

**Layer-4 tasks**: `steps_md` is the prose the runtime LLM executes; write it with explicit step tags and concrete decision trees ("if VLM says X, do Y; else Z"). Avoid vague prose like "navigate to X".

## Correcting a wrong entry

```
supersede_ai_userinterface_row(table_short='screens'|'transitions'|'quirks'|..., row_id=..., reason="<why>")
```

Only tables with a `superseded_at` column are eligible: `{screens, transitions, quirks, known_hardware, fingerprints}`. Verifications and tasks use write-then-replace — delete the row and re-add.

For a corrupted parent edit: `revert_ai_userinterface(ui_id, to_version=<N>, reason="<why>")` reads snapshot N from history and writes a new version. No data is destroyed.

## Common asks → which tool

| User asks | Call |
|---|---|
| "Read the firmware" / "run task `<task>`" | `resolve_ai_userinterface` → `get_ai_userinterface` → execute the matching `tasks[].steps_md` via `capture_screenshot` + `execute_device_action` |
| "What do we know about the UI on `<host>/<device>`?" | `resolve_ai_userinterface` → `get_ai_userinterface` |
| "Which UIs have we learned?" | `list_ai_userinterfaces` |
| "Show me the change log for `<ui_id>`" | `get_ai_userinterface_history` |
| "I discovered a new transition" | `get_ai_userinterface` → `add_ai_userinterface_transition` |
| "I observed a new screen" | `get_ai_userinterface` → `add_ai_userinterface_screen` |
| "Add an assertion for screen X" | `add_ai_userinterface_verification` |
| "Record this task flow" | `add_ai_userinterface_task` |
| "This transition doesn't work anymore" | `supersede_ai_userinterface_row` with reason |
| "Roll back the last edit on `<ui_id>`" | `get_ai_userinterface_history` → `revert_ai_userinterface(to_version=<N-1>)` |

## Reference

- `docs/agent/navigation/AI_USERINTERFACE_MARKDOWN_PACKS.md` — 5-layer model, status, plan
- `docs/agent/AI_USERINTERFACE_example_EXAMPLE.md` — filled-in example-5.02 example
- `setup/db/schema/033_ai_userinterface.sql` + `setup/db/migrations/20260424_*.sql` — DDL
- `shared/src/lib/database/ai_userinterface_db.py` — Python lib (source of truth)
