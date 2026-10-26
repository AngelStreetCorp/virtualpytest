---
bug_id: BUG-0558
title: workspace.project_tags is documented but no code reads or writes it for filtering
summary: The JSONB field `workspaces.project_tags` was added with the Phase 2 commit (`docs/agent/platform/WORKSPACES.md` §1) but no backend route, no hook, and no frontend predicate consults it. Project scoping today is done via `executable_tags` (project's tag → executables tagged with it).
tags: [bug, workspace, project, scoping, dormant, jsonb]
keywords: [workspace, project_tags, project scope, dormant, phase 2, workspaces, executable_tags, scope filter, dead field]
created: 2026-10-16
---

# BUG-0558

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0558                                                     |
| Reported  | 2026-10-16                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (UX confusion, no active leak)                           |
| Area      | db / backend / frontend / docs                               |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

## Symptom

`public.workspaces.project_tags` (JSONB array of tag IDs) is documented in:

- `docs/agent/platform/WORKSPACES.md` §1 ("Project scope: `project_tags` limit which
  testcases/campaigns are visible (Phase 2)")
- `docs/agent/platform/WORKSPACES.md` §3 (DB schema — `project_tags JSONB DEFAULT '[]'`)
- `docs/agent/platform/WORKSPACES.md` §7 ("Data filtering — pass `workspace_id` as a query
  param when fetching testcases/campaigns")
- `docs/features/workspace-scoping.md` ("`project_tags` limit which testcases/campaigns are
  visible (Phase 2)")

But a grep over the codebase shows the field is **dormant**:

```
$ grep -rln "project_tags" backend_server/src frontend/src shared/src
backend_server/src/routes/server_workspaces_routes.py     # schema accept only (create/update)
backend_server/src/routes/server_deployment_routes.py     # nothing
shared/src/lib/database/workspaces_db.py                   # schema accept only
frontend/src/hooks/pages/useWorkspaces.ts                  # type definition
frontend/src/contexts/workspace/WorkspaceContext.tsx       # never consulted
```

No read path consults `workspace.project_tags`. No testcase or campaign list endpoint filters
by it. `WorkspaceContext` exposes `isDeviceAllowed` / `isScriptAllowed` / `isPathHidden` but
not `isProjectAllowed` / `isExecutableAllowed` for this field.

In the meantime, **project scoping does work** — via the project's *own* tag, applied to
executables via `executable_tags` (post TASK-65 G10 + `20261015a_executable_tags_virtual_script_campaign.sql`).
That's the active path; `workspace.project_tags` is a parallel, unwired mechanism.

## Root cause

Two Phase 2 features were scoped at the same time:

1. **Workspace project-scope** — let a workspace narrow the executables visible to a project.
2. **Project as a tag** — when a project is selected, filter by the project's tag.

Feature (2) shipped and works (TASK-65 G9). Feature (1) was deferred because (2) covered
the same UX need more directly, and the workspace-level field became dead. The doc was
never revised.

- An admin who fills `project_jobs` on a workspace expecting a filter sees **no change** in the UI.
- Operators may spend time configuring a field that the platform ignores.

## Impact

**No active leak.** The active path (TASK-65 G9 + G10) does the project scoping correctly.
The dormant field is a UX confusion, not a security issue.

## Fix

Pick one of:

**Option A — wire it.** Add `WorkspaceContext.isExecutableAllowed(name, kind)` that
intersects the active workspace's `project_tags` with the project's tag set when both are
present. Wire it into `RunTests` script selector + `TestCaseSelector` + `CampaignSelector`
the same way `isScriptAllowed` is wired today. Update `WORKSPACES.md` §1 to move out of
"Phase 2" and into the live features list.

**Option B — remove it.** `ALTER TABLE public.workspaces DROP COLUMN project_tags;` (one
migration + rollback). Update `WORKSPACES.md` §1 + §3 + §7 to remove the references. Update
the type in `useWorkspaces.ts`. Add a release-note entry.

## Recommendation

Option A — wire it. The cost is small (one context predicate + one selector hook) and the
benefit is that operators who set `project_tags` on a workspace get what they asked for.
Defer if the team prefers to standardise on Option B.

## Verification

After Option A: with workspace W that has `project_tags = [tag_of_project_X]`, only
executables tagged with `tag_of_project_X` are visible in RunTests when W is active.

After Option B: `git grep project_tags` returns only schema documentation; the column is
gone from `public.workspaces`.

## Related

- TASK-65 (`docs/tasks/TASK-65-projects.md`) G9 + G10 — the working mechanism
- `docs/agent/platform/WORKSPACES.md` §1, §3, §7 — the docs that promise a behavior
- `docs/agent/platform/ACCESS_MODEL.md` §7 G2 — surfaced during the access-model audit