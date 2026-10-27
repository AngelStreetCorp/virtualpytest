# BUG-0967 — A navigation tree write answered with an empty 500 when the platform could not check whether the tree was a prod tree

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0967                                                     |
| Reported  | 2026-10-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_server (navigation tree write guard)                 |
| Fixed in  | build 90256 |
| Commit    | branch `fix/ci-backend-server-tests`                         |

---

## Symptom

Every write on the navigation-trees blueprint — a per-node, per-edge or subtree save, and the
`POST /server/navigationTrees/<tree_id>/refresh` call that makes a write visible to the hosts —
died with an **HTTP 500 and an empty body** whenever the platform's own guard could not reach the
database. The route never ran, so the caller got a status code with nothing to read: the request
looked like a server crash with no cause.

```
POST /server/navigationTrees/tree-1/refresh?team_id=team-1  ->  500 (empty body)

ERROR app.py:875 Exception on /server/navigationTrees/tree-1/refresh [POST]
Traceback (most recent call last):
  File ".../backend_server/src/routes/server_navigation_trees_routes.py", line 64, in _redirect_prod_tree_writes_to_dev
    redirect = resolve_dev_tree_for_prod(args[key], team_id)
AttributeError: 'NoneType' object has no attribute 'table'
```

The guard was added on 2026-10-26 (TASK-173) and had no test of its own, so nothing caught it
until the CI job that runs the backend server suite went red: `3 failed, 3370 passed` — all three
in `tests/backend_server/test_navigation_tree_refresh.py`.

## Root cause

TASK-173 made "prod trees are only written by Publish" a server-side rule: a write aimed at a
prod tree is re-aimed at the dev tree it was published from. The rule is enforced by a blueprint
`before_request` hook, `_redirect_prod_tree_writes_to_dev`
(`backend_server/src/routes/server_navigation_trees_routes.py`), which runs in front of **every**
write on the blueprint and calls `resolve_dev_tree_for_prod()`
(`shared/src/lib/database/userinterface_publish.py`).

That resolver reads the tree and its userinterface through `get_supabase()`, which is
`get_supabase_client()`: it returns **`None`** when the process has no Supabase client — the
"NO DB CLIENT — missing environment variables" state the platform logs as BUG-0109, and the
convention everywhere else in the code base is that a database operation is then *skipped*, not
fatal. The resolver did not honour that convention: it dereferenced the missing client straight
away, so `supabase.table(...)` raised `AttributeError` inside the hook, the request was aborted
before the route ran, and Flask answered with its default 500 — no JSON, no message.

The same crash was one line away in the batch-save path (`save_tree_data_api`), which calls the
same resolver for the same reason.

## Fix

Two files, both in the write path:

- `shared/src/lib/database/userinterface_publish.py` — `resolve_dev_tree_for_prod()` returns
  `None` when there is no Supabase client. There is no prod tree to redirect to in that state,
  and nothing the write could be persisted to either, so "not a prod tree" is the honest answer.
- `backend_server/src/routes/server_navigation_trees_routes.py` — the hook wraps the lookup. The
  rule "prod can never be written by an edit" has to survive a database that answers with an
  error, so the write is **refused** when the lookup fails, with a JSON body the caller can read
  (`503` and `success: false`) instead of an empty 500.

A new test file, `tests/backend_server/test_navigation_tree_prod_redirect.py`, covers the guard
itself — the first test of it — and pins all three behaviours: a write without a database still
reaches its route, a failing lookup refuses the write with a readable body, and a prod-tree write
is still re-aimed at the dev tree.

## Verification

- `tests/backend_server/test_navigation_tree_refresh.py` and
  `tests/backend_server/test_navigation_tree_prod_redirect.py`: 11 passed. Without the fix the
  same set reports **5 failed** — the three the CI job caught plus the two new ones.
- The whole backend server suite: `2774 passed, 0 failed` locally (20 setup errors are the
  live-server tests, which need a server on `localhost:5109`).
- CI job `Backend Server Unit Tests` on main: `3373 tests, 0 failed` (was `3 failed, 3370 passed,
  13 skipped`).
