---
bug_id: BUG-0557
title: @require_team_in_tenant decorator declared but not applied to any of the ~140 team-scoped routes
summary: TASK-23 phase 3 was deferred. The decorator exists in backend_server/src/lib/auth_middleware.py but zero routes carry it. The global `enforce_team_scope()` guard catches the team_id path, but per-route tenant defense-in-depth is missing.
tags: [bug, security, tenancy, tenant, team, route, decorator]
keywords: [tenant, team, require_team_in_tenant, route, decorator, auth_middleware, enforce_team_scope, defense in depth, phase 3, task 23, gap]
created: 2026-10-16
---

# BUG-0557

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0557                                                     |
| Reported  | 2026-10-16                                                   |
| Status    | Closed (duplicate)                                           |
| Severity  | Medium (defense-in-depth gap, not an active leak today)      |
| Area      | backend                                                      |
| Fixed in  | — (internal)                                                 |
| Commit    | TBD                                                          |
| Duplicate of | [BUG-0561](BUG-0561-2026-10-16-require-team-in-tenant-not-applied-to-routes.md) |

## Symptom

TASK-23 phase 3 — the mechanical sweep of adding `@require_team_in_tenant` to every
team-scoped route — was deliberately deferred (see `docs/tasks/TASK-23-tenant-management.md`
§"Phase 3 deferred"). Today:

```
$ grep -rln "@require_team_in_tenant" backend_server/src/routes
(no output)
$ grep -rln "request.args.get..team_id" backend_server/src/routes | wc -l
      38
$ grep -rln "require_team_in_tenant" backend_server/src/lib/auth_middleware.py
backend_server/src/lib/auth_middleware.py   # the decorator IS declared
```

The decorator **exists** in `backend_server/src/lib/auth_middleware.py` and is wired into the
module, but **none** of the team-scoped routes carry it. Coverage today:

- `enforce_team_scope()` global guard in `backend_server/src/app.py:252` does catch the
  `team_id` taken from `request.args` (the most common path) and refuses teams the caller
  is not a member of. So a user editing the query string cannot read another team's data.
- `server_branding_tenant_routes.py` consults `_caller_tenant_ids()` directly (defensive
  pattern) for branding read endpoints.
- `auth_middleware.py:1525` reads `team.tenant_id` and checks it is in
  `_caller_tenant_ids()` in the org-scope path.

But: any route that takes a `tenant_id` directly (or a `team_id` from a non-`args` source),
or any route added after TASK-23 that was not individually reviewed, has no per-route tenant
gate.

## Root cause

Phase 3 was explicitly deferred in the task plan — the global `enforce_team_scope()` plus
`@require_admin_role` (now `@require_permission`) covered the read paths well enough at the
time. The decorator was wired in for completeness but the mechanical sweep was a follow-up
commit that was never opened.

## Impact

Today: **no active leak**. The RLS policies on the ~45 team-scoped tables plus the global
`enforce_team_scope()` guard already cover the realistic cross-tenant data paths. The
decorator is a **defense-in-depth** measure so a future route that takes a `tenant_id` or
`team_id` from a non-`args` source is still refused.

Worst case if a future contributor adds a route that bypasses `enforce_team_scope()`:
- a user in tenant A could request a resource by tenant B's id and have it returned,
- the user must still know the other tenant's UUID (low discovery cost on a closed deploy),
- RLS still rejects the underlying DB read.

## Fix

A mechanical sweep that adds `@require_team_in_tenant` to every route that:

1. takes `team_id` from anywhere (args, body, path, header), OR
2. dereferences a `tenant_id` (any source).

The decorator:

```python
@require_team_in_tenant  # reads team.tenant_id from request, refuses if not in _caller_tenant_ids()
@require_permission('org.teams:view')
def list_teams(...):
    ...
```

Pattern: layer it **after** `@require_user_auth_if_enabled` (so the caller principal is
established and `_caller_tenant_ids()` can read the JWT claim), but **before** the
permission gate (so unauthenticated calls don't pay the lookup).

## Verification plan

1. `grep -l "require_team_in_tenant" backend_server/src/routes` returns the expected N routes.
2. `tests/backend_server/test_tenant_route_guard.py::test_every_team_scoped_route_wears_decorator`
   walks the route table and asserts the decorator is present on every route that reads
   `team_id` from anywhere.
3. Live: a tenant-A user requests `/server/teams/<team-in-tenant-B>` and gets 403, not 200.

## Workaround today

None. The global `enforce_team_scope()` is the only thing covering this gap.

## Related

- TASK-23 (`docs/tasks/TASK-23-tenant-management.md`) — phase 3 deferred section
- `docs/agent/platform/ACCESS_MODEL.md` §7 G1 — this gap surfaced during the access-model
  audit on 2026-10-16