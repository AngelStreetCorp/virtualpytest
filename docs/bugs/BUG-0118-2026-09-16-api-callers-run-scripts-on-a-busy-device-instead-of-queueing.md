# BUG-0118 — An API caller's scripts all run at once on a busy device; the browser's get queued

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                              |
|-----------|----------------------------------------------------------------------------------------------------|
| ID        | BUG-0118                                                                                             |
| Reported  | 2026-09-16                                                                                           |
| Status    | **Fixed (pending deploy).**                                                                          |
| Severity  | High (any external scheduler or API integration firing more than one script at a device)            |
| Area      | `backend_server/src/lib/utils/lock_utils.py`, `backend_server/src/routes/server_script_routes.py`, `backend_server/src/routes/server_deployment_routes.py`, `frontend/src/hooks/script/useScript.ts` |
| Fixed in  | build 9151                                                                                                                                                                                           |

---

## Symptom

An external scheduler fired a test matrix through `POST /server/script/execute` — six scripts per
host, all on `--device host`, two to six seconds apart. Every one of them started immediately and
ran **concurrently on the same device**: twenty `Payload:` lines in the server journal inside
forty seconds, zero `device_locked` refusals. Two of the six drive a browser, so they tore each
other down (that half is BUG-0114); the rest simply ran on top of each other.

The same six scripts launched from the Run Tests page behave correctly: the first runs, the rest
show **Queued** and start one by one as the device frees up.

## Root cause

The server never queues anything. The "Queued" a browser user sees is the **frontend** reacting
to a refusal: `RunTests.tsx` fires the batch in parallel, the first call wins the device lock, the
others get `423 device_locked`, and `queueScriptExecutionFallback` turns each into a one-shot
deployment (`cron '0 0 1 1 *'`, `max_executions 1`) that the host's deployment scheduler queues
per device.

Whether the server *refuses* depended on a fork in `DeviceLockManager.acquire_lock` that nobody
designed, when a `script_execution` lock is already held:

| second script arrives from…                | result                                                    |
|--------------------------------------------|-----------------------------------------------------------|
| same session, same user, new task          | `device_locked` 423 → the browser queues it               |
| **different session, same user**           | **takes over the running script's lock, dispatches**      |
| different user                             | `device_locked` 423                                       |

`/server/script/execute` passes `allow_same_user_takeover=True`, and the manager's
"same user, existing lock is `script_execution`" branch superseded the running run and returned
success. A browser tab keeps one session cookie, so it lands in row 1. An API caller has no
cookie jar: Flask mints a fresh session id per request, every call is "a different session, the
same user", and every call takes over the one before it. Row 2, twenty times.

The takeover has been there since the initial snapshot with no report justifying it. The one
legitimate use — "my own run is stuck, take it over" — already has an explicit `force_unlock`
flag on the route.

## Fix

**A running script's lock is never taken over implicitly** (`lock_utils.py`). The
`script_execution → script_execution` same-user branch is gone; that case now falls through to
`device_locked` like every other conflict. The `manual_control` umbrella (a user who holds
control runs a script under it) is untouched, and `force_unlock=true` remains the explicit way to
take a stuck run over.

**The server queues, so every caller gets what the browser gets** (`server_script_routes.py`).
On a lock conflict the route now does what the frontend's fallback did: it creates the one-shot
deployment itself — through `create_deployment_record`, the body of `/server/deployments/create`
extracted so both paths share it — and answers `202 {success: true, queued: true, task_id,
deployment_id}`. The `task_id` stays open; when the queued run finishes,
`/server/deployments/executionComplete` completes it with the run's real result
(`report_url`, `script_success`, …), read back from `rerun_payload.queued_task_id`. An API caller
polling `/server/script/status/<task_id>` cannot tell "ran now" from "ran when the device freed
up". A queued run that never happens resolves the task too — the abort button completes it with
`aborted`, the stale-queue sweep with `stale_queue_timeout` — because tasks never expire on their
own and a caller must not be left polling something nothing will complete. If creating the
deployment fails, the route returns the 423 it always did.

**The browser understands the new answer** (`useScript.ts`, `RunTests.tsx`). A `queued` reply
returns at once instead of waiting on the task; the page drops its local row and refreshes the
deployment feed, which carries the queued run from there. Its own 423 fallback stays for older
servers. The rerun button, which is run-now only, sends `queue_if_locked: false` and keeps
getting the 423.

## Verification

- `DeviceLockManager`, driven directly: first script acquires; same user from a second session →
  `device_locked` (was `success` before); same session → `device_locked`; the lock still names the
  first task; a script under the user's own manual control still returns `subordinate: true`.
- `create_deployment` delegates to the extracted helper and `execution_complete` completes the
  queued task — checked by importing the module.
- Frontend: `tsc --noEmit` clean, `eslint` clean on both files.
- End-to-end: the external scheduler's next cycle must show, per device, one `Payload:` followed
  by `queued … as deployment` lines in the server journal, `QUEUED:` lines in the host's
  `deployments.log`, and the scripts completing one after another.

## Not fixed here

**Campaigns.** `/server/campaigns/execute` passes the same flag and used to take over the same
way; it now gets the 423 instead, which is strictly better, but the server does not queue a
campaign yet and the page has no campaign fallback — a campaign started while that user's script
runs shows an error. Same treatment, separate change.

**A leaked script lock is no longer papered over.** A run that dies without its completion
callback used to be silently superseded by the same user's next run; now that next run is queued
behind it until the lock is cleared. The host route guarantees the callback on every exit path
and `force_unlock` covers the rest, but a lock that does leak is now visible instead of hidden.
