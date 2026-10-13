# BUG-0424 — Take control recorded a logged-in user as the built-in default user

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0424                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_server / device locks                                |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

On a customer server with logins enforced (`SERVER_OPEN_MODE=f`, JWT secret set), every
`device_control_sessions` row for a person's take control had
`owner_user_id = eb6cfd93-44ab-4783-bd0c-129b734640f3`, the built-in default user. Joining
`auth.users` gave no email, so the sessions behind BUG-0422 could only be traced through the IP
and the display name printed in the server journal (`🎮 [CONTROL] Taking control … user: <name>`).

## Root cause

The lock routes took the owner from the request body: `data.get('user_id') or X-User-ID`. The
browser sends `user?.id || APP_CONFIG.DEFAULT_USER_ID` (`frontend/src/hooks/useUserSession.ts`),
so a browser whose auth context had no id sent the default. The server never used the identity its
own auth guard had verified (`request.user_id`, the JWT subject).

## Fix

`resolve_lock_owner()` in `backend_server/src/lib/utils/lock_utils.py`: when the auth guard verified
a personal login (`request.user_id` is a UUID), that id is the lock owner, and the display name falls
back to the login email. Without a personal login (open mode, service key, auto sign) the request
body is used as before. Used by take control, heartbeat, takeover, script execution and campaign
execution, so a user's own script still matches their manual lock.

## Verification

Take control while logged in, then:
`select owner_user_id, u.email from device_control_sessions s left join auth.users u on u.id::text = s.owner_user_id order by started_at desc limit 1;`
→ the logged-in account and its email, not `eb6cfd93-…`.
