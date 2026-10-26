# BUG-0548 — Project cards always show "1 tags" because the auto-created scope tag is counted as a user tag

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                |
|-----------|--------------------------------------------------------------------------------------|
| ID        | BUG-0548                                                                             |
| Reported  | 2026-10-15                                                                           |
| Status    | Fixed (pending deploy)                                                               |
| Severity  | Medium — display-only on the list page; misleading "1 tags" chip on every new project |
| Area      | backend — `server_projects_routes`, `projects_db._enrich` · schema migration 20261015b  |
| Fixed in  | build 90145 |
| Commit    | TBD                                                                                  |

---

## Symptom

Every project card on `/projects` shows `1 tags`, even for projects the user just created without attaching
a single tag. The badge is hard-coded as `{count} tags` and reads from `p.tag_ids.length`.

Reproduction:

1. Create a project (`POST /server/projects {"name": "Foo"}`).
2. Open `/projects`.
3. The card shows a chip reading `1 tags`.

Confirmed against a freshly seeded team: every row reads `1 tags` regardless of what the user did during
create. The doc string on `projects_db.update_project` even says "the slug is hidden in the UI" — the
behaviour it documents didn't exist.

## Root cause

`projects_db.create_project` auto-creates one tag per project — the project's *scope* tag, with the slugged
project name on `tags` and a row in `projects_tags` linking the two. There was no column on `projects_tags`
to mark that row as *internal* vs *user-attached*, and `_enrich` listed every linked tag as
`tag_ids: [t['tag_id'] for t in tags]`. The frontend's `Projects.tsx` counted all of them.

```python
# before the fix — every project has 1 scope tag, count > 0 even with no user tags
chip = "{count} tags".format(count=p.tag_ids.length)
```

## Fix

- **New schema migration** `setup/db/migrations/20261015b_projects_tags_is_scope.sql` adds
  `is_scope BOOLEAN NOT NULL DEFAULT FALSE` on `projects_tags`. Idempotent (`ADD COLUMN IF NOT EXISTS`)
  and a no-op when the column already exists.
- **Backend**:
  - `projects_db.create_project` step 3 inserts `is_scope: TRUE` on the auto-link.
  - `projects_db.create_project` steps 5–6 attach user-attached tags (`is_scope: FALSE`) and add
    initial members in one flow (G11 one-shot create, the work this slice was measured against).
  - `projects_db._enrich` exposes `{scope_tag, scope_tag_id, user_tags, user_tag_ids, user_tag_count}` so
    the API can count *only* user-attached tags.
  - `list_projects` / `get_project` query `projects_tags.is_scope` and build the enriched dict
    accordingly.
- **Frontend (commit 2, planned)**: `Projects.tsx` switches to `p.user_tag_count` (the new field). The
  scope tag is hidden from the chip group.

12 in-memory unit tests cover the split (`test_auto_scope_tag_is_marked_is_scope_true`,
`test_enrich_splits_scope_and_user`, `test_enrich_handles_no_scope_row`, plus the one-shot create / route
wiring tests).

## Verification

In-memory:

```
pytest tests/backend_server/test_projects_g11_bug_fixes_in_memory.py -v
# TestBug0523ScopeTagSplit :: test_auto_scope_tag_is_marked_is_scope_true ........ PASS
# TestBug0523ScopeTagSplit :: test_enrich_splits_scope_and_user ................. PASS
# TestBug0523ScopeTagSplit :: test_enrich_handles_no_scope_row .................. PASS
# TestG11OneShotCreate       :: test_initial_user_tags_create_with_is_scope_false  PASS
# TestG11RouteWiring         :: test_post_project_persists_initial_tags_and_members PASS
```

End-to-end (post-deploy, after migration apply):

1. Apply migration `20261015b` (one column add).
2. Create a project with no `tags` payload.
3. `GET /server/projects/<id>` — response includes `scope_tag: {...}` and `user_tag_count: 0`.
4. `GET /server/projects` — the card shows `0 tags` (the project's scope tag is hidden).

Rollback: `20261015b_projects_tags_is_scope_rollback.sql` drops the column. The data is recoverable:
re-running `_get_or_create_tag` for each project on the old data set restores the same behaviour the legacy
non-`is_scope` path was producing.
