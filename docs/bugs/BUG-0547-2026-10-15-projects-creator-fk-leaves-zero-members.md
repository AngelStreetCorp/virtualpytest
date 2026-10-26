# BUG-0547 — Newly created Projects always show 0 members, even though the creator should be auto-added as owner

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                 |
|-----------|-----------------------------------------------------------------------|
| ID        | BUG-0547                                                              |
| Reported  | 2026-10-15                                                            |
| Status    | Fixed (pending deploy)                                                |
| Severity  | High — every project is affected; counts, audit, and ACL all read wrong |
| Area      | backend_server — `server_projects_routes.create_project` · `projects_db.create_project` |
| Fixed in  | build 90145 |
| Commit    | TBD                                                                   |

---

## Symptom

On `/projects`, every card shows `0 members` and `1 owners` even for the project the user just created. The
project shows in the list, the user is treated as its creator on subsequent reads, but the `projects_members`
row that should make them the first owner is missing.

Reproduction:

1. Sign in as a `team:projects:create`-permitted user.
2. `POST /server/projects` with `{"name": "Acme TV"}`.
3. `GET /server/projects` — the new project's card reads `{count: 0, owners: 0, viewers: 0}`.
4. `GET /server/projects/<id>` — the project row is present, `created_by` is set, but `projects_members` is empty.

The executive summary's *Members* tile is also empty for every freshly created project.

## Root cause

`server_projects_routes.py:create_project` (commit `4b36c1cdd`, the version that landed the G1 wiring) calls
`projects_db.create_project(... created_by_team_member_id=request_user_id ...)`. `request.user_id` is the
caller's `profiles.id` (Supabase auth subject), not a `team_members.id`. Inside `projects_db.create_project`,
step 4 inserts into `projects_members` with `team_member_id = created_by_team_member_id` — whose FK targets
`team_members.id`, not `profiles.id`. The insert raises a foreign-key violation, the surrounding
`try/except` swallows it (`logger.warning("... could not add creator as owner: %s", e)`), and the project
is created with no member row at all.

The route had a comment claiming `created_by` (a `profiles.id`) is the right thing to pass; the table says
otherwise. The mismatch was never caught because (a) the endpoint only logs a warning, and (b) no test
exercised the post-create `projects_members` row.

## Fix

- `server_projects_routes.py:create_project` — resolves `creator_team_member_id = str(caller_team_member_ids[0])`
  (or the first row of the team for service-key callers) before calling `projects_db.create_project`. The FK
  on `projects.created_by` still receives the profile.id (`projects.created_by`), so we explicitly use
  `team_members.id` for the `projects_members` insert path.
- `shared/src/lib/database/projects_db.py:create_project` — defensive guard: skip the creator insert if
  `created_by_team_member_id` is empty / None (the route already prevents this, but future callers from MCP
  tools can reach the db layer directly).
- 12 unit tests in `tests/backend_server/test_projects_g11_bug_fixes_in_memory.py` cover the FK fix, the
  scope-tag split, and the G11 one-shot create.

## Verification

In-memory (no DB needed):

```
pytest tests/backend_server/test_projects_g11_bug_fixes_in_memory.py -v
# 12 passed
#   - TestBug0522CreatorFK :: test_creator_added_as_owner_when_team_member_id_supplied
#   - TestBug0522CreatorFK :: test_regression_against_old_id_type
#   - TestBug0523ScopeTagSplit :: test_auto_scope_tag_is_marked_is_scope_true
#   - TestBug0523ScopeTagSplit :: test_enrich_splits_scope_and_user
#   - TestBug0523ScopeTagSplit :: test_enrich_handles_no_scope_row
#   - TestG11OneShotCreate :: test_initial_user_tags_create_with_is_scope_false
#   - TestG11OneShotCreate :: test_initial_members_persist_alongside_creator
#   - TestG11RouteWiring   :: test_post_project_persists_initial_tags_and_members
#   - TestG11RouteWiring   :: test_post_project_rejects_invalid_payload
#   - TestMigration20261015b :: ...
```

End-to-end (post-deploy, with the G1 migration applied):

1. Sign in as a project-create permitted user.
2. `POST /server/projects` with `{"name": "Acme TV"}`.
3. `GET /server/projects/<id>` — `member_count: 1`, `owner_count: 1`, the creator's display name appears under
   the *Owners* chip group on the executive summary.

Rollback: revert the route + db edits; the `created_by` column on `projects` is unchanged and the FK
constraint on `projects_members.team_member_id` was never relaxed.
