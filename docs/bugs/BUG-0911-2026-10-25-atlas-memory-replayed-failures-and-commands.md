# BUG-0911 — Atlas memory replayed failed answers and recalled device commands

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0911                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (the memory is off everywhere, so no user hit it)     |
| Area      | backend / Atlas agent                                        |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

A review of the TASK-172 prototype (memory switched on, `ATLAS_MEMORY=on`) found that:

1. A turn that produced nothing was remembered and replayed for 14 days: "I don't understand 'cap 5'",
   a clarifying question, `manage_script failed: …`. All four recalls in the TASK-172 benchmark were
   such non-answers.
2. "send cmd to stb" was answered from the memory: the command was not sent, the user got the old
   result.
3. The recall says "say 'again' to run it now", but nothing handled "again", and asking the same
   question again hit the memory again.
4. The 90-day retention never ran: `memory.prune()` had no caller.
5. The default tree `<repo>/data/atlas_memory` was inside the git checkout and not gitignored.

## Root cause

- `memory_step.record_turn` wrote every turn that had a user id, whatever its tools returned; the
  quick-step write passed no success flag.
- `memory_step.step` checked only the FAQ hot cache, not whether the message was a live operation.
  The FAQ's own `should_decline` is too broad to reuse as is: it declines every short command,
  "create a script" included.
- No session state remembered that a question had just been recalled.
- `prune()` was written but never wired.
- `_DEFAULT_ROOT` was computed from the module path.

## Fix

- `memory_step.record_turn` writes only when at least one call succeeded (`_call_succeeded`) and
  leaves failed calls out; the quick step passes `success: ok`.
- `memory_step.is_live_operation`: a command or a live-state question that names a device or host,
  or running a script / campaign / test, is never answered from the memory. Fails closed.
- `memory_step.resolve_rerun` turns "again" (and close variants) after a recall into the recalled
  question, also in the session history; a key already recalled in the session is a miss.
  Wired in `manager.py` before the memory step.
- `memory.record` prunes on the first write of each new day file; `RETENTION_DAYS` is 30 (owner).
- Default root `~/.virtualpytest/atlas_memory`; `data/atlas_memory/` is gitignored.
- On demand (owner): `ATLAS_MEMORY=optin` runs the memory only for users with an `.enabled` marker,
  written by `memory.set_enabled()`.

### Found by the quality benchmark (TASK-172 §8), fixed before its full run

- A turn that only looked (`get_` / `list_` / `search_` / `read_` … tools) was saved — "cap 5" read
  the docs and an empty transcript. Now not saved (`memory_step.is_read_only_tool`).
- A recall named a script the model had only read as a template: artefacts now come only from the
  tools that acted.
- "create a user interface … for an android_tv device" was never recalled: a create is not a live
  operation unless it also asks to run something.
- A created script / userinterface entry named nothing: ids are read from the tool's text answer.

## Verification

`python3 -m pytest -q tests/backend_server/test_atlas_memory.py` — 59 passed, including one test per
fix above. Live behaviour is unchanged: `ATLAS_MEMORY` is unset on every server.
