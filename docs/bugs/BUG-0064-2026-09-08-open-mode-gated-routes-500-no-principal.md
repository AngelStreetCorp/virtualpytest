# BUG-0064 — `SERVER_OPEN_MODE=true` left every permission-gated route answering 500

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0064                                                                    |
| Reported  | 2026-09-08                                                                  |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | High on an open-mode deployment (test case save, campaign and user-admin writes all fail) |
| Area      | backend_server/src/lib/auth_middleware.py                                   |
| Fixed in  | build 8713                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

On a server running with `SERVER_OPEN_MODE=true` (the documented dev / trusted-network
escape hatch of the closed-by-default guard, `be7dfa7c9`), every route carrying
`@require_permission` / `@require_any_permission` / `@require_role` answered:

```
500 {"error": "Configuration error",
     "message": "@require_permission must be used after @require_user_auth"}
```

That is `POST /server/testcase/save` (so the QuickTest Builder could not save a single
test), the campaign create/update/delete/execute routes gated by BUG-0061 / `8747ac429`,
and the admin-only user/team/workspace routes. Reads were unaffected.

## Root cause

The global guard's open-mode branch returned `None` (allow) **without setting a principal**.
Every other allow path (`X-API-Key` → `service`, auto-sign → `AUTO_SIGN_ROLE`, JWT → the
token's role, `X-Server-Key` → `SERVER_PUBLIC_ROLE`) populates `request.user_role`; the
gates read that attribute and treat its absence as a wiring error. Open mode was added
before the write routes were gated, so nothing exercised the combination until the
permission matrix was enforced on testcase/campaign writes.

## Fix

The open-mode branch now sets the same principal as the no-JWT `X-Server-Key` path:
`request.user_role = SERVER_PUBLIC_ROLE` (default `admin`), `user_id='open_mode'`,
empty permission/denial lists. Open mode means "everything is allowed" by definition, so
granting the configured public role there does not widen the posture; it only stops the
gates from crashing.

## Verification

Flask test request context with `SERVER_OPEN_MODE=true`, no `SUPABASE_JWT_SECRET`:

```
guard -> None | role = admin
gated route (require_any_permission testcases:create|edit) -> OK
admin route (require_admin_role) -> ADMIN-OK
```

Closed mode is untouched: without the flag the same request still gets `401`.
