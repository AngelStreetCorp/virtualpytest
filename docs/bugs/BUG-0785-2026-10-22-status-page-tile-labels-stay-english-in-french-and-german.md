# BUG-0785 — The Status page tile labels (Services healthy, Server CPU, RAM, Disk) stay English in French and German although the translations exist

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0785                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | frontend / i18n                                              |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |
---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-10, in `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** /status
- **Viewport / theme:** 1440 px, dark, French

Steps to reproduce:

1. Switch the app to French.
2. Open `/status` and read the four tiles.

**Expected:** "Services sains", "CPU du serveur", "RAM du serveur", "Disque du serveur" (already in the catalogue).

**Actual:** The tiles read the English text while the table underneath is translated, so the page looks half broken.

Evidence:

- [ops-10-status-untranslated-fr.png](../tasks/qa-evidence/ops/ops-10-status-untranslated-fr.png)
- Fix evidence: [after FR](../tasks/qa-evidence/fix/bug-0785-after-fr.png) · [after DE](../tasks/qa-evidence/fix/bug-0785-after-de.png)

## Root cause

The tiles are raw literals, not `t()` calls (`frontend/src/pages/Status.tsx:1304`, `:1308`). `src/pages/Status.tsx` is not in `frontend/src/i18n/translated-files.txt`, so the CI i18n check does not flag it.

Two more things kept the page half-translated in French and German, and both are on the same page:

- the page header ("System Status", "Last checked: …", "Refresh now") and the uplink tile's caption
  were raw literals too, and their keys were not in the catalogues at all;
- four keys the page uses were **stubs** in the catalogues — the value was the English key
  ("VM summary", "Collapse VM summary", "Expand VM summary", "Hide details"), so the page showed
  English even though the file had an entry. That is BUG-0808's defect, on this page.

## Fix

- The four tile labels now go through `t()`, using the keys the dashboard's system cards already
  use: `Services healthy`, `Server CPU`, `Server RAM`, `Server disk` (the dashboard's spelling —
  the two pages now say the same thing).
- The page header and the uplink tile are translated as well: `System Status`,
  `Last checked: {time}`, `Refresh now`, `Saturated`, `Busy`, the uplink caption and its tooltip
  (seven new keys, with the French and German wording).
- The four stubs the page shows are now real translations (`Synthèse des VM` / `VM-Übersicht`,
  `Masquer les détails` / `Details ausblenden`, and the two collapse/expand labels).
- **`src/pages/Status.tsx` is now listed in `frontend/src/i18n/translated-files.txt`**, so the CI
  i18n check refuses a raw English literal in that page from now on. That is what let the page
  drift in the first place.

## Tests

`tests/frontend/StatusTilesI18n.test.ts` — 3 cases: the page is listed in
`translated-files.txt` (so the check enforces it); every tile label has a French and a German
translation that is not the English key; the header strings have one too.

Verified against the pre-fix sources via `git stash`: **2 failed / 1 passed**; on the fixed
sources **3 passed**.

## Verification

`node scripts/i18n-check.mjs` → **0 errors** with `src/pages/Status.tsx` enforced (141 files).
`tsc --noEmit` clean · eslint clean on the changed files.

Read in a real browser at 1440 px on the worktree build:

| | French | German |
|---|---|---|
| page title | État du système | Systemstatus |
| last checked | Dernière vérification : 4:17:47 PM | Zuletzt geprüft: 4:16:17 PM |
| tiles | Services sains · CPU du serveur · RAM du serveur · Disque du serveur | Dienste gesund · Server-CPU · Server-RAM · Server-Festplatte |
| summary block | Synthèse des VM · Masquer les détails | VM-Übersicht · Details ausblenden |

The table underneath was already translated and still is.

Deployed as `main-2026.10.22-89636` (integration `int-mvjsys09db00cb`), verified on the live site.
