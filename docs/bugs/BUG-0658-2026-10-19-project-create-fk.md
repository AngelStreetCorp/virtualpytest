# BUG-0658 — Creating a project always fails with "Failed to create project"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0658 |
| Reported  | 2026-10-19 |
| Status    | Fixed (pending deploy) |
| Severity  | High |
| Area      | backend / projects |
| Fixed in  | build 90145 |
| Commit    | see git log |

---

## Symptom

`POST /server/projects?team_id=...` answers `500 {"error":"Failed to create project"}` for every caller
(13 tests in `test_projects.py` / `test_projects_executive.py` failed in CI backend-server-tests).

## Root cause

`projects.created_by` is a foreign key to `profiles.id`, but `projects_db.create_project()` wrote the creator's
`team_members.id` into it (the route resolves a team-member id for the `projects_members` owner row and the same
value was reused). Server log on the deployed server:
`insert or update on table "projects" violates foreign key constraint "projects_created_by_fkey" ...
Key (created_by)=(fe68c027-...) is not present in table "profiles"` (that id is a `team_members.id`).

## Fix

`shared/src/lib/database/projects_db.py`: `create_project()` resolves `team_members.user_id` (= `profiles.id`) for the
creator and writes that to `created_by`. The `projects_members` row still uses the `team_members.id`.

## Verification

`tests/backend_server/test_projects_in_memory.py`, `test_projects_g11_bug_fixes_in_memory.py` pass; after a deploy
the 13 live project tests create projects (201). No DB migration.
