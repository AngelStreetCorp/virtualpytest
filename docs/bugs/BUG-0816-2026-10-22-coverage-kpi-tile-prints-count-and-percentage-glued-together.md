# BUG-0816 — The Coverage "Covered" KPI tile reads "1915%": the count 19 and the rate 15% have no separator

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0816                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | Low                                                       |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |
---

## Symptom

Found by the QA sweep of 2026-10-22 (finding ANALYST-A-14, in `docs/tasks/QA-ANALYST-findings.md`); reproduced against the live app.

- **Page / route:** /test-plan/coverage (also Localize > Screens taught)
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open `/test-plan/coverage`.
2. Read the second KPI tile, then copy its text.

**Expected:** "19" and "15 %" (or "19 / 131 (15 %)").

**Actual:** The tile's text is `1915%`. The same pattern on Localize > Screens taught reads "78.6%327/416" and "10/ 34".

Evidence:

- [coverage.png](../tasks/qa-evidence/analyst/pass1/coverage.png)
- [pass2-loc-screens-taught.png](../tasks/qa-evidence/analyst/pass2-loc-screens-taught.png)

## Root cause

`frontend/src/pages/Coverage.tsx:288-292` builds `value` + `extra`, rendered one after the other at `:319-321`.

## Fix

The separator lives in the shared tile component, so every page that shows a tile with a
second figure gets it (`frontend/src/components/common/PageChrome.tsx`, `StatTiles`):

```tsx
{extra ? ` · ${extra}` : null}
```

The two call sites that glued a number to another number are fixed as well:

- `frontend/src/pages/Coverage.tsx` — the tile reads "78.6% · 327/416";
- `frontend/src/pages/LocalizeCoverage.tsx` — the "Interfaces ready" tile moves the total into the
  value ("10 / 34") instead of printing it after the label.

## Tests

`tests/frontend/StatTilesSeparator.test.tsx` — 2 cases: a tile with a second figure reads
"19 · 15%", a tile without one is untouched.

Verified against the pre-fix sources via `git stash`: **1 failed / 1 passed**; on the fixed sources
**2 passed**.

## Verification

Checked in dark and light at 1440 px: the Coverage tile reads "78.6% · 327/416" and the
Localize tile reads "10 / 34". No tile on either page prints two numbers without a separator.

Deployed as `main-2026.10.22-89636` (integration `int-mvjsys09db00cb`), verified on the live site.
