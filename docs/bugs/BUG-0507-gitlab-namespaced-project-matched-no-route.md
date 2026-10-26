# BUG-0507 — A namespaced GitLab project matched no route, so no project ever showed its files

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0507                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | features/gitlab                                              |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The GitLab page connected, listed the projects and showed the tiles — and then every project came
up with an **empty file tree and no README**. The browser console carried three `400`s. Clicking a
file did nothing, because there was no file.

Nothing at all looked broken: the instance was reachable, the projects listed, their names were
right. It is the kind of failure that reads like "the repository is empty".

## Root cause

The project was a **path segment**, and a GitLab project path is `group/project`.

`features/gitlab/frontend/gitlabApi.ts` correctly URL-encoded it:

```ts
`/projects/${encodeURIComponent(project)}/tree?ref=…`   // → /projects/group%2Fmy-project/tree
```

But Flask's default `<project>` string converter does not accept a `/` in the matched segment, and
`%2F` decodes to one. **No route matched.** The request then fell through to the `auto_proxy`
catch-all (BUG-0362), whose handler is a host helper — so the answer was:

```
400 {"error":"host_name required in request body or query parameters","success":false}
```

`host_name` is a **device host** parameter. This feature has never used it. The 400 pointed at a
completely unrelated concept, which is what made the real cause so hard to see from the browser.

Eight routes were affected, and between them they are the entire repository view:

| Before | After |
|---|---|
| `GET /projects/<project>` | `GET /project?project=` |
| `GET /projects/<project>/branches` | `GET /project/branches?project=` |
| `GET /projects/<project>/tree` | `GET /project/tree?project=` |
| `GET /projects/<project>/readme` | `GET /project/readme?project=` |
| `GET /projects/<project>/file` | `GET /project/file?project=` |
| `GET /projects/<project>/pipelines` | `GET /project/pipelines?project=` |
| `GET /projects/<project>/pipelines/<id>/jobs` | `GET /project/pipelines/jobs?project=&pipeline_id=` |
| `GET /projects/<project>/jobs/<id>/trace` | `GET /project/jobs/trace?project=&job_id=` |
| `POST /projects/<project>/trigger` | `POST /project/trigger?project=` |

The singular `/project` prefix avoids colliding with `GET /projects`, which stays the list.

**Every project on a real GitLab is namespaced, so this broke all of them** — including the one
layout that works, a project at the root of a personal namespace with no group, is the exception
rather than the rule.

## Why it was not caught

1. The bundler never used these routes. `build_customer_bundle.sh` clones through git with
   `VPT_GITLAB_*` config, so the packaging path — the part exercised by the real build — was
   completely independent of them.
2. The route test **allowed the failing status**: `assert response.status_code in (200, 400, 404,
   502)`. A test that accepts 400 cannot catch a bug that produces 400.
3. The route tests **skip without a live backend** (`tests/backend_server/conftest.py` skips the
   whole directory when `localhost:5109` is unreachable), so in a normal CI run they did not
   execute at all.

It only surfaced when an instance was configured on a real server and a real, namespaced project
was selected.

## Two more defects behind the same symptom

Fixing the routes was not enough — the repository view came back **still** empty, which is what
pushed this past a single cause.

### B. GitLab v4 has no `/projects/:id/readme`

`gitlab_api.readme()` called an endpoint that does not exist:

```python
data = _request(f'/projects/{project_ref(project)}/readme{query}', api=api, tok=tok)
```

Verified against the running instance: `GET /api/v4/projects/3/readme` → **404**. A repository
file is only reachable through `/repository/files/:file_path`, and the filename is not known in
advance — it may be `README.md`, `Readme.rst` or plain `README`. `readme()` now lists the root
tree and resolves the name from it, preferring `.md` over `.rst`, and treats a project with no
README as **None**, which is a normal state rather than an error.

### C. A missing README blanked the file tree

`loadRepo()` fetched the tree and the README in one `Promise.all`, then assigned both in the same
`try`. The README 404 rejected the pair, so the `catch` ran and cleared `entries` as well — the
page showed **"Empty directory"** for a repository holding two files. The tree and the README are
independent; they are now settled separately with `Promise.allSettled`, and a README failure no
longer touches the file list.

Together: A meant no request reached GitLab, B meant one of the two that did came back 404, and C
meant that 404 was allowed to erase the other. All three had to be fixed to see a file.

## The fix

The project is now a **query argument** on both sides, read by one helper
(`_project_or_400()`), which returns `project is required` — a message about a parameter this
feature actually has — instead of letting the request escape to a host helper. `readme()` resolves
from the tree, and the page settles the two independently.

## Tests added

- `test_namespaced_project_never_reaches_the_auto_proxy_catch_all` — asserts on the **body**, not
  just the status, that the answer is not the catch-all's `host_name` complaint.
- `test_project_argument_is_required` — pins our own 400.
- `TestProjectIsNeverAPathSegment` — a dependency-free source guard marked `@pytest.mark.unit`, so
  it **runs without a live backend** (the gap that let this ship): the backend must declare no
  `<project>` path segment, and the client must send the project as `?project=`/`&project=`.
- `TestReadme` — rewritten for the resolve-from-tree contract: markdown wins over rst, a **folder**
  named `readme` is not the README, and a project with no README returns `None` rather than raising.

All three guards were checked by deliberately reintroducing the bug: each one fails, then passes
again once reverted. `readme()` was additionally run against the live GitLab CE 19.4.2 instance,
where it resolves and decodes the README of two different projects.

## Not fixed here

- The `auto_proxy` catch-all answering `host_name required` for an unrelated route is a poor error
  message in its own right (BUG-0362 territory). Worth making unmatched routes say so.