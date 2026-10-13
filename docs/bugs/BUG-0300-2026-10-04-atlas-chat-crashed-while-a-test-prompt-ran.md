# BUG-0300 — An Atlas chat started while a Test Prompt run was active crashed instead of waiting

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0300                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — the chat turn never finished ("No response from agent") |
| Area      | `backend_server/src/agent/async_utils.py`, `server_agent_routes.py`, `agent/core/manager.py`, `features/ai-test/backend_server/server_testprompt_routes.py` |
| Fixed in  | Unreleased                                                   |
| Commit    | `04cd29529`                                                       |

---

## Symptom

On the Pi-hosted server, an Atlas chat sent while a Test Prompt exploration was running showed
*Agent task failed to start: asyncio.run() cannot be called from a running event loop* and never
answered (2 of 3 first turns in one browser test run). The server log showed the exploration
(`[@testprompt:agent]`) active at that moment.

## Root cause

Same family as BUG-0126. Under gevent every request and background job is a greenlet in one OS
thread, and asyncio's "a loop is running" flag is per OS thread. Atlas chats were queued among
themselves by a lock, but the Test Prompt exploration, the agent background queue, the approval
route and the `run_async` route helper started their own loops beside them, so whichever started
second failed.

## Fix

Every event loop in the server worker goes through one gate, `agent.async_utils.run_in_worker_loop`
(a process-wide lock shared by both import paths of the module). A chat that has to wait is told
*Waiting for another conversation to finish...*; a nested call fails fast instead of deadlocking.
Test Prompt's time limit now starts when its run gets the loop, not while it waits. (The Slack
events handler imports modules that no longer exist and never reaches its loop; untouched.)

## Verification

- `tests/backend_server/test_worker_loop_gate.py`: under real gevent, two plain `asyncio.run`
  greenlets reproduce the crash; through the gate they run one after the other; both import paths
  share the gate; the waiting caller is told; nested use raises.
- Live on the Pi server, build 9751: an Atlas chat sent during a Test Prompt exploration showed
  "Waiting for another conversation to finish...", and answered 3 s after the exploration ended,
  with no event-loop error in the server log.
