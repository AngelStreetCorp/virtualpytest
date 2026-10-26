# BUG-0682 — Build Map (auto-discover) froze vpt-host: asyncio.run on the gevent request greenlet

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0682                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / ai_exploration                                |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

A Build Map call (`POST /host/ai-generation/auto-discover-screen`, MCP `auto_discover_screen`) from the TASK-135 baseline on
host-clone-2 (2026-10-19 11:57 UTC) froze vpt-host. It stopped accepting connections (listen backlog 129/128) for 30 min,
until the service was restarted by hand. The MCP caller saw `Request timeout (30s)`, and every other request to that host
hung, stream playlists included.

## Root cause

vpt-host serves Flask-SocketIO on gevent **without monkey patching** (see `backend_host/src/lib/utils/gevent_utils.py`). The
exploration steps drive the device through bare `asyncio.run(...)` in `services/ai_exploration/phases/validation_runner.py`.
In the wedge this was the "PROACTIVE RECOVERY go home" `execute_navigation` after a failed click/back. Run directly in the
route, that `asyncio.run` blocks the main thread in a real `select()` while the Playwright work it waits for runs on the
PlaywrightControllerLoop thread. The gevent hub on the main thread is frozen, so nothing else is served
(py-spy of the wedged process: `host_ai_exploration_routes.py:502 → exploration_executor.py:820/580 →
validation_runner.py:1338`). `/start-exploration` was fine: it already runs in a `threading.Thread`, which is a real OS thread
here.

## Fix

`backend_host/src/routes/host_ai_exploration_routes.py`: every route that drives the device synchronously (`/init`, `/next`,
`/continue-exploration`, `/start-validation`, `/validate-next-item`, `/start-node-verification`,
`/approve-node-verifications`, `/auto-discover-screen`) now calls the executor through `off_hub()` (BUG-0511/0512 helper). The
work runs on an OS thread of the hub's threadpool and the request greenlet waits cooperatively, so every `asyncio.run`
below it (validation_runner lines 42-1338) no longer blocks the hub. Status, cancel and cleanup routes do no device I/O
and are unchanged.

## Verification

After deploy: start Build Map on a web host and, while it runs, `curl /host/system/health` on the same host answers
at once. The auto-discover call returns its result instead of freezing the host.
