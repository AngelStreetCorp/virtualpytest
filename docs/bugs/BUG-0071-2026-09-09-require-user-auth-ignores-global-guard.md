# BUG-0071 — Per-route `@require_user_auth` ignored the global guard: 500/401 on every admin route of a no-login site

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0071                                                                    |
| Reported  | 2026-09-09 (customer site, first packaged delivery)                         |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | High on a no-login site (Run Command, user administration, security and storage admin routes all unusable) |
| Area      | backend_server/src/lib/auth_middleware.py                                   |
| Fixed in  | Unreleased                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

On the customer server (open mode, BUG-0070 workaround applied so the stale `SUPABASE_JWT_SECRET`
is commented out) the Run Command page fails on every host:

```
POST /server/system/runCommandOnHost?team_id=...  {host_name: "host4", command: "ls"}
→ 500 Internal Server Error
```

The server journal shows **no** `[server_system:runCommandOnHost]` line and **no**
`[@call_host] ... /host/system/runCommand` line for the request — only the neighbouring
`takeControl` / `cache/populate` traffic of other pages. The route body never ran. The
response body is `{"error": "Server configuration error", "message": "User authentication not
configured"}`; the journal shows `[@auth_middleware] WARNING: SUPABASE JWT secret not configured`.

Every route stacked with `@require_user_auth` + `@require_role(...)` behaves the same
(15 routes across `server_auth_routes`, `server_security_routes`, `server_storage_routes`,
`server_system_routes`). With the secret left in place and open mode set (post-BUG-0070 code)
the same routes answer 401 instead.

## Root cause

Two independent authorizers ran on the same request:

1. The **global guard** (`app.py` `before_request` → `enforce_user_auth_if_enabled_for_request`)
   accepted the request under open mode and set `request.user_role = admin` (BUG-0064/0070).
2. The **per-route** `@require_user_auth` decorator then started from scratch: it only knows
   the auto-sign and Supabase-JWT paths. With no secret it returned the 500 above; with a secret
   and no bearer token it returned 401. It never looked at the principal the guard had just
   established, so open mode, the X-Server-Key posture and the service key could never satisfy it.

`require_admin_role` already documents the intended contract ("runs after the global guard,
which is what sets `request.user_role`, so it needs no `@require_user_auth` of its own"), but
the older `@require_user_auth` + `@require_role` pairing predates the guard and was never
reconciled with it. It went unnoticed because every environment we operate has a JWT secret
and a logged-in browser, where both authorizers agree.

Not a missing SSH key and not name resolution: the server reaches hosts over HTTP at the
`host_api_url` each host registers (`http://10.10.x.10x:6109`), which the journal confirms.

## Fix

`auth_middleware.require_user_auth`: right after the auto-sign check, if the request already
carries a principal (`request.user_role` set by the global guard) the decorator passes through.
The guard is authoritative for `/server/*`: open mode, X-Server-Key and the service key never
carry a user JWT, and when a secret is configured the guard's own JWT branch has already verified
the token and set the same attributes. Routes outside `/server/*`, the guard's
`unauthenticated_prefixes`, and the guard's internal JWT probe (which runs before any principal
exists) keep the full JWT path unchanged.

`@require_role` still fails closed on its own: the service key (`role=service`) still gets 403
on `@require_role('admin')` routes, exactly as before.

## Verification

Flask test request context, guard then the decorated route (`@require_user_auth` +
`@require_role('admin')`), before → after:

| Posture | Before | After |
|---|---|---|
| `SERVER_OPEN_MODE=true`, no secret (customer site) | 500 `User authentication not configured` | 200, role admin |
| `SERVER_OPEN_MODE=true` + stale secret | 401 `Authorization header is required` | 200, role admin |
| `SERVER_PUBLIC_KEY` posture, `X-Server-Key` header | 500 | 200, role admin |
| `X-API-Key` (service) | 500 | 403 from `@require_role` (unchanged contract) |
| Secret configured, no token | 401 at the guard | 401 at the guard |
| Nothing configured | 401 at the guard | 401 at the guard |

`py_compile` clean.

## Workaround on the current build

None short of a code change: the route cannot be reached without a JWT on a site that has no
login. Deploy the fix.
