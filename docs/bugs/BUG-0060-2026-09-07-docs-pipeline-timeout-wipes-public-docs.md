# BUG-0060 — every /docs page broke because the doc pipeline deletes before it copies

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                 |
|-----------|-----------------------------------------------------------------------|
| ID        | BUG-0060                                                              |
| Reported  | 2026-09-07                                                            |
| Status    | Fixed (pending frontend deploy)                                       |
| Severity  | High (all in-app documentation unreachable in production)             |
| Area      | frontend/scripts/copy-docs.sh · frontend/scripts/prebuild.sh          |
| Fixed in  | build 8713                                                            |
| Commit    | this commit                                                           |

---

## Symptom

Every `/docs/*` page on virtualpytest.angelstreet.io rendered the red
**"Error Loading Documentation"** box. CI `e2e-pages` went from 43/43 green (run at 17:46 UTC)
to **8 failed** (18:46 UTC) and stayed there — Get Started, QuickGuide, FAQ, Features,
User Guide, Technical, Screenshots, Videos.

Reproducible against the live site:

```
$ curl -s https://virtualpytest.angelstreet.io/docs/faq/README.md | head -1
<!doctype html>
```

Every `/docs/**` asset — `docs-manifest.json` included — fell through to the SPA index, because
the files were not in the bundle. `Documentation.tsx` fetches `/docs/<section>/README.md`, sees
HTML instead of Markdown, and shows the error box.

On the frontend VM, `frontend/public/docs/` contained **only `api/`**: no markdown, no manifest.

## Root cause

`copy-docs.sh` began with `rm -rf public/docs` and then copied into it in place — API docs
first, markdown second, manifest last. `prebuild.sh` runs it via `run_step`, i.e. under
`timeout -k 5` with **whatever is left of a 120 s budget shared by the whole doc pipeline**
(`DOC_TIMEOUT`), and copy-docs is the *last* of four steps. The generators ahead of it
(OpenAPI HTML, MCP reference, and the Bandit/npm-audit security scan) ate the budget, so
copy-docs was killed part-way — after the API docs, before the markdown. The good copy it had
already deleted was gone.

Delete-then-copy under a kill-timeout means a timeout cannot leave the docs *stale*; it can
only leave them *broken*.

Why it started on 2026-09-07 rather than earlier: prebuild hashes its doc inputs and restores a
cached snapshot when they are unchanged, skipping steps 2-5 entirely. The BUG-0058 doc commits
(18:33 and 18:49 UTC) touched `docs/`, the hash changed, the cache gate missed, and the full
pipeline ran for the first time in a while — straight into the budget.

The cached snapshot at `/opt/vpt-cache/docs/public_docs` was *not* corrupted: prebuild only
snapshots a clean run (`DOC_OK=1`), so the last good copy survived and is what the fixed build
restores.

## Fix

`copy-docs.sh` — stage, then swap:

- Everything is written to `public/.docs-build.$$`; `public/docs` is untouched until the end.
- A `trap … EXIT INT TERM` removes the staging directory, so a kill leaves no debris.
- The final swap refuses to publish an obviously incomplete tree (no manifest, or zero markdown
  files) and keeps the existing docs instead.
- If the swap itself fails, the previous `public/docs` is moved back.

`prebuild.sh`:

- copy-docs no longer runs on the leftovers of the shared budget. It is local file copying, so
  it gets its own fixed budget (`VPT_COPY_DOCS_TIMEOUT`, default 90 s).
- The cache-restore path had the same delete-first shape (`rm -rf public/docs` then `cp -a`);
  it now copies to a staging dir and swaps.

## Verification

Locally, in `frontend/`:

- Normal run: 150 markdown files, 14 manifest sections, no staging directory left behind.
- **SIGTERM at 3 s**, during "Following markdown links recursively" — exactly the phase that
  broke production. Child exits 143; `public/docs` still has its 150 markdown files and all
  15 entries, `git status` reports it byte-identical to HEAD, no staging leftovers. Under the
  old script this is precisely the kill that emptied it.
- Incomplete-build guard: run against an empty `../docs`, the swap is refused (exit 1), the
  sentinel `public/docs` survives untouched.
