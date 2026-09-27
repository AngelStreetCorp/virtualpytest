# BUG-0167 — The agent retried a dead browser action every 5 seconds for 40 minutes, and every other chat waited on it in silence

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0167                                                     |
| Reported  | 2026-09-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend / backend_host / agent                               |
| Fixed in  | Unreleased                                                   |
| Commit    | `b660a964d8`                                                  |

---

## Symptom

Agent session `39d2c4e2` (2026-09-27, 14:37 → 15:16 CEST) called `execute_device_action` every
five seconds, 360 times, each call failing identically:

```
❌ 0/1 failed: navigate: RuntimeError: Failed to acquire page from context:
TargetClosedError: BrowserContext.new_page: Target page, context or browser has been closed
```

It only stopped when `stop_generation` was sent by hand. While it ran it took and released the
device lock on every call, made an LLM call per iteration, and — because one agent conversation
is processed at a time per server worker — every other conversation that was sent in that window
received its `Received...` ack and then nothing, for minutes, indistinguishable from BUG-0166
from the user's seat.

## Root cause

**Host:** `PlaywrightController._get_persistent_page` only reconnects when the class-level
`_browser` / `_context` handles are `None`. Once the persistent context has been closed
(Chrome exited, window closed, CDP session dropped), the handles are still set, `context.pages`
/ `context.new_page()` raise `TargetClosedError`, and the method wraps it in a `RuntimeError`
without resetting anything — so the next call fails the same way, forever.

**Agent:** the tool loop in `agent/core/manager.py::process_message` is `while True` with no
cap on iterations or on repeated failures. A tool error is appended as an `is_error` tool
result and the model is asked again; with an error that can never clear, the model just retries.

**Server:** `run_agent_coroutine` takes the per-worker `_agent_processing_lock` silently. A
conversation queued behind a long (or runaway) one gets no event at all until its turn.

## Fix

- `backend_host/src/controllers/web/playwright.py`: when acquiring a page fails, drop the dead
  browser/context handles, `connect_browser()` once and retry; raise only if that also fails.
- `backend_server/src/agent/core/manager.py`: three consecutive identical failures of the same
  tool end the turn with an explicit error event (`repeated_tool_failure`) instead of looping.
- `backend_server/src/routes/server_agent_routes.py`: a conversation that has to wait for the
  processing lock receives a `thinking` event, "Waiting for another conversation to finish...".

## Verification

- Host: close the persistent Chrome (or its context) on a host with a web device, then run any
  web action through the agent or `/host/web/*`. The first call logs
  `Page acquisition failed (...) — dropping dead browser handles and reconnecting` and succeeds
  on the reconnected context.
- Agent: force a tool to fail with a fixed error (e.g. an unknown command); the third identical
  failure yields `Stopping: '<tool>' failed 3 times in a row with the same error` and
  `session_ended`, instead of a fourth call.
- Queueing: send a message from a second chat while a first one is mid-answer; the second shows
  the "Waiting for another conversation" line before its own events.
