# BUG-0186 — Test reports named the same user for every run launched from the web UI

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0186                                                     |
| Reported  | 2026-09-29                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — wrong audit trail, no data loss                     |
| Area      | frontend / backend_server / backend_host / reports           |
| Fixed in  | Unreleased                                                   |
| Commit    | `a25e643bf`                                                  |

---

## Symptom

Once a site switched on user logins, the report's execution summary line
`🎯 Trigger: type=api | user=eb6cfd93-44ab-4783-bd0c-129b734640f3 | ip=…` showed the same UUID for
every run started from Run Tests, whoever was logged in. Nothing in the line told a run started in
VirtualPyTest apart from one sent by an outside scheduler through the API
(`user=<their X-User-ID>`), and the platform's own deployment scheduler wrote
`user=deployment:script:<name>`.

## Root cause

- `frontend/src/hooks/useUserSession.ts` took the user id from `localStorage['cached_user']`, a key
  nothing in the frontend ever writes, so it always fell back to `APP_CONFIG.DEFAULT_USER_ID`
  (`eb6cfd93-…`). The same id was sent as the device-lock owner.
- The execute routes (`server_script_routes.py`, `server_campaign_execution_routes.py`,
  `server_testcase_routes.py`) copied that body `user_id` into `trigger.caller_user` and ignored
  the identity the auth guard had already verified from the login token.

## Fix

- `useUserSession` reads the logged-in user from the auth context; deployments without a login
  keep the default id. The dead `CACHED_USER` constant is removed.
- New `backend_server/src/lib/utils/trigger_utils.py::resolve_caller_user`, used by the four
  execute paths, labels the caller:
  - logged-in UI user → `vpt_user:<full name | email>`, from the verified token, not the body
  - UI without a login (open mode, public key, auto-sign in a browser) → `vpt_user:<name | open_mode | …>`
  - X-API-Key callers and other direct calls → their own `user_id` / `X-User-ID`, unchanged
- `backend_host/src/services/deployment_scheduler.py` labels scheduled runs
  `vpt_deployment:script:<name>` / `vpt_deployment:campaign:<name>`.

## Verification

- `tests/backend_server/test_trigger_utils.py` (7 unit tests) pass; frontend `tsc --noEmit` clean.
- After deploy: run a script from Run Tests while logged in; the report's Trigger line reads
  `user=vpt_user:<your name>`. A scheduled deployment reads `user=vpt_deployment:script:<name>`;
  an API caller with `X-API-Key` still shows its own `X-User-ID`.
