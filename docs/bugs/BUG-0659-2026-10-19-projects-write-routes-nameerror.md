# BUG-0659 — Renaming, deleting or managing members of a project fails with a server error

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0659 |
| Reported  | 2026-10-19 |
| Status    | Fixed (pending deploy) |
| Severity  | High |
| Area      | backend / projects |
| Fixed in  | build 90145 |
| Commit    | see git log |

---

## Symptom

`PATCH /server/projects/<id>`, `DELETE /server/projects/<id>`, `POST /server/projects/<id>/members`,
`DELETE .../members/<id>` and the tag write routes answered `500 {"error":"name '_can_edit_project' is not defined"}`
for every caller, admins included (found by CI backend-server-tests, run 3422, once BUG-0658 let projects be created).

## Root cause

Commit d83f4695f (BUG-0609 step 1) moved `can_edit_project` to `backend_server/src/lib/project_permissions.py` and
re-exported only the public name at the top of `server_projects_routes.py`; its message says the underscore alias
was kept "for completeness" but no alias was written. The write routes still call `_can_edit_project(...)`.
`server_projects_in_scope_routes.py` was updated correctly (`can_edit_project as _can_edit_project`), which hid it.

## Fix

`server_projects_routes.py`: import `can_edit_project as _can_edit_project` (same rename as the in-scope routes).
The admin-or-project-owner check is unchanged.

Two CI test fixes, not server bugs: `test_create_project_rejects_duplicate_name` posted without `?team_id=`
(400 "team_id is required"), and `test_tester_cannot_create_project` was stale: migration `20261006a_projects.sql`
grants `team:projects:create` to manager, developer and tester (viewer is view-only), and the route is
`@require_permission('team:projects:create')`, so a tester creating a project (201) is the designed behaviour.
It is now `test_tester_can_create_project` and deletes what it creates.

## Verification

New `tests/backend_server/test_projects_write_routes_in_memory.py` drives each write route through a Flask test
client (admin, owner, non-owner): 16 tests, all fail without the fix, pass with it. The other in-memory projects
suites still pass. After a deploy the four NameError CI tests should go green.
