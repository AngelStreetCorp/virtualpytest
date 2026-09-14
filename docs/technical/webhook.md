# Webhook + WebSocket Completion Contract

This document describes the current, implemented completion model for script and deployment execution.

## Summary

- Frontend/internal clients should use Socket.IO `/system` events (push model).
- External systems can pass `callback_url` and receive completion webhooks.
- Fallback status polling endpoints can remain for compatibility, but are no longer the primary flow.

## Compatibility Policy (Important)

During migration, keep legacy status endpoints enabled to avoid regressions if any client misses a socket/webhook event.

- Primary path: socket/webhook completion.
- Fallback path: status endpoints.
- Removal criteria: remove status endpoints only after all known clients have migrated and monitoring shows no fallback usage for a full release window.

## Implemented Components

- Completion helper: `backend_server/src/lib/utils/completion_notifier.py`
  - `notify_completion(payload, callback_url=None, emit_only=False)`
  - Emits:
    - `deployment_execution_changed`
    - `execution_update`
  - Optionally POSTs to external `callback_url`.

- Script completion route: `POST /server/script/taskComplete`
  - Completes task in task manager.
  - Calls `notify_completion(...)`.

- Deployment completion route: `POST /server/deployment/executionComplete`
  - Receives host scheduler completion payload.
  - Calls `notify_completion(...)`.

- Host scheduler integration:
  - `backend_host/src/services/deployment_scheduler.py`
  - Sends completion callback to `/server/deployment/executionComplete` for success and failure.

## WebSocket Contract (`/system`)

### `execution_update`

Used by execution waiters (`waitForExecutionSocketEvent`).

Common fields:
- `type`: `"execution_update"`
- `execution_type`: e.g. `"script"`, `"deployment"`, `"testcase"`, `"action"`, `"verification"`, `"navigation"`, `"builder"`
- `execution_id`: task/execution id
- `status`: `"running"`, `"completed"`, `"failed"`, `"error"` (domain dependent)
- `host_name`, `device_id`, `team_id` (optional)
- `result`, `error`, `timestamp`

### `deployment_execution_changed`

Deployment-facing event for existing listeners.

Common fields:
- `domain`: `"deployment"`
- `action`: e.g. `"script_task_complete"`, `"deployment_execution_complete"`
- `task_id` or `execution_id`
- `deployment_id` (if applicable)
- `success`, `status`, `result`, `error`, `timestamp`

## External Webhook Contract (`callback_url`)

When `callback_url` is provided, server resolves it as:

- Absolute `http/https` URL: used as-is.
- Relative path (example: `/hooks/script-complete`): resolved using `WEBHOOK_BASE_URL`.

If neither condition can be satisfied, callback is rejected/ignored (depending on route).

When resolved callback URL is valid, server sends:

```json
{
  "event_type": "execution.completed",
  "execution_type": "script",
  "execution_id": "uuid",
  "status": "completed",
  "success": true,
  "host_name": "host-1",
  "device_id": "device1",
  "team_id": "team-uuid",
  "deployment_id": null,
  "deployment_execution_id": null,
  "result": {},
  "error": null,
  "timestamp": 1739880000.123
}
```

For deployment completions:
- `execution_type`: `"deployment"`
- `execution_id`: deployment execution id
- `deployment_id`, `deployment_execution_id` are populated

## Triggering Manual Script Execution with Callback

Endpoint: `POST /server/script/execute?team_id=<team_id>`

Request body example:

```json
{
  "host_name": "my-host",
  "device_id": "device1",
  "script_name": "my_script.py",
  "parameters": "--foo bar",
  "callback_url": "https://external.example.com/vpt/callback"
}
```

Notes:
- `callback_url` is optional.
- If present, can be absolute `http/https` or relative path when `WEBHOOK_BASE_URL` is configured.

## UI Integration

### Run Tests

- Page: `frontend/src/pages/RunTests.tsx`
- New field: **Callback URL (Optional)**
- Behavior:
  - Value is sent as `callback_url` in script execute requests.
  - Works per selected device execution.

### Run Campaigns

- Page: `frontend/src/pages/RunCampaigns.tsx`
- New fields:
  - **Callback URL (Optional)**
  - **Callback after each script** (`callback_on_script_complete`)
  - **Callback on campaign completion** (`callback_on_campaign_complete`)
- Behavior:
  - Campaign callback settings are passed to `/server/campaigns/execute`.
  - Host sends completion payload to `/server/campaigns/executionComplete`.
  - Server fans out webhook(s) and socket updates.

## Environment Variable

### `WEBHOOK_BASE_URL`

Backend server uses this value to resolve relative callback paths.

Example:

```env
WEBHOOK_BASE_URL=https://automation.example.com
```

With this configuration:
- `callback_url: "/hooks/script-complete"` resolves to `https://automation.example.com/hooks/script-complete`
- `callback_url: "hooks/campaign"` resolves to `https://automation.example.com/hooks/campaign`

## Deployment Callback Notes

- Deployment scheduler now reports completion to server (`/server/deployment/executionComplete`).
- Campaign execution supports:
  - campaign-level completion callback
  - optional per-script callback fanout (`callback_on_script_complete`)
- Current DB schema does not persist `callback_url` on `deployments`.
- Today, deployment webhook delivery depends on payload-provided `callback_url` path.
- Future improvement: add `deployments.callback_url` column + create/update API support.
