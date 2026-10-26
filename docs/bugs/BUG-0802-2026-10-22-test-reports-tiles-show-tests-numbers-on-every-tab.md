# BUG-0802 — The Test Reports headline tiles show the Tests numbers on every tab, including above "No shared links"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0802                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | frontend                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding ANALYST-A-10, in `docs/tasks/QA-ANALYST-findings.md`); reproduced against the live app.

- **Page / route:** /test-results/reports (Campaigns and Shared links tabs)
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open `/test-results/reports` and note the tiles (66.0 % / 26.5 s).
2. Click Campaigns, then Shared links.

**Expected:** Tiles that describe the rows on screen.

**Actual:** The tiles do not change. On Campaigns the table shows 16 rows, 14 passed and 2 failed (87.5 %), average about 90 s; on Shared links the page states 66 % above "No shared links".

Evidence:

- [pass2b-reports-campaigns.png](../tasks/qa-evidence/analyst/pass2b-reports-campaigns.png)
- [pass2b-reports-sharedlinks.png](../tasks/qa-evidence/analyst/pass2b-reports-sharedlinks.png)

## Root cause

`frontend/src/pages/TestReports.tsx:755` builds the tiles from `scriptResults`; the tile block sits above the tab switch.

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.
