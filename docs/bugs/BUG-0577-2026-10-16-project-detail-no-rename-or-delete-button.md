# BUG-0577: Project detail page exposes no Rename / Delete buttons (and no permission gating for them)

**Date:** 2026-10-16
**Discovered on:** the project detail page (`/projects/<id>`) for a freshly-created project (`"Tester Create 3f93a291"`, 0 owners, 0 viewers at the moment of the report).
**Severity:** medium — the underlying `PATCH /server/projects/<id>` and `DELETE /server/projects/<id>` routes were already in place and already enforced the right ACL; only the UI was missing.
**Status:** fixed on branch `fix/project-detail-edit-delete`.

## Symptom

On `/projects/<id>` the page chrome shows the project name, the owner / viewer chips, and the "Executive summary" link — but no **Rename** and no **Delete** button. The project's name is fixed once it's created; the only way to rename or remove a project was to drop into the Supabase dashboard and edit the row by hand. For a freshly-created test project that surfaces as "stuck with whatever auto-generated name the create dialog suggested".

The intended permission contract — **admins and project creators can rename or delete a project; plain viewers can't** — was already enforced server-side (`_can_edit_project` in `backend_server/src/routes/server_projects_routes.py` predates this bug). What's missing is the UI surface and the public helper that lets the page know whether the buttons should even render.

## Root cause

1. **`frontend/src/pages/ProjectDetail.tsx` had no Rename / Delete buttons.** The title row was wired only to the folder icon + name + owner/viewer chips + the Executive summary link. The `PageTitle` `right` slot stopped there.
2. **The overview response did not expose `can_edit` / `my_role`.** `GET /server/projects/<id>/overview` returned `{project, days, tiles}` only. The route layer knew the caller's edit rights (it uses the same `_can_edit_project` helper as `PATCH` and `DELETE`) but the JSON never carried the verdict to the client. The frontend couldn't gate the buttons even if we added them, because there was no signal.
3. **Helpers were private to `server_projects_routes.py`.** `_caller_team_member_ids` and `_can_edit_project` were underscore-prefixed — fine for callers in the same module, but not for `server_projects_overview_routes.py` to share without importing private symbols across modules.

## Fix

1. **Public helpers in `server_projects_routes.py`.** Added `caller_project_role(project_id) -> 'owner' | 'viewer' | None` and `can_edit_project(project_id) -> bool`. Both wrap the existing private logic so the admin bypass, the `projects_members.role = 'owner'` row check, and the team-scope check all stay one source of truth.

2. **`can_edit` + `my_role` in the overview response.**
   `GET /server/projects/<id>/overview` returns an extra `permissions` block:
   ```json
   "permissions": {
     "my_role": "owner" | "viewer" | null,
     "can_edit": true | false
   }
   ```
   `my_role` is the caller's row in `projects_members` (None for admins, service-key callers, or non-members). `can_edit` mirrors the `_can_edit_project` verdict the write routes already enforce, so the UI gate is **identical** to the server gate — no risk of the two diverging.

3. **`ProjectDetail.tsx` — Rename + Delete buttons in the title row, gated on `can_edit`.**
   - **Rename** opens a `Dialog` with a single `TextField` (60-char cap, matches the create flow). Enter submits; Submit is disabled when the trimmed name is empty, exceeds the cap, equals the current name, or the mutation is in flight. The server PATCH goes through `apiClient(... method:'PATCH' ...)` because the existing `api.*` object only ships GET/POST/PUT/DELETE; `PATCH` is the project's update verb.
   - **Delete** opens the shared `ConfirmDialog` with `confirmColor="error"`. The destructive action is unmistakably red; the dialog message names the project and warns that the scope tag will be detached from every script / testcase / virtual script / campaign it owns. On success the project is removed from localStorage (`writeCurrentProjectId(null)` + `setCurrentProject(null)`), the projects list and the per-project overview cache are invalidated, and the route transitions to `/projects` via `navigate('/projects', { replace: true })`.
   - Both buttons are **IconButton + Tooltip** so they fit cleanly next to the owner / viewer chips and the Executive summary link in the page header without adding a second row at 390 px.

4. **Permission gating is a server mirror, not a separate decision.** The frontend reads `permissions.can_edit` and only renders the buttons when it's true. The PATCH and DELETE routes still re-check on the server (admin OR owner) — a hand-crafted request from a viewer would still get a 403 even if the UI was wrong. Two-layer defence.

5. **i18n strings.** All nine new keys land in `frontend/src/i18n/locales/fr.json` and `de.json`:
   - `Delete project`, `Deleting…`, `Failed to delete project`, `Failed to rename project`, `Only admins and project owners can delete this project`, `Project name cannot be empty`, `Rename project`, `This action cannot be undone.`, `This will permanently delete "{name}" and remove its scope tag from every script, testcase, virtual script, and campaign it owns.`
   - `i18n-check --quiet` reports `0 error(s)`.

6. **TypeScript + lint.**
   - `tsc --noEmit -p .` — green.
   - `eslint --quiet src/pages/ProjectDetail.tsx` — green.

## Files changed

- `backend_server/src/routes/server_projects_routes.py` — added `caller_project_role()` + `can_edit_project()` public helpers.
- `backend_server/src/routes/server_projects_overview_routes.py` — overview response now carries `permissions: { my_role, can_edit }`.
- `frontend/src/pages/ProjectDetail.tsx` — Rename + Delete buttons + dialogs + PATCH / DELETE wiring + permission gate.
- `frontend/src/i18n/locales/fr.json` and `de.json` — nine new strings (en keys only).
- `tests/backend_server/test_projects_can_edit_in_memory.py` — unit tests for the public helpers (admin / owner / viewer / non-member matrix).

## Reproduction recipe (before the fix)

1. Sign in as a non-admin user who is a project owner.
2. Open `/projects/<id>` for any project they own.
3. Page header shows: folder icon, project name, "1 owners" chip, "0 viewers" chip, "Executive summary" link.
4. **Expected:** a pencil (rename) and a trash (delete) icon button.
5. **Observed:** nothing. The only way to rename the project is to hit the Supabase dashboard.

## Verification

- Admin sees both buttons on every project.
- Project owner sees both buttons on their projects; nothing on someone else's project they're not a member of.
- Plain viewer sees neither.
- Rename: PATCH round-trip works; the 60-char limit is mirrored client-side; a no-op submit (same name) is disabled; a 409 from a duplicate-name race surfaces as "A project with that name already exists in this team".
- Delete: ConfirmDialog → DELETE → back to `/projects`; the localStorage `virtualpytest:project_id` entry is cleared so the ProjectSelector stops claiming a deleted project is still active; the overview cache is removed so a back-nav doesn't show stale data during the navigation transition.
- The page header also carries a back arrow (to `/projects`) on the left of the folder icon, mirroring the `<- Back to project` link on `ProjectExecutive.tsx` for consistency across the two project sub-pages. Disabled while a rename / delete mutation is in flight, so a mid-action navigation can't desync the cache.