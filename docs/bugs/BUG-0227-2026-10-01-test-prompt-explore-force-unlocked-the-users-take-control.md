# BUG-0227 — Test Prompt: Explore took the device away from the user who ran it

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0227                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed — deployed and verified 2026-10-01                     |
| Severity  | High — after any exploration the user no longer holds the device, though the page still shows Release; the next run is refused, and another user can take the device |
| Area      | `features/ai-test/skills/test-prompt-{web,mobile,androidtv,stb}/SKILL.md` |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

On `/test-prompt` (host-clone-1, 2026-10-01 16:11 UTC) an Explore run passed. The very next
**Run graph** was refused with `409 take_control_required` and `lock_info: null`, while the
page still showed the device under the user's control (Release button). Run graph on its own,
before any Explore, passed.

## Root cause

Each `test-prompt-*` skill told the agent to "ALWAYS include `force_unlock: true`" in
`execute_device_action`. The MCP tool (`backend_server/src/mcp/tools/action_tools.py`,
`_auto_lock`) treats `force_unlock` on a `manual_control` lock as an explicit override. It
calls `/server/control/forceUnlock`, takes the device under its own `mcp-action-…` session,
and releases it after the call. Server log of the run: `Force unlocking device:
host-clone-1:host` on the agent's first `dump_elements`, then `Releasing control … (session:
mcp-action-…)` after every call. Without `force_unlock`, the same tool piggybacks on the
user's `manual_control` lock and never releases it. That is what TASK-36 phase 1 relies on,
since a Test Prompt run already requires the user's Take Control.

## Fix

The four skills no longer ask for `force_unlock`. Rule 4 now says never to pass it, and why.

## Verification

- After a server deploy: Explore, then Run graph, from the page on host-clone-1. The graph run
  must start (no 409), and the server log must show no `Force unlocking` during the
  exploration (TASK-36 task doc §2.7).
