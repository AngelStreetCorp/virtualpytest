# BUG-0813 — On a phone two column headers of the Unknown screens table run into their neighbour ("ScreenProposed name", "FramesActions")

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0813                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                       |
| Severity  | Low                                                       |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding DEVELOPER-09, in `docs/tasks/QA-DEVELOPER-findings.md`); reproduced against the live app.

- **Page / route:** /configuration/interface/stb_tv/unknown
- **Viewport / theme:** 390 px, light (same in dark)

Steps to reproduce:

1. Open the page at 390 px.
2. Look at the header row of the "Needs a name" table.

**Expected:** Five readable headers.

**Actual:** "Screen" overflows its 34 px cell by 6 px and "Frames" its 27 px cell by 16 px; the cells have `overflow: visible`, no ellipsis and no `title`. Breaks UI_STYLE rules S3 and S9.

Evidence:

- [developer-09-phone-clipped-headers.png](../tasks/qa-evidence/developer/developer-09-phone-clipped-headers.png)

## Root cause

`frontend/src/pages/UserInterfaceUnknown.tsx` — the "Needs a name" table was `tableLayout: 'fixed'`
with percentage widths (Screen 10 %, Proposed name 38 %, Type 12 %, Frames 8 %, Actions 32 %). At
390 px the table is about 340 px wide, so the header cells were 34 px (Screen) and 27 px (Frames) —
narrower than the words in them ("Frames" is about 43 px). The cells had `overflow: visible`, no
ellipsis and no `title`, so the headers ran into their neighbours: "ScreenProposed name" and
"FramesActions".

The same table shape broke UI_STYLE S3 (column widths must not follow the content) and S9 (text
must wrap or ellipsise on purpose, never clip silently).

## Fix

`frontend/src/pages/UserInterfaceUnknown.tsx`:

- The columns get their own widths through a `<colgroup>` — the thumbnail column, the type column,
  the frames column and the actions column are sized for their content, the name column takes the
  rest (UI_STYLE S3).
- The table keeps that width on a narrow screen (`minWidth`), so the container scrolls sideways
  instead of squeezing the columns into unreadable slivers. This is the pattern the other wide
  tables of the app use (`FlakyTests`, `Milestones`, `NeverExecuted`, `Models`).
- Every header cell ellipsises on purpose and keeps its full text in the `title` (UI_STYLE S9).
- The "Excluded as content" table, which had the same shape, gets the same treatment.

## Verification

- `tests/frontend/UserInterfaceUnknown.test.tsx`: the table has a `<colgroup>` with five columns,
  the name column takes the rest, and every header keeps its text in a `title`.
- `frontend/scripts/ui-check.mjs` — no findings.

In the browser at 390 px: the header row reads "Screen | Proposed name | Type | Frames | Actions"
with no overlap, and the table scrolls sideways inside its card
(screenshot: `../tasks/qa-evidence/fix/bug-0813-unknown-screens-phone-headers.png`).
