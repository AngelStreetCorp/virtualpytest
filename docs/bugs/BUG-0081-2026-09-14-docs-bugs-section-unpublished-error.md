# BUG-0081 — Docs → Bugs shows "Error Loading Documentation"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0081                                                     |
| Reported  | 2026-09-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / docs site                                         |
| Fixed in  | build NNNN                                                   |
| Commit    | `this commit`                                                |

---

## Symptom

On the docs site, **Docs → Bugs** (`/docs/bugs`) shows a red panel:

```
Error Loading Documentation
Invalid documentation response (received HTML instead of Markdown): /docs/bugs/README.md
```

Every other Docs menu entry renders normally. Checked live before the fix — each section's
`README.md` returned markdown except `bugs`, which returned `<!doctype html>`.

## Root cause

An earlier commit stopped publishing `docs/bugs/` (the tracker named internal things), but left the **Bugs** entry in the Docs
menu (`frontend/src/config/navItems.tsx` → `DOCS_ITEMS`).

So the menu offered a section the build no longer produced. `Documentation.tsx` fetches
`/docs/bugs/README.md`; the file is absent, the SPA fallback answers **`200` with `index.html`**,
and the HTML sniff added for BUG-0060 reports it as an invalid documentation response. On an SPA a
missing docs file can never surface as a `404` — every stale docs link produces exactly this error.

Nothing caught it: the Playwright page sweep asserts no "Error Loading Documentation", but its
`PAGES` list is hand-maintained and never contained `/docs/bugs`.

## Fix

The tracker is published again — the answer to "it names internal things" is to stop naming them,
not to hide the section.

- **Anonymized 14 bug files in place** per `docs/agent/release/ANONYMIZATION.md`; the leak gate
  and gitleaks are clean under `docs/bugs/`.
- **`frontend/scripts/copy-docs.sh`**: `bugs/README.md` back as a copy entry point, `bugs/*` removed
  from the excluded trees, and the pass that demoted the release note's 81 `[BUG-XXXX](../bugs/…)`
  links to plain text deleted — those links resolve again on the site.
- **`frontend/src/pages/Documentation.tsx`**: `bugs: ['How to log a bug']` restored in
  `STRIP_SECTIONS`, so readers get the index without the contributor process section.
- **`docs/bugs/README.md`**: a standing note (in the stripped section, so contributors see it and
  readers don't) that this tracker is public and what must never appear in a report.
- **`tests/frontend/DocsNavItems.test.tsx`** (new): every markdown Docs menu entry must have a
  published `frontend/public/docs/<section>/README.md`. `/docs/api` and `/docs/security` are
  excluded — they are React routes and fetch no markdown. This is the general guard: a menu item
  pointing at an unpublished section now fails a test instead of shipping a page that can only error.

## Verification

- `npx vitest run --config ../tests/frontend/vitest.config.ts ../tests/frontend/DocsNavItems.test.tsx`
  passes; reverting `navItems.tsx` to the unpublished-section state fails it with
  `Bugs → /docs/bugs` (checked both directions).
- `bash frontend/scripts/copy-docs.sh` → 171 markdown files, 14 sections, `bugs` in
  `docs-manifest.json`, 84 files under `frontend/public/docs/bugs/`.
- Relative-link scan over the published copy: no dead `.md` links (the only hit is the
  `BUG-XXXX-<date>-<slug>.md` format example inside the release note's stripped section).
- `scripts/security/leak_gate.sh --all` → `✓ identifiers: clean (4 terms)`; the pre-existing
  full-tree secret findings are unrelated (`.env`, `docs/agent/*`, TASK-08 §4).
- After deploy: `/docs/bugs` renders the index, each `BUG-XXXX` page opens, and the release note's
  bug links resolve.
