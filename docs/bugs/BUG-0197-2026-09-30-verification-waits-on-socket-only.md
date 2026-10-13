# BUG-0197 — Verification always timed out where the host's execution-event callback fails, because it was the one flow with no polling fallback

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0197                                                                    |
| Reported  | 2026-09-30 (a customer install)                                             |
| Severity  | High — every verification run from the editor fails, nothing can be checked |
| Status    | Fixed (pending deploy)                                                      |
| Area      | frontend / verification                                                     |
| Fixed in  | Unreleased                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

Running a verification from the Navigation editor always ends in a timeout, while actions and
navigation on the same host work:

```
[useVerification] Batch test result: {execution_id: '79589734-…', message: 'Verification execution started', success: true}
[useVerification] ✅ Async execution started: 79589734-…
[useVerification] Socket wait timeout(ms): 25000
[useVerification] Error during verification test: Error: Execution timeout for 79589734-…
```

`POST /server/verification/executeBatch` answers **200** with an `execution_id`, so the run did
start on the host. The result never arrives.

## Root cause

Two things, and only together do they produce this.

**1. The execution event never reaches the browser (install-specific).** Async results travel
host → server → browser: the host POSTs to `/server/system/executionEvent`
(`backend_host/src/lib/utils/execution_event_utils.py:95`) and the server rebroadcasts on the
`/system` socket (`server_system_routes.py:1950`). When that POST fails the event is simply
never broadcast. `_post_with_retry` already documents the exact failure mode from a previous
occurrence — *"/server/* requires a credential … Without it the server answers 401, and because
that is a response rather than an exception it used to be swallowed here"* — and it now logs
`[@execution_event_utils] Failed to emit execution event after retry:`.

The browser side was healthy: the thrown error is the bare `Execution timeout for <id>` and
**not** the `; last socket error: …` variant, so `lastConnectError` was never set
(`executionSocketWait.ts:52`) — the `/system` socket connected, it just had nothing to deliver.
`workers: 1` (`gunicorn_app.py:183`) rules out a broadcast landing in another worker.

**2. Verification was the only flow that waits on the socket alone (ours).** Every sibling
already treats the socket as best-effort and guarantees completion by polling the host's status
endpoint:

- `useAction.ts:276` — `Promise.race([waitForExecutionSocketEvent(...), pollExecutionStatus()])`,
  commented *"Socket is primary; status polling guarantees completion if socket event is missed."*
- `navigationExecutionUtils.ts:189` — `(await socketWaitPromise) ?? (await pollExecutionStatus())`

`useVerification.ts` awaited `waitForExecutionSocketEvent` and nothing else, so on an install
where the callback is broken it could only ever time out — which is why verification failed
100% of the time while actions and navigation still completed.

The host has had the endpoint all along
(`GET /host/verification/execution/<execution_id>/status`,
`host_verification_routes.py:220`, backed by `VerificationExecutor.get_execution_status`, which
reports `running` / `completed` / `error` plus the result), auto-proxied as
`/server/verification/execution/<id>/status`. Nothing needed adding on the host.

## Fix

`frontend/src/hooks/verification/useVerification.ts` races the socket wait against a 1 s status
poll, the `useAction` pattern:

- polling owns the deadline (socket budget + 30 s slack), so a dead socket costs one poll
  interval rather than the whole 20–300 s budget;
- `device_id` is sent explicitly — the host route defaults to `'device1'` when it is absent,
  which would read another device's execution store on a multi-device host;
- the losing promise is aborted through one `AbortController` and its rejection swallowed, so it
  cannot surface as an unhandled rejection;
- falling back is logged once (`resolved by status polling (socket issue: …)`) instead of passing
  silently — a run that only succeeds via polling still means the event callback is broken.

This makes verification survive a broken callback. It does **not** fix the callback: on the
affected install, `[@execution_event_utils] Failed to emit execution event after retry:` in the
host log names the real cause (401 → the host's server credential; a connection error →
`SERVER_URL` unreachable from the host), and until that is fixed every async flow pays its poll
interval instead of being event-driven.

## Verification

- Socket healthy: verification still completes on the socket event, no polling warning.
- Socket starved (callback failing): the run completes ~1 s after the host finishes, and the
  console carries one `resolved by status polling (socket issue: …)` warning.
- `device_id` is present in the status URL for a host with several devices.
