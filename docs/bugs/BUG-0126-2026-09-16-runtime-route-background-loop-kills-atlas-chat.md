# BUG-0126 — One 404 on an agent-runtime route kills Atlas chat for the life of the worker

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0126                                                                    |
| Reported  | 2026-09-16                                                                  |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | High (Atlas chat is dead server-wide until someone restarts `vpt-server`, and the UI reports nothing) |
| Area      | `backend_server/src/agent/async_utils.py`, `backend_server/src/routes/server_agent_routes.py` |
| Fixed in  | build 9151                                                                  |
| Commit    | `4002680226`                                                                |

---

## Symptom

Sending any message in Atlas chat shows the "Received..." acknowledgement and then nothing —
no answer, no error, no end of turn. The conversation hangs until the frontend's 90 s stall
timeout unsticks it, and every retry behaves identically, in every conversation, for every user.
Restarting `vpt-server` fixes it until the next time it happens.

The only trace is in the server journal, once per message:

```
File "…/routes/server_agent_routes.py", line 659, in <lambda>
    lambda: run_agent_coroutine(process_and_stream)
File "…/routes/server_agent_routes.py", line 134, in run_agent_coroutine
    asyncio.run(coro_factory())
RuntimeError: asyncio.run() cannot be called from a running event loop
```

Nothing correlates it with a user action, because the request that breaks the server is not a
chat request and happens minutes or hours earlier.

## Root cause

Two defects stacked.

**1. A background event loop that flags the whole worker.** `run_async()` in
`agent/async_utils.py` submitted its coroutine to a process-wide loop kept alive by
`loop.run_forever()` in a `threading.Thread`. `app.py` calls `gevent.monkey.patch_all()`, so
that "thread" is a greenlet inside the single gunicorn gevent worker's one OS thread — and
asyncio records *"a loop is running"* per OS thread. From the first `run_async()` call onward,
the entire worker counted as being inside a running loop, permanently.

It stays invisible because `patch_all()` removes `select.epoll`, so asyncio falls back to the
gevent-patched `select.select`: the forever-loop parks cooperatively and the worker keeps
serving every other request normally.

Every `asyncio.run()` in that worker then fails — and Atlas chat runs each message through
`asyncio.run()` in `run_agent_coroutine`.

The trigger is any route that calls `run_async`, the cheapest being
`POST /server/runtime/instances/<id>/stop`: it calls `run_async(runtime.stop_agent(...))`
*before* checking the instance exists, so even a 404 starts the loop. `tests/backend_server/
test_agent_runtime.py` posts exactly that to a nonexistent instance, and the regression suite
runs against the deployed server on every push — so CI killed chat on production routinely.
The journal on `.103` holds **no** successful agent event in its whole retained window
(2026‑08‑26 onward).

**2. The failure is silent.** `run_agent_coroutine` runs in a detached background greenlet.
The `RuntimeError` propagated out of it, gevent printed the traceback and dropped it, and the
conversation was never told: no `error`, no `session_ended`. A dead backend turn is
indistinguishable in the UI from a slow one.

## Fix

`4002680226`.

`agent/async_utils.py` — `run_async` now runs one loop per call inside the calling greenlet and
tears it down before returning, so no loop outlives a request:

```python
return asyncio.run(asyncio.wait_for(coro, timeout=_RUN_ASYNC_TIMEOUT))
```

`get_or_create_event_loop()` and the module's loop globals are gone; nothing else imported them.
A real OS thread for the loop was tried first and rejected: `concurrent.futures.Future.result()`
waits on gevent-patched primitives, which a foreign thread cannot reliably wake.

Trade-off, deliberate: tasks a coroutine spawns with `asyncio.create_task` no longer outlive the
request that created them. That only touches `POST /server/runtime/instances/start`, whose agent
instances need their own supervisor to survive a request in any case; the runtime is not started
on this deployment (`No agents with background_queues configured` at boot, `list_instances`
returns 0).

`routes/server_agent_routes.py` — `run_agent_coroutine` now catches whatever its greenlet raises
and closes the turn on the session room (`error` then `session_ended`), so a backend crash
surfaces as a failed message instead of a conversation that hangs forever.

## Verification

On `.103`, with `scripts/atlas_chat.py` against the deployed server:

1. `sudo systemctl restart vpt-server` → chat answers normally (`session_ended | Done`).
2. One request: `curl -X POST …/server/runtime/instances/__nonexistent__/stop` → `HTTP 404`.
3. Chat again → `Received...` and nothing else; journal shows the `RuntimeError`.

That is the whole reproduction — a single 404, no agent involvement.

The loop fix was checked in an isolated `monkey.patch_all()` process: after two `run_async()`
calls the thread's running-loop is `None` and `asyncio.run()` still works, where the old
implementation left it set after the first call.
