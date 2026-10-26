# BUG-0914 — Atlas acts on any device it can list, outside the page's device context

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0914                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High (a drone and a shared host were driven without a lease) |
| Area      | backend / Atlas agent                                        |
| Fixed in  | build 90145 |
| Commit    | —                                                            |

---

## Symptom

During the TASK-172 memory benchmark (2026-10-25, 20:26–20:29 UTC, live node1 server, user
`admin.test@vpt.local`), the harness asked Atlas the owner's prompt **"cap 5"** with only
`host-clone-1/device2` (Phone slot 1) in the page context. Over two turns Atlas:

- called `list_hosts`, then `take_control` on **`host-clone-1/device5` (Tello via phone — a drone)** and
  sent `execute_device_action` → `rotate 30 cw` (no success reported);
- took control of the `host` device of **`host-clone-1`** and of **`labox-web`** (the labox product's
  fleet, off-limits for VPT tests) and ran `execute_bash_command` there: `curl` downloads of its own
  model-output images into `/tmp`, a hand-written `/tmp/view.html`, browser navigations to them.

No vpt-lease was held for any of those devices; `host-clone-1` and `labox-web` had other agents'
tickets waiting. Sessions `6453ba12-…` and `164a524e-…` (`agent_turns` holds every call).

Clean-up done the same evening: all six control locks released through
`/server/control/releaseControl`, the `/tmp/cap5*.jpeg` and `/tmp/view.html` files removed from
`host-clone-1` (none were left on `labox-web`). The drone's state after the `rotate` was not checked
physically.

## Root cause

- The page context (`available_devices`, `selected_server_hosts`) is a hint in the prompt, not a
  boundary: `list_hosts` / `get_device_info` return every host of the server, and `take_control` /
  `execute_device_action` accept any of them.
- An ambiguous prompt ("cap 5") sent the model exploring: it guessed a meaning, found no tool that
  matched, and improvised with `execute_bash_command` on a host.
- The product's device lock (`take_control`) is unrelated to the agents' vpt-lease registry, so a
  free product lock is enough for Atlas even when an agent holds the lease.

## Fix

`backend_server/src/agent/device_scope.py`, checked by `ToolBridge.execute` before any device **action**
(reads such as screenshots, UI dumps, key lists are not gated) for every chat agent:

1. **The page's devices**: when the chat sent its device list, an action on a device outside it is refused
   (the chat's selected Target always counts).
2. **Drones**: a drone tool, or an action on a `tello` device, only when the user named that device or said
   drone / tello / fly … in this message, or it is the selected Target.
3. **Host desktops** (device `host`): only when the user named that host in this message, or it is the
   selected Target.
4. **Shell commands** (`execute_bash_command`): only when the user asked for a command in this message.

A refusal goes back to the model as a tool error with the reason, so it asks the user. Owner approval of
the design: 2026-10-26 (TASK-175 goal 6).

## Verification

`python3 -m pytest -q tests/backend_server/test_device_scope.py` — 12 passed: the incident replayed (the drone
outside the page, the drone rotate, a host desktop, bash on "cap 5": all refused) and what still works
(a named device, the selected Target, "take off the drone", a named host, "run the command df -h", reads). The TASK-172 quality benchmark now runs against a local backend with no hosts
(`scripts/atlas_memory_quality_bench.py`, TASK-172 §8).
