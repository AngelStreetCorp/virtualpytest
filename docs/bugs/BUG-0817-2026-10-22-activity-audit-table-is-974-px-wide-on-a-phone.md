# BUG-0817 — On a 390 px phone the Activity audit table is 974 px wide, so Target, Details and Actor are off screen

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0817                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | Low                                                       |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |
---

## Symptom

Found by the QA sweep of 2026-10-22 (finding ANALYST-A-15, in `docs/tasks/QA-ANALYST-findings.md`); reproduced against the live app.

- **Page / route:** /configuration/logs > Activity
- **Viewport / theme:** 390 px, dark

Steps to reproduce:

1. Open Logs > Activity at 390 px.
2. Look at the table.

**Expected:** At least event, target and actor are readable.

**Actual:** Columns total 974 px in a 324 px box (When 89, Event 206, Target 314, Details 71, Actor 294). Only "When" and a word of "Event" are visible; all 504 rows are in the DOM at once. Same shape as BUG-0736 on a newer tab.

Evidence:

- [phone-activity.png](../tasks/qa-evidence/analyst/phone-activity.png)

Related bugs: BUG-0736.

## Root cause

Not diagnosed yet: the QA sweep reported the symptom only.

## Fix

The activity table is a fixed layout that fills its box, and its cells wrap
(`frontend/src/pages/Logs.tsx`): the page-wide `commonTableSx` forbids line breaks in every cell
(`white-space: nowrap`), which is right for the log tables but pushed the five activity columns to
974 px inside a 324 px phone box — and because the table sized itself to its longest cell, it
stayed that wide even after the cells were allowed to wrap.

```tsx
<Table size="small" sx={{ ...commonTableSx, width: '100%', tableLayout: 'fixed', '& .MuiTableCell-root': { whiteSpace: 'normal' } }}>
```

The Target column additionally breaks inside a long path (`overflowWrap: 'anywhere'`), so a
monospace target wraps instead of widening the table, and the Details column — the longest text of
the five — is left out on a phone (`display: { xs: 'none', sm: 'table-cell' }`). It stays on a
wider screen and in the CSV export.

## Tests

`tests/frontend/ActivityTablePhone.test.tsx` — 1 case: an activity cell is `white-space: normal`,
the target breaks inside the path, and the table fills its box with a fixed layout.

Verified against the pre-fix sources via `git stash`: **1 failed**; on the fixed sources
**1 passed**.

## Verification

Measured on the worktree build at 390 px: the activity table is 324 px wide in a 326 px box — it
was 974 px — and the five columns share the width (When 65 px, Event 81 px, Target 97 px, Actor
81 px). At 1440 px the table is 1102 px wide with the Details column back.

Checked in dark and light. Evidence:
[after 390 dark](../tasks/qa-evidence/fix/bug-0817-after-390-dark-en.png) ·
[after 390 light](../tasks/qa-evidence/fix/bug-0817-after-390-light-en.png).

Deployed as `main-2026.10.22-89636` (integration `int-mvjsys09db00cb`), verified on the live site.
