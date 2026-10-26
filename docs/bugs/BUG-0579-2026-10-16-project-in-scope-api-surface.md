# BUG-0579: project detail page has no API surface for in-scope artefacts

**Date:** 2026-10-16
**Discovered on:** the project detail page (`/projects/<id>`) after BUG-0577 landed the rename + delete buttons.
**Severity:** medium — auto-tag-on-create (TASK-65 G5) was already in production, but the project page had no way to (a) **see** what was in scope, (b) **add** an existing artefact manually, or (c) **edit** the project's user tags. The contract was complete, the UI was passive.
**Status:** fixed on branch `fix/project-in-scope-api`.

## Symptom

The `ProjectDetail` page header (post-BUG-0577) had:
- a back arrow
- the project name
- owner / viewer chips
- scope / user tag chips (read-only)
- 6 stat tiles (scripts, runs 30d, devices, AI tokens, active users, failures)
- an "Executive summary" link
- a Rename / Delete IconButton pair

…but no way to see *which* devices, scripts, testcases, virtual scripts, and campaigns were actually in scope, no way to add an artefact that was missing, and no way to edit the user-tag list. The auto-tag path (TASK-65 G5) handles artefacts at create time, but a project that's been around for a while has artefacts the user wants to link retroactively.

## Root cause

1. **No in-scope aggregator.** The overview endpoint returns aggregate counters; the executables endpoint returns ids + names. Neither surfaces the per-item run/pass/tokens data the project page mockup (TASK-101 v3) called for: "X runs · Y% pass · Z k tok" on every device / script / campaign row.
2. **No manual link endpoint.** The existing `add_executable_to_project` db helper exists but isn't exposed via a route. The UI's `+ add` and `×` buttons had no backend to call.
3. **No tag-by-name endpoint.** The existing tag-management routes (`POST /server/projects/<id>/tags`) take `tag_id` (int). The user-facing flow in the device flag editor (`PUT /server/device-flags/...` body `{flags: ["qa-test", "nightly"]}`) takes names. The mismatch meant the project page would need a tag-picker UI, not a flag-style text input.

## Fix

A new blueprint `server_projects_in_scope_bp` (5 routes, all under `/server/projects/`) plus 7 new helpers in `shared/src/lib/database/projects_db.py`. No new tables, no schema migration.

### Routes

| Verb | Path | Body | Behaviour |
|---|---|---|---|
| `GET` | `/<id>/in-scope?days=30` | — | Aggregator: returns `{devices, executables, campaigns}` with per-item run/pass/last-seen, plus `totals` (devices count, distinct hosts, executables by type, campaigns count) and the project's `tag_names`. |
| `POST` | `/<id>/link` | `{type, id}` | Manually attach an artefact (script / testcase / virtual_script / campaign) to the project. Idempotent (duplicate = 200 with `already_linked: true`). Admin or project owner only. |
| `DELETE` | `/<id>/link` | `{type, id}` | Manually detach. The artefact itself is **not** deleted. Idempotent (already-gone = 200 with `was_linked: false`). Admin or project owner only. |
| `POST` | `/<id>/tags/names` | `{names: [...]}` | Get-or-create each tag by name (matches the device-flag pattern `flags: ["qa-test", "nightly"]`) and link it to the project as `is_scope=false`. Skips the scope tag. Admin or project owner only. |
| `DELETE` | `/<id>/tags/names/<name>` | — | Unlink a user tag. The scope tag (auto from project name) is **protected** — 400 with `Cannot remove the project's scope tag`. The `tag` row itself is kept: artefacts that were tagged through it still link to the same `tag_id`. Admin or project owner only. |

### Helpers (projects_db.py)

- `list_in_scope_devices(project_id, team_id, days)` — devices with `flags ∩ tag_names ≠ ∅`, plus per-device runs / pass rate / last-seen / state.
- `list_in_scope_executables(project_id, team_id, days)` — flat peer list: scripts + testcases + virtual scripts, each with runs / pass rate. Scripts are joined by `script_name` (the existing G5 contract); virtual scripts by `virtual_script_id`; testcases report `0 runs` (no `testcase_runs` table today — v2 enhancement).
- `list_in_scope_campaigns(project_id, team_id, days)` — campaigns with run / pass from `campaign_executions`.
- `add_executable_to_project(project_id, type, id)` / `remove_executable_from_project(...)` — direct row-level link helpers.
- `get_or_create_tag_by_name(name)` — get-or-create a `tags` row by name. Re-queries after insert to get the full row (PostgREST return shape isn't trustable across versions).
- `add_user_tag_to_project(project_id, tag_id)` / `remove_user_tag_from_project(project_id, tag_id)` — link by `tag_id`, with `is_scope = false` filter on remove to protect the scope tag.

### Audit log

Every write emits a `[PROJECT_AUDIT]` line via the local `_audit_log` helper. New actions: `link_add`, `link_remove`, `tag_add_by_name`, `tag_remove_by_name`. The action set in the docstring of the original G6 audit helper is closed — this slice extends it with four new values.

### Permission gate

All four write routes call `_can_edit_project(project_id)` — same gate the existing PATCH / DELETE / members / tags routes use. The 403 message names the contract: "Only admins and project owners can manage project tags / link artefacts to a project".

### Filter contract (unchanged)

The in-scope endpoints apply the same rules the G9 selector uses:
- **Devices**: `device_flags.flags ∩ project.tag_names ≠ ∅` (computed in SQL; `tag_set` is lowercased for case-insensitive match)
- **Executables**: `executable_tags.tag_id IN projects_tags.tag_ids`
- **Campaigns**: same as executables (`executable_type = 'campaign'`)

## Files

- `backend_server/src/routes/server_projects_in_scope_routes.py` (new, ~470 lines)
- `backend_server/src/app.py` (1 import, 1 blueprint registration)
- `shared/src/lib/database/projects_db.py` (7 new helpers + `datetime` import at module level)
- `tests/backend_server/test_projects_in_scope_in_memory.py` (new, 26 tests across 8 classes)
- `docs/release_note/README.md` (entry under Features)

## Verification

- 26 in-memory tests pass in `test_projects_in_scope_in_memory.py`:
  - device flag-intersection (2 in scope, 1 out of scope)
  - per-device run/pass aggregation
  - last-seen picked from the most recent run
  - empty-tags short-circuit
  - executables as a flat peer list (scripts / testcases / virtuals)
  - script runs joined by `script_name`, virtual scripts by `virtual_script_id`
  - testcases report 0 runs (the documented v1 behaviour)
  - campaign aggregation from `campaign_executions`
  - link add/remove + idempotency
  - add/remove helper acceptance/rejection of unknown types
  - get_or_create_tag_by_name idempotency
  - user-tag add sets `is_scope = false`
  - user-tag remove refuses to drop the scope row
  - GET in-scope full payload (devices, executables, campaigns, totals, tag_names)
  - GET 404 when project missing
  - link-add 200 for admin, 403 for viewer, 400 for unknown type
  - link-remove idempotent (already-gone = 200)
  - tags/names POST 200 / 403 (viewer) / 400 (invalid name)
  - tags/names DELETE 200 (user tag) / 400 (scope tag)
- 169 project tests pass overall (3 pre-existing G5 path failures from the Linux-only `/home/<operator>/...` checkout are unrelated to this slice).

## What's not in this slice (v2)

- **Per-item token counts.** `ai_usage_stats` doesn't link to `script_results.script_name` or `virtual_script_id`. Today the project page would show project-wide AI tokens (already on the overview tile) but not per-script / per-device / per-campaign. A v2 join on `ai_usage_stats` ↔ `script_results` is the only blocker.
- **Testcase runs.** Same shape — `testcase_runs` table doesn't exist. Reporting 0 runs is the honest answer; the project page surfaces it.
- **Re-tag-on-create is still on.** The auto-tag path (`X-Project-Id` header) is unchanged. The new manual link endpoint is additive.
- **Frontend UI.** The v3 mockup in `docs/tasks/TASK-101-project-page-mockup-v3.html` shows what this API enables. The actual `ProjectInScope` React component is a follow-on (estimated 1-2 days).