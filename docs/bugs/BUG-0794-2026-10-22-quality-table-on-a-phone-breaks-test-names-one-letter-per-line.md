# BUG-0794 — On a 390 px phone the Quality table squeezes the Test column to one letter per line and clips the Host column

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0794                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |
---

## Symptom

Found by the QA sweep of 2026-10-22 (finding TESTER-11, in `docs/tasks/QA-TESTER-findings.md`); reproduced against the live app.

- **Page / route:** /test-results/quality
- **Viewport / theme:** 390 px, dark (fine at 1440 px)

Steps to reproduce:

1. Open the app at 390 px.
2. Open Test results > Quality (Flaky tab).
3. Read the table.

**Expected:** A readable test name and a table that scrolls horizontally.

**Actual:** The table is 970 px wide inside a 390 px viewport and the Test column collapses (`g / a / m / e / _ / s ...`) while "host-clone-1 / host-clone-1_Ho..." is cut at the right edge. The page itself does not overflow, so the overflow is hidden inside the table's scroll container. Same family as BUG-0736, different page.

Evidence:

- [tester-08-quality-table-squeezed-on-phone.png](../tasks/qa-evidence/tester/tester-08-quality-table-squeezed-on-phone.png)

Related bugs: BUG-0736.

## Root cause

Not diagnosed yet: the QA sweep reported the symptom only.

## Fix

The Test column now asks for a width and the whole table asks for a minimum width, so the
container scrolls sideways instead of squeezing the names into one letter per line:

- `frontend/src/pages/FlakyTests.tsx` — the first `<col>` gets `width: 220` and the table
  `minWidth: 1190` (the sum of the column widths);
- `frontend/src/pages/SlowTests.tsx` — the same first-column width, `minWidth: 950`;
- `frontend/src/pages/NeverExecuted.tsx` — the same first-column width, `minWidth: 640`.

The `<colgroup>` was already there, but the **first** `<col>` had no width at all, so the fixed
table layout gave the Test column whatever was left over — nothing. The table container keeps
`overflow-x: auto`, so the table now scrolls horizontally on a phone and every column keeps the
width it asks for.

## Tests

`tests/frontend/QualityTableColumns.test.tsx` — 3 cases (one per table): the first `<col>` has an
explicit width of at least 200 px and the table has a minimum width.

Verified against the pre-fix sources via `git stash`: **3 failed**; on the fixed sources
**3 passed**.

## Verification

Measured on the worktree build at 390 px (Vite dev + the live backend):

| | before | after |
|---|---|---|
| Test column | 0 px (name broke one letter per line) | **220 px** (`stb_android_mobile` on one line) |
| table width | 970 px in a 358 px box | 1190 px in a 358 px box |
| table container | `overflow-x: auto` | `overflow-x: auto` (scrolls sideways) |

Checked in dark and light, at 390 px, in EN / FR / DE — the Test column keeps its width and the
table scrolls. Evidence: [after 390 dark](../tasks/qa-evidence/fix/bug-0794-after-390-dark-en.png) ·
[after 390 light](../tasks/qa-evidence/fix/bug-0794-after-390-light-en.png).

Deployed as `main-2026.10.22-89636` (integration `int-mvjsys09db00cb`), verified on the live site.
