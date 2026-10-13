# BUG-0402 — An Atlas test chat took a phone another agent was using

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                 |
|-----------|-----------------------------------------------------------------------|
| ID        | BUG-0402                                                              |
| Reported  | 2026-10-05                                                            |
| Status    | Closed                                                                |
| Severity  | Medium                                                                |
| Area      | scripts/atlas_chat.py + backend_server MCP `take_control`             |
| Fixed in  | Unreleased                                                            |
| Commit    | `b0431508ec`, `da9b5ffa1c`, `776c289d6`                               |

---

## Symptom

2026-10-04 14:27 UTC: an Atlas chat started by a TASK-43 worker with
`scripts/atlas_chat.py --host vpt-pi1 --device device1` took control of the phone while another
agent (TASK-28, video recording) was using it and held a vpt-lease on it.

## Root cause

Two things, from the lock history in `device_control_sessions` (the vpt-pi1 server's journal for
that day has already rotated away):

1. **The recording agent never held a product lock.** Rows for vpt-pi1/device1 from 14:00 to 14:30
   UTC: `codebox-task40` 14:13:19–14:16:23 (expired), then three `atlas_chat` locks
   (`ff677c17…` 14:21:02–14:24:09, `e064c6e9…` 14:26:02–14:27:28, `268708de…` 14:27:30–14:29:00),
   then a browser lock at 14:29:31. No row overlaps another and none ends with
   `end_reason='takeover'`, so at 14:27:30 there was no lock on the device for any take-control
   to see. The other agent drove the phone directly and was visible only in vpt-lease.
2. **Atlas test chats took the device by force anyway.** `atlas_chat.py` called
   `POST /server/control/takeover` with `stop_running_execution=true` — the browser's
   user-confirmed force path, which preempts another session's manual lock and stops a running
   script — and kept chatting when that call failed. Had the other agent held a lock, the chat
   would have taken it from them. The MCP `take_control` tool had the same default for executions:
   `allow_takeover` defaulted to true, so a running script was stopped and taken over silently.

Atlas's own device tools do go through the normal lock (`/server/control/takeControl`, in-memory
`DeviceLockManager` + `device_control_sessions` history); identity was not reused.

## Fix

- `scripts/atlas_chat.py`: takes control with `POST /server/control/takeControl` (the same lock as
  the web UI) and exits 3 with the holder when the server answers 423. It never calls `/takeover`.
- `backend_server/src/mcp/tools/control_tools.py`: `take_control` falls back to `/takeover` only on
  an explicit `allow_takeover=true`; otherwise the conflict is returned.
- `docs/agent/devices/DEVICE_LOCK.md`: agents never force; a device driven without a lock is
  invisible to take-control; the stale "takeover refuses manual locks" row is corrected.

Not changed (proposal): agents that drive a device directly should hold a product lock for the
whole session — `takeControl` with a stable `session_id` and a keep-alive (repeat `takeControl`
under 3 min), or `acquireExecutionLock` with an agent owner type — so the UI, Atlas and other
agents see them. Separately, the MCP execution tools' `_auto_lock` piggybacked on any
`manual_control` lock, not only the caller's — closed below.

### Remaining gap closed: MCP device tools use only the caller's own lock (2026-10-05)

`execute_device_action` and `navigate_to_node` (`_auto_lock`) and `execute_testcase` ran under
**any** `manual_control` lock, so an Atlas chat or MCP client could drive a device someone else
had taken control of; `force_unlock=true` even cleared that person's control with
`/forceUnlock`. Now:

- `backend_server/src/mcp/utils/lock_ownership.py` (`auto_lock`, shared by both tools): takes
  control under the caller's own session; a 423 is used only when the lock is the caller's
  (same session, the chat's browser tab, or the same signed-in user), otherwise it returns
  `device_locked` naming the holder. `force_unlock` only stops a running script/testcase/
  deployment, never a Take Control. The per-instance "already hold it" shortcut, which let any
  concurrent caller ride another call's lock, is gone.
- `execute_testcase` retries with the lock's session only when the lock is the caller's.
- Identity: `tool_bridge.py` sets `session_id` (chat session), `_caller_browser_session_id` and
  `_caller_user_id` (none for shared principals) on the device tools, overriding the model;
  the web app sends `browser_session_id` with every Atlas message (`SocketContext.tsx`), stored
  on the session by `server_agent_routes.py`. A plain MCP client is its `session_id`, or the
  session its own `take_control` opened (`control_tools.py` no longer reuses a chat's session
  for another caller).

## Verification

`python3 -m pytest tests/backend_server/test_mcp_auto_lock_owner.py` — 11 pass; the
`execute_device_action` one fails on the previous code (it drove the device under Alice's lock).

`python3 -m pytest tests/backend_server/test_take_control_never_steals.py` — 4 pass; 3 of them fail
on the previous code (takeover URL, chat continues on 423, MCP silent takeover).

### Live check (2026-10-05, node1, server main-2026.10.05-10036) — not closed

Browser took control of host-clone-1/host (`manual_control`, user "Auto Signed"), then MCP without `allow_takeover`:

- `execute_device_action`: refused, `Device 'host' on host 'host-clone-1' is in use by Auto Signed (manual_control). Not taking it over ...` — correct.
- `take_control`: refused and did not steal (the browser lock was still in place afterwards), but the answer is only
  `Error [backend_error]: Device host-clone-1:host is locked` — it does not name the holder. `control_tools.take_control`
  passes the 423 result to `format_api_response`, which keeps only `error` and drops `lock_info`
  (`owner_user_name`, `owner_type`). Open: say who holds the device in the `take_control` conflict, as `auto_lock` does.

### Holder named in the `take_control` conflict (2026-10-05)

`control_tools.take_control` now builds its own answer for a `device_locked` result instead of
passing it to `format_api_response`: `Device '<device>' on host '<host>' is in use by <holder>
(<owner type>). Not taking it over - wait until they release it or ask them to.`, using the same
`holder()` helper as `auto_lock` (reads `owner_user_name` top-level or in `lock_info`), with
`errorType: device_locked`. For an execution lock it adds "retry with allow_takeover=true".
`test_mcp_take_control_conflict_names_the_holder` in `tests/backend_server/test_take_control_never_steals.py`
uses the live 423 shape (holder only in `lock_info`) and fails on the previous code. Pending deploy
and a live re-check on node1.



## Live check on node1 (2026-10-05, server main-2026.10.05-10046)

One session took control of labox-dongle/device1 through `/server/control/takeControl` (user `VerifyHolderA`). MCP `take_control` on the same device then answered "Device 'device1' on host 'labox-dongle' is in use by VerifyHolderA (manual_control). Not taking it over - wait until they release it or ask them to.", and the lock stayed with the first session. `execute_device_action` had already refused the same way on build 10036.
