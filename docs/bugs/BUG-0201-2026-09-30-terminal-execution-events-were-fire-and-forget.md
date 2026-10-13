# BUG-0201 — The one event a client waits on was posted by a detached thread nobody could hear fail

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0201                                                          |
| Reported  | 2026-09-30                                                        |
| Severity  | Low — reliability/observability hardening, no known live failure   |
| Status    | Fixed (pending deploy)                                            |
| Area      | `backend_host/src/lib/utils/execution_event_utils.py`             |
| Fixed in  | Unreleased                                                        |
| Related   | [BUG-0151](BUG-0151-2026-09-21-host-execution-events-rejected-401-since-server-lockdown.md), [BUG-0199](BUG-0199-2026-09-30-three-more-host-callbacks-swallow-401.md) |
| Commit    | this commit                                                       |

---

## Why

`emit_execution_event` handed **every** event to a detached daemon thread, terminal ones included.
That is the right call for `running`, which is emitted from a request handler that still owes the
caller an HTTP response. It is the wrong call for `completed` / `error` / `failed` / `aborted`: all
19 of those call sites are already inside a background execution thread that is about to exit, so
there is nothing to protect from blocking — and handing the delivery to a thread nobody joins means

- the outcome is not observable where the result was produced,
- the failure line lands outside that run's log capture, after `Log capture completed`,
- and the emit races process teardown.

Two incidents in ten days turned on nobody hearing that POST fail
([BUG-0151](BUG-0151-2026-09-21-host-execution-events-rejected-401-since-server-lockdown.md),
[BUG-0199](BUG-0199-2026-09-30-three-more-host-callbacks-swallow-401.md)). This is the structural
half of that lesson; the status check was the other half.

## Fix

`emit_execution_event` takes `blocking: Optional[bool] = None`:

- `None` (default) → blocking for `TERMINAL_STATUSES`, non-blocking for everything else;
- terminal delivery uses a tighter budget, `_EMIT_BLOCKING_TIMEOUT_SECONDS = 5`, so two attempts
  bound the worst case at ~10.5 s on a thread that is exiting, rather than the fire-and-forget
  path's ~20.5 s;
- any call site can override either default explicitly.

Checked before changing the default: every terminal emit is in a background context. The two that
look like route bodies (`host_actions_routes.py:149/161`) are inside an `async def` driven by
`asyncio.run` in a worker thread, and `host_campaign_routes.py:186` is a `running` emit.

## Verification

`tests/backend_host/test_execution_event_utils.py` — 9 cases, no host or server required
(`requests.post` is replaced, so nothing leaves the process). It pins the contract all three bugs
came from breaking:

| test | pins |
|---|---|
| `test_terminal_event_is_delivered_before_returning` | posted on the caller's thread, before the call returns, with the blocking timeout |
| `test_every_terminal_status_blocks` | all four terminal statuses, parametrised |
| `test_running_event_does_not_block_the_request_handler` | `running` is never posted on the caller's thread |
| `test_credential_is_sent` | `X-API-Key` present — the whole of BUG-0151 |
| `test_rejection_is_logged_and_retried` | a 401 retries once and logs, rather than reading as success |
| `test_blocking_can_be_overridden` | the explicit escape hatch works |

```bash
python -m pytest tests/backend_host/test_execution_event_utils.py -q
```
