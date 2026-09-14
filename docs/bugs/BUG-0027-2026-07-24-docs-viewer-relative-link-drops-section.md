# BUG-0027 — Clicking a bug link in the in-app Docs errors "received HTML instead of Markdown"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0027                                                     |
| Reported  | 2026-07-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / docs viewer                                       |
| Fixed in  | build 8713                                                   |
| Commit    | `3ed999f34`                                                  |

---

## Symptom

In the in-app **Docs › Bugs** page, clicking any bug row (e.g. BUG-0006) failed with:

```
Error Loading Documentation
Invalid documentation response (received HTML instead of Markdown):
/docs/BUG-0006-2026-07-20-scheduled-script-survives-force-take-control/README.md
```

The URL is wrong twice over: the `bugs/` section segment is dropped, and the bug is treated as a
folder so `/README.md` is appended. Release-note links to the same bug files worked fine.

## Root cause

The Docs viewer's markdown link transformer (`frontend/src/pages/Documentation.tsx`, the `a`
component) has three branches for relative links. `../bugs/BUG-….md` hits the `../` branch, which
correctly prefixes `/docs/` → `/docs/bugs/BUG-…` (why release-note links worked). But the bug
**index** links to its files with a **bare relative path** (`BUG-0006-….md`, no `./` or `../`),
which fell into the "Direct path" branch:

```ts
transformedHref = href.replace(/\.md$/, '').replace(/\/README$/i, '');
```

That produced a **bare** href (`BUG-0006-…`) with no section prefix. The browser then resolved it
relative to the current URL `/docs/bugs`, replacing the last segment → `/docs/BUG-0006-…`. The
router matched `/docs/:section/:page` as `section=BUG-0006-…`, `page=README`, fetched
`/docs/BUG-0006-…/README.md`, missed, and got the SPA's `index.html` (HTML) back — the exact error.

## Fix

`frontend/src/pages/Documentation.tsx` — the "Direct path" branch now resolves a bare relative link
against the **current doc's directory** instead of the site root:

```ts
const currentDoc = getCurrentDocPath();               // e.g. /docs/bugs or /docs/bugs/BUG-0006
const currentDir = page && page !== 'README'
  ? currentDoc.substring(0, currentDoc.lastIndexOf('/'))  // a file -> its folder
  : currentDoc;                                            // a section index -> itself
transformedHref = `${currentDir}/${href.replace(/\.md$/, '')}`
  .replace(/\/+/g, '/')
  .replace(/\/README$/i, '');
```

So from `/docs/bugs`, `BUG-0006-….md` → `/docs/bugs/BUG-0006-…`, and a bug file's own
`[README.md](README.md)` back-link → `/docs/bugs`. Applied identically in `main` and `prod`.

## Verification

1. Docs › Bugs → click any bug row → its report opens (no "received HTML" error); URL is
   `/docs/bugs/BUG-XXXX-…`.
2. From a bug page, the `Bugs index: README.md` back-link returns to `/docs/bugs`, and cross-links
   like BUG-0014 → BUG-0013 resolve.
3. Release-note `../bugs/BUG-XXXX` links still work (the `../` branch is unchanged).
