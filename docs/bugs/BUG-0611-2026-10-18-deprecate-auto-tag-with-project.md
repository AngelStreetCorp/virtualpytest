# BUG-0611: `auto_tag_with_project` is now a deprecated no-op

**Date:** 2026-10-18
**Discovered on:** review of the projects slice after BUG-0609. The
auto-tag-on-create path is now legacy: a user can add an artefact to a
project via the supported manual flows (POST `/link` from BUG-0579, the
project page `+ add` buttons from BUG-0608) regardless of when the
artefact was created. The auto-tag path was the original convenience
when there was no other way; today it does work the user has to undo
("why is my campaign silently in this project?" — see the BUG-0608 doc
release-note entry on the topic).
**Severity:** low — no behaviour change for users who already use the
manual flow. Users who depended on the auto-link-on-save convenience
will need to learn the `+ add` button (one extra click), or a future
slice re-introduces an explicit "link to active project" toggle on the
save dialog (BUG-XXXX to be filed if requested).

## What changes

`projects_db.auto_tag_with_project(executable_type, executable_id, project)`
becomes a no-op. The function still:

- accepts the same three positional arguments
- returns `True` on the happy path (or `False` if `project` is missing
  its `tag_ids`)
- never throws

What it stops doing:

- Inserting into `executable_tags` (the table the manual `add_executable_to_project`
  helper also writes to)
- De-duplicating on the `(type, id, tag_id)` unique constraint
- Logging the `auto_tag_with_project error: ...` warning that callers
  used to surface transient Supabase failures

A single `logger.info` line is now emitted per call so anyone watching
project-audit logs can see the deprecated path firing.

The three production callers stay green for now:

- `backend_server/src/mcp/tools/campaign_tools.py:227` (campaign save)
- `backend_server/src/mcp/tools/testcase_tools.py:515` (testcase save)
- `features/virtual-scripts/backend_server/mcp_tools/virtual_script_tools.py:146`
  (virtual script save)

Follow-on: drop the `auto_tag_ok = ...` line and the surrounding
try/except in each once Atlas's "auto-link on save" UX hint is removed.

## Why this lands now

TASK-65 G11 commit 2 (BUG-0608) wired the manual flow. Anything that
silently mutates the project's executable set on save is now a paper cut
— it makes the audit log noisier and surprises users who don't realise
their campaign ended up in the "Smoke regression" project. Deprecating
the helper but keeping the signature stable for one release cycle lets
the three legacy tool callers keep working while the UI migrates.

## Test changes

- `test_auto_tag_inserts_executable_tag` → renamed and re-asserted as
  `test_auto_tag_returns_true_without_inserting`. Verifies the function
  returns True AND that the `executable_tags` table doesn't grow.
- `test_auto_tag_is_idempotent` updated to assert the row count is
  unchanged after three calls (it was previously asserting exactly one
  tag row existed; now zero).
- `test_full_pipeline_create_project_then_autotag` renamed and
  reworked as `test_full_pipeline_create_project_then_manual_link`. The
  final assertion (`list_executable_ids_for_project_tag` returns the
  linked id) is now reached by the manual `add_executable_to_project`
  path instead of the deprecated one.

The three `TestG5McpToolAutoTag` tests
(`test_save_virtual_script_auto_tags_with_project`,
`test_save_virtual_script_passes_explicit_project_id`,
`test_save_virtual_script_no_project_is_noop`) already had
hardcoded `/home/<operator>/vpt-task65/...` import paths in their bodies
that fail on every machine except `/home/<operator>/vpt-task65`. They fail
on `main` too — pre-existing, not introduced by this slice.

## Release note

The BUG-0608 release note entry gets a closing line that mentions the
deprecation, so readers who still rely on the auto-tag path see the
warning.
