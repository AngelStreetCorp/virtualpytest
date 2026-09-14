# BUG-0061 — any signed-in user could read and write users, teams and workspaces

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                          |
|-----------|--------------------------------------------------------------------------------|
| ID        | BUG-0061                                                                       |
| Reported  | 2026-09-08                                                                     |
| Status    | Fixed (pending server deploy)                                                  |
| Severity  | High (missing authorization on user/team/workspace administration)             |
| Area      | backend_server/src/lib/auth_middleware.py · server_{users,teams,workspaces,permissions}_routes.py |
| Fixed in  | build 8713                                                                     |
| Commit    | this commit                                                                    |

---

## Symptom

Enabling the role-based backend suites (`63930e084`) turned on ~107 previously-skipped
tests. 13 of them failed — every one a *negative* authorization assertion that the server
answered `200`/`201` instead of `403`:

```
test_permissions.py::TestRoleBaselines::test_tester_cannot_access_users_endpoint
test_permissions.py::TestRoleBaselines::test_viewer_cannot_access_users_endpoint
test_permissions.py::TestPermissionMatrixAPI::test_non_admin_cannot_get_matrix
test_workspaces.py::TestWorkspaceAccessControl::test_{tester,viewer}_cannot_{list,create}_workspace
test_org_management.py::TestOrgRouteAccessControl::test_{tester,viewer}_cannot_create_team
test_org_management.py::TestOrgRouteAccessControl::test_tester_cannot_delete_team
test_org_management.py::TestTeamMemberManagement::test_{tester,viewer}_cannot_manage_team_members
```

Confirmed against the live server with short-lived probe JWTs signed with the server's own
`SUPABASE_JWT_SECRET` (the same way `scripts/setup_test_accounts.py` mints the CI tokens):

```
route                     admin   tester   viewer
GET /server/users           200      200      200
GET /server/workspaces      200      200      200
GET /server/teams           200      200      200
```

A **viewer** token could list every user account, every team and every workspace — and the
write routes were equally unguarded.

## Root cause

TASK-09 closed `/server/*` to *authentication* — the global guard in `app.py`
(`configure_global_frontend_auth_guard`) rejects anonymous callers. It never added
*authorization*: it sets `request.user_role` and lets the request through. Not one route in
`server_users_routes.py`, `server_teams_routes.py`, `server_workspaces_routes.py` or
`server_permissions_routes.py` carried a `@require_role` gate, so every authenticated
principal was effectively an admin on them. `require_role` existed and worked
(`@require_role('admin')` has been in use on run-command since 2026-05-19) — it was simply
never applied here.

## Fix

`auth_middleware.py` gains `require_admin_role` = `@require_role('admin', 'service')`:

- **`admin`** — the user role, from `app_metadata.role`.
- **`service`** — the shared `X-API-Key` principal the global guard sets for host→server,
  provisioning, CI and backend→backend callers. It is strictly *more* trusted than any
  user role (the same key drives `/host/*` device control), so locking it out of admin routes
  would break those callers for no safety gain. `docs/agent/platform/SERVER_AUTH.md` already
  specifies `X-API-Key` as the credential for service automation.
- Auto-signed E2E requests need no special case — the guard gives them `AUTO_SIGN_ROLE`, which
  is `admin` on every deployment that runs the browser suites.

Applied to 26 routes: the whole `/server/users`, `/server/teams` and `/server/permissions`
surface, and all of `/server/workspaces` **except** `GET /server/workspaces/user/<user_id>`.
That exception matters: `WorkspaceContext.tsx` calls it for every signed-in user to load
memberships + public workspaces. Locking it would have logged non-admins out of their own
workspaces. The plain `GET /server/workspaces` list is only used as an anonymous fallback,
so closing it is safe.

Deliberately *not* changed: existing `@require_role('admin')` gates keep their exact
semantics; only the new `require_admin_role` admits the service principal.

## Verification

- 26 routes register cleanly; blueprint endpoint names preserved (`require_role` uses `@wraps`).
- Frontend blast radius checked before landing: `useUsers`/`useTeams` are imported only by
  `Users.tsx`, `Teams.tsx` and `Workspaces.tsx` (admin pages); the frontend never calls
  `/server/permissions/matrix` or `/server/users/<id>/permissions`.
- Post-deploy, re-probed the live server per role and re-ran the role suites — see the
  release note entry for the resulting counts.

## Known gap, not fixed here

`GET /server/workspaces/user/<user_id>` takes the user id from the path and is open to any
authenticated caller, so one user can read another's workspace memberships. Narrowing it to
"self, or admin" is a separate change — it needs the route to compare against
`request.user_id`, and the frontend passes an explicit id today.
