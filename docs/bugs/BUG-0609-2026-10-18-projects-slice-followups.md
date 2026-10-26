# BUG-0609: projects slice follow-ups — permissions module, scope-tag inline error, per-project AI summary

**Date:** 2026-10-18
**Discovered on:** routine review of the BUG-0608 / project page v2 slice.
**Severity:** low — none of these are bugs in the existing behaviour. They are
housekeeping / paper cuts that surfaced while wrapping the v2 slice:
- `caller_project_role` / `can_edit_project` were inlined inside
  `server_projects_routes.py` and crossed module boundaries via a
  underscore-prefixed private import in `server_projects_in_scope_routes.py`.
- The `×` on a user-tag chip in `ProjectTagsEditor` only
  `console.error`-ed on failure (400 for the scope tag, 403 for non-owners,
  network errors). The user was looking at the chips and had no signal that
  the click was rejected.
- BUG-0606 / BUG-0608 deferred per-item AI token counts to a future slice
  because `ai_calls` had no `script_id` column. The cheap win — a project
  total — was still pending because no one had written the helper.

## What ships

- **`backend_server/src/lib/project_permissions.py`** — new module that owns
  `caller_project_role`, `can_edit_project`, `_can_edit_project`, and the
  private `_caller_team_member_ids` (the auth.users → team_members bridge
  that is only useful to these helpers). `server_projects_routes` keeps a
  thin re-export so tests / callers that use the old import path still
  resolve. `server_projects_in_scope_routes` now imports
  `can_edit_project` directly from the lib. Two callers, one source of
  truth for the ACL.

- **`ProjectTagsEditor` inline error** — on a failed `DELETE /tags/names/<n>`
  the catch block now sets a `removeError` string state and renders an
  inline error chip next to the chips. The friendly copy
  "Cannot remove the project's scope tag" is a regex match on the route's
  user-facing message; anything else passes through verbatim with
  `HTTP <status>`. Dismissing the error is a `×` click; the next remove
  attempt clears it. Backend test
  `test_remove_user_tag_400_for_scope_tag` already covered the 400 contract;
  the route and the chip now communicate correctly.

- **Per-project AI summary on `/server/projects/<id>/in-scope`** — the
  response gains a `summary: {tokens, calls, cost_usd}` field, populated by
  a new helper `_ai_tokens_for_project(project_id, days)` that filters
  `ai_calls` by `project_id` over the `days` window. The project page
  renders this as a muted chip in the section header; the chip suppresses
  itself when `calls == 0` so a quiet project doesn't shout "0 · 0 · $0".
  `ai_usage_stats` (the hourly rollup) deliberately bypassed — it has no
  `project_id` column; the per-call `ai_calls` table does (added in
  BUG-0559).

- **v3 mockup committed** —
  `docs/tasks/TASK-101-project-page-mockup-v3.html` is now in the repo
  (the worktree file was lost when the previous worktree was removed).
  BUG-0606 and BUG-0608 docs link to it from a "Visual reference" section.
  The mockup is the implementation-bound design — Devices by host,
  Executables as a flat peer list, Campaigns in a separate band — and the
  code in `ProjectInScope.tsx` tracks it 1-to-1.

- **Renumber note on BUG-0608** — the doc body now explains why the slice
  shipped as BUG-0608 instead of BUG-0607 (a parallel pokemon agent
  claimed 0607 for the saffron-step fix in the same merge window), with a
  cross-link to the actual BUG-0607 doc for readers landing here from old
  release notes.

## Why these belong together

None of the five items warrants a slice on its own (≤ 1 day each); together
they share the same review surface (project permissions module,
`ProjectInScope.tsx` + the GET endpoint it consumes, and the project page
doc corpus). Bundling keeps the leak-gate + review-gate cycles aligned with
the source files that exercise the changes.

## What's still deferred

- **Per-script / per-testcase / per-virtual AI token breakdown.** Needs a
  `script_id` / `virtual_script_id` column on `ai_calls` (and the writers
  in `ai_calls_ingest` to populate them). When the column lands the helper
  grows a `group_by` argument and `ProjectInScope` shows per-row tokens in
  the same position as `runs · pass %`.
- **Toast provider.** The inline error is in the right place but a
  full-product wave will probably want a real toast service for cross-page
  notifications. Until then the inline pattern is contained and works.
- **Idempotency on `DELETE /tags/names/<name>`** — the helper unlinks one
  row at a time. If two clients race, both DELETEs return 200 even though
  only one row existed. Real-world impact is zero because removing the
  same user tag twice is a no-op the user can predict; documenting for
  completeness only.
