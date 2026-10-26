# BUG-0787 — The Roles page and the Users page show different permission counts for the same role, because three stored permissions are unknown to the app

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0787                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / backend                                           |
| Fixed in  | build 90145 |
| Commit    | —                                                             |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-16, in `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** /roles and /users
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open `/roles` and read the Permissions column.
2. Open `/users` and read the Permissions column for the same roles.

**Expected:** One number per role.

**Actual:** Manager 68 vs 65, Developer 54 vs 51, Tester 48 vs 45, Viewer 27 vs 26. The migration `setup/db/migrations/20261006a_projects.sql:296-310` seeded `team:projects:view`, `:edit`, `:delete` into the role rows, but the frontend registry (`ALL_PERMISSIONS`, `types/auth.ts:146`) does not contain them, so they can be neither granted nor revoked in the UI, and the project routes other than POST carry no `require_permission` guard, so they gate nothing. They only make the Roles number wrong.

Evidence:

- [ops-16-permission-count-mismatch.png](../tasks/qa-evidence/ops/ops-16-permission-count-mismatch.png)

## Root cause

Two pages counted two different sets, and the difference was not only a number.

**The count.** `frontend/src/pages/Roles.tsx:145` counted the stored list (`roles?.[info.role]`, straight from the API), while `Users.tsx:278` counted the *effective* list (`computeEffectivePermissions`, which filters through the frontend registry `ALL_PERMISSIONS`). The role rows hold four project permissions that the frontend registry does not know — `team:projects:view`, `:edit`, `:delete` (unknown everywhere) and `team:projects:create` (known to the frontend, unknown to the backend). The Roles page counted all four, the Users page only the ones the app knows: three per role for manager, developer and tester, one for viewer.

**The save.** `team:projects:create` is a real permission — `POST /server/projects` is gated by `@require_permission('team:projects:create')` (`backend_server/src/routes/server_projects_routes.py:174`) and the Projects page checks it (`frontend/src/pages/Projects.tsx:68`) — but the backend's vocabulary `_ALL_PERMISSIONS` (`server_permissions_routes.py:32`) did not contain it. `update_role()` rejects every permission outside that vocabulary, and the edit dialog sent the stored list back, so **every save of the manager, developer, tester and viewer role failed**. Reproduced on the live platform (2026-10-22), `PUT /server/roles/manager` with the role's own stored list:

```json
{"error":"Unknown permissions: ['team:projects:create', 'team:projects:delete', 'team:projects:edit', 'team:projects:view']","success":false}
```

So the admin could not edit a role at all — and the number on the page was wrong at the same time.

## Fix

- **The backend knows the permission the app enforces.** `team:projects:create` is now in `_ALL_PERMISSIONS` (`backend_server/src/routes/server_permissions_routes.py`), with a comment saying why. The two vocabularies now hold the same 93 permissions.
- **The Roles page counts the permissions the app can honour.** `frontend/src/pages/Roles.tsx` filters the stored list through the frontend registry: the Permissions chip counts (and names) the known permissions only, and the edit dialog opens with the known permissions ticked. The three dead permissions are neither counted nor sent.
- **The admin is told, not surprised.** When a role holds permissions the app does not know, the edit dialog says so ("3 stored permission(s) are not used by the app and are not shown here: … They gate nothing, and saving this role removes them."). The dead permissions are removed from the row by the next save of that role — no data migration needed, and nothing that gates anything changes.
  Which stored lists change, exactly (from `20261006a_projects.sql`): on the first save, manager, developer and tester lose `team:projects:view`, `:edit` and `:delete`; viewer loses `team:projects:view`; `team:projects:create` stays everywhere. Roles never saved keep their stored rows.

## Verification

Real browser, the Roles page (`scripts/agent/roles_permission_counts.py`, reading the Permissions column of every row):

| role | before (live) | after (worktree) | what the Users page counts |
|---|---|---|---|
| Admin | All | All | All |
| Manager | **68** | **65** | 65 |
| Developer | **54** | **51** | 51 |
| Tester | **48** | **45** | 45 |
| Viewer | **27** | **26** | 26 |

One number per role. **After the deploy** (build main-2026.10.22-89636) the live Roles page reads the same: Manager **65**, Developer **51**, Tester **45**, Viewer **26** — the numbers the Users page counts.

Re-checked after the deploys that followed: the live Roles page still reads Manager **65**, Developer **51**, Tester **45**, Viewer **26** (`scripts/agent/roles_permission_counts.py`).

Screenshots: [before (live)](../../tasks/qa-evidence/fix/bug-0787-before-live.png) · [after (worktree)](../../tasks/qa-evidence/fix/bug-0787-after-worktree.png) · [after (live, deployed)](../../tasks/qa-evidence/fix/bug-0787-after-live.png).

Tests:

- `tests/frontend/RolesPermissionCount.test.tsx` — a role holding two known and two unknown permissions counts the two known ones. Against the pre-fix page the chip shows 4 and the test fails.
- `tests/backend_server/test_permission_vocabulary.py` — the frontend and the backend vocabularies must be the same list (they were not: the frontend knew one permission the backend rejected), and `team:projects:create` must be in both. Both cases fail against the pre-fix backend.
- `tests/backend_server/test_update_role_permissions.py` — the route itself (database write mocked): a role holding `team:projects:create` is saved, a role holding a permission nobody knows is still refused with the name in the answer. The first case fails against the pre-fix backend with exactly the "Unknown permissions" answer the live platform gave.

Checks: `pytest tests/backend_server/test_permission_vocabulary.py tests/backend_server/test_update_role_permissions.py` 4/4 · `tsc --noEmit` 0 errors · eslint clean on the changed files · the gate's ruff selection clean on the changed files.
