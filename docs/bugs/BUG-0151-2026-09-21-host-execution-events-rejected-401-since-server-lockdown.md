# BUG-0151 — Every async execution waited 2 minutes: the host's completion events were 401'd in silence

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                 |
|-----------|-----------------------------------------------------------------------|
| ID        | BUG-0151                                                              |
| Reported  | 2026-09-21                                                            |
| Status    | Fixed (pending deploy)                                                |
| Severity  | High (every async execution on every host took ≥120s in the UI)       |
| Area      | `backend_host/src/lib/utils/execution_event_utils.py`                 |
| Fixed in  | Unreleased                                                            |
| Regression of | `be7dfa7c95` (2026-09-07)                                         |
| Commit    | `d6f0ff0f28`                                                          |

---

## Symptom

A `goto` to a node the device was **already on** reported **"Navigation succeeded in 2m:00s"**,
with the UI's own ETA reading 9.55s. Always almost exactly 2m:00s, on any host, for navigation,
actions, verifications, campaigns and testcases alike.

## Cause

`be7dfa7c95` ("/server/* closed by default — require a credential") made every host → server call
need a credential. Three of the four were updated to send `server_auth_headers()`:

| call | file | updated |
|---|---|---|
| register | `host_utils.py:352` | ✅ |
| ping | `host_utils.py:686` | ✅ |
| unregister | `host_utils.py:794` | ✅ |
| **execution events** | `execution_event_utils.py:27` | ❌ **missed** |

So `POST /server/system/executionEvent` has answered **401** ever since, and the server never
rebroadcast the event.

**It failed silently because of a second flaw in the same function.** `_post_with_retry` caught
only *exceptions*, and a 401 is a perfectly valid `requests` **response**:

```python
requests.post(url, json=payload, timeout=_EMIT_TIMEOUT_SECONDS)
return                      # ← 401 lands here, indistinguishable from success
```

No log line, no retry, no error — the event was simply dropped.

The frontend then behaved exactly as designed
(`frontend/src/utils/navigationExecutionUtils.ts:180`):

```js
waitForExecutionSocketEvent(executionId, ['navigation'], 120000)   // socket event that never comes
  ?? await pollExecutionStatus()                                    // fallback, instantly "completed"
```

It waited the full **120 000 ms** for an event that could never arrive, then fell back to polling
and immediately saw `completed` — because the work had finished long before. Hence the constant,
suspiciously round 2m:00s.

## Measured on vpt-pi1 (2026-09-21)

```
20:03:49.943  server → POST /host/navigation/execute/…
20:03:49.948  server ← success=True            (4.7 ms; async, returns an execution id)
20:03:49.948  host   → execute_navigation begins
20:03:53.201  host   ✅ Already at target      ← real work: 3.25 s
     … 120 s of the UI waiting on an event that was 401'd …
20:05:50.091  server → first get_status poll   ← +120.1 s
              UI: "Navigation succeeded in 2m:00s"
```

## Fix

Send the credential, like the three sibling calls, **and** treat a rejected POST as a failure:

```python
response = requests.post(url, json=payload, headers=server_auth_headers(), timeout=...)
if response.status_code < 400:
    return
last_exc = RuntimeError(f"server answered {response.status_code}: {response.text[:200]}")
```

The status check matters as much as the header. Without it the next credential change degrades
every execution to a 120 s wait again, with nothing in any log to say so.

## Verification

On vpt-pi1, emitting through the real host helper with the host `.env` loaded:

```
before : POST /server/system/executionEvent → 401,  socket events received: 0
after  : POST → 200,  socket events received: 1
         {type: execution_update, execution_type: navigation,
          execution_id: VERIFY-FIX-4, status: completed, progress: 100}
```

That is exactly the payload shape `executionSocketWait()` matches on.

## Blast radius

`emit_execution_event` is the single emitter for every async execution type:

```
host_navigation_routes.py   host_actions_routes.py     host_builder_routes.py
host_campaign_routes.py     host_verification_routes.py  testcase_executor.py
```

So since 2026-09-07 **every** async execution on **every** host has fallen back to the 120 s
timeout. The system stayed functionally correct — polling always resolved it — which is why this
read as general sluggishness rather than a fault.
