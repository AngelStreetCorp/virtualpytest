# BUG-0372 — QuickTest rail reloaded its list on every refresh and repeated the page title

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0372                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

On `/builder/quick-test` the saved-tests rail started empty with a spinner after every page
refresh, then filled in once the testcase list came back. The rail also had its own
"Quick tests" heading under the page header's "QuickTest", with the search box on a second row.

## Root cause

`refreshTestcaseList` in `features/quicktest/frontend/hooks/useQuickTestBuilder.ts` went through
`getCachedTestCaseList`, an in-memory cache (`frontend/src/utils/requestCache.ts`) that a browser
refresh wipes, and the list state started as `[]`.

## Fix

- `useQuickTestBuilder.ts`: the quick-test list (id, name, interface, variant only) is kept in
  localStorage per server URL (`virtualpytest:quicktest-list:<url>`). The rail starts from it, the
  fetch revalidates in the background, and save / delete update it. A failed fetch keeps the
  cached list instead of blanking the rail.
- `QuickTestBuilder.tsx`: the "Quick tests" heading is gone; search and + share one row, with the
  spinner inside the search box only while there is nothing cached.

## Verification

Open `/builder/quick-test`, wait for the list, refresh: the list is there immediately. Save or
delete a quick test, refresh: the change is kept.
