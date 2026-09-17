# BUG-0132 — Creating a workspace whose name was already used answered 500, and one leftover row disabled its tests for good

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0132                                                                    |
| Reported  | 2026-09-16                                                                  |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | Medium (a recoverable user error presented as a server fault; three tests silently stopped running) |
| Area      | `shared/src/lib/database/workspaces_db.py`, `backend_server/src/routes/server_workspaces_routes.py` |
| Fixed in  | build 9151                                                                  |
| Commit    | `40716b6ca5`                                                                |

---

## Symptom

`POST /server/workspaces` with a name whose derived slug was already taken answered:

```
HTTP 500 {"error":"Failed to create workspace"}
```

The caller is told the server broke. In fact they had picked a name that was in use — the one
thing they could have fixed.

## Root cause

`workspaces_db.create_workspace` wrapped its insert in a bare `except Exception`, printed the
error and returned `None`. The route treats `None` as "something went wrong" and returns 500,
so a postgres `23505` unique violation on `workspaces_slug_key` was indistinguishable from a
genuine database failure.

The slug is derived from the caller's own `name` (`_make_slug`), which makes a collision
ordinary input, not an outage.

## Why it disabled three tests

`tests/backend_server/test_workspaces.py` had four fixtures that each created a workspace
under a **fixed** name — `"Smoke Member Test Workspace"`, `"Test Workspace Smoke"`,
`"Smoke Create Test"`, `"Smoke Delete Target"` — and called `pytest.skip()` when creation did
not return 201.

So the first run whose teardown never fired (an interrupt, a failed delete) left a row behind,
and every run after it collided, got the 500, and skipped. Three tests reported "skipped"
forever and nobody chased it. One such row, created 2026-09-16 20:35, was still in the table
when this was found.

Two defects reinforcing each other: a wrong status code, and a test that treats any failure as
a reason to stop asking.

## Fix

`40716b6ca5`.

`workspaces_db` gains `DuplicateSlugError` and `_is_duplicate_slug`, which matches postgres
`23505` on the `workspaces_slug_key` constraint. `create_workspace` raises it instead of
returning `None`, and the route answers **409** with the offending slug:

```python
except workspaces_db.DuplicateSlugError as e:
    return jsonify({"error": str(e), "slug": e.slug}), 409
```

All four test fixtures now use a unique name per run (`uuid.uuid4().hex[:8]`) and **assert**
rather than skip: creating a workspace as admin is something the platform must be able to do,
not an environment condition. The stale row was deleted.

## Verification

Against the deployed server, a second create with the same name answers `409` naming the slug,
and `tests/backend_server/test_workspaces.py` runs with no skips — 24 passed across the three
repaired files where nine tests previously skipped.
