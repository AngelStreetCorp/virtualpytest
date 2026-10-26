# BUG-0313 — Agent chat kept a Target from another server after switching the server picker

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0313                                                     |
| Reported  | 2026-10-04 (real browser, build 9777)                        |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium - messages went to a host the selected server does not own                                                        |
| Area      | `frontend/src/pages/AgentChat.tsx`, `frontend/src/hooks/aiagent/useAgentChat.ts`                                                       |
| Fixed in  | build 90145 |
| Commit    | `c92efe050e`                                                     |

---

## Symptom

On /ai-agent, switching the top-bar server picker from the main server to RPI1-server left the chat toolbar's Target on `host-clone-1:host` (a main-server device). That host and device were sent with every `send_message`, next to `selected_server_hosts` that did not contain it.

## Root cause

The Target is local page state, auto-selected once from `getAllHosts()`, which spans every server. Nothing reacted to a server change, and the send path forwarded the ref's host unchecked.

## Fix

AgentChat clears a Target whose host is not in the selected server's hosts and re-runs the first-device default, restricted to that server's hosts; the Target dropdown lists only that server's devices. `useAgentChat` sends `host_name`/`device_id` only when the host is in `selected_server_hosts`.

## Verification

Vitest `tests/frontend/AgentChat.test.tsx` (switch server, Target moves from `host-clone-1:device1` to `rpi1-host:device1`); `tsc --noEmit` clean.

### 2026-10-20 — red CI was a stale test, not a regression

"Frontend Component Tests" failed this test on main (655 tests, 1 failed). The drop logic was never broken: the
server-switch effect in `AgentChat.tsx` is byte-identical before and after `59a31f0fd`. That commit replaced the
Target's MUI `Select` with the shared `Button` + `Popover` (`TargetDropdown.tsx`), so the test's
`input.MuiSelect-nativeInput` query no longer matched anything and the Target read back as `undefined`. The test now
reads the trigger button's label (`<device> - <host>`), and still fails if the drop logic is disabled.
