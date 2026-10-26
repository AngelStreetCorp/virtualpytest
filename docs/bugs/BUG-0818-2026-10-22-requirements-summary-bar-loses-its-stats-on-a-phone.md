# BUG-0818 — On a 390 px phone the Requirements summary bar loses its right-hand stats and runs its title into the first number

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0818                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | Low                                                       |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |
---

## Symptom

Found by the QA sweep of 2026-10-22 (finding CHAOS-08, in `docs/tasks/QA-CHAOS-findings.md`); reproduced against the live app.

- **Page / route:** /test-plan/requirements
- **Viewport / theme:** 390 px, dark and light

Steps to reproduce:

1. Open `/test-plan/requirements` at 390 x 844.

**Expected:** The bar wraps or scrolls; no stat is cut.

**Actual:** It reads `RequirementsTotal 131 | Active 131 | No coverag...`; the P1/P2/P3 chips are gone. At 1440 px the bar shows all six stats. The bar is a single non-wrapping row.

Evidence:

- [phone-dark-test-plan-requirements.jpg](../tasks/qa-evidence/chaos/phone-dark-test-plan-requirements.jpg)
- [desktop-dark-test-plan-requirements.jpg](../tasks/qa-evidence/chaos/desktop-dark-test-plan-requirements.jpg)

## Root cause

Not diagnosed yet: the QA sweep reported the symptom only.

## Fix

The bar and its stats group wrap (`frontend/src/pages/Requirements.tsx`):

```tsx
<Box display="flex" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={1}>
  …
  <Box display="flex" alignItems="center" gap={{ xs: 1.5, sm: 4 }} flexWrap="wrap">
```

The stats group was one non-wrapping row with a 32 px gap, so on a phone it ran off the right
edge and the P1/P2/P3 chips were gone. The gap now shrinks on a phone and both rows wrap.

## Tests

`tests/frontend/RequirementsSummaryBar.test.tsx` — 2 cases: the bar and the stats group wrap,
and all six stats are still in the bar.

Verified against the pre-fix sources via `git stash`: **2 failed**; on the fixed sources
**2 passed**.

## Verification

Measured on the worktree build at 390 px: the bar is 340 px wide with no overflow
(`scrollWidth` 340) and reads "Requirements | Total 131 | Active 131 | No coverage 112 | P1: 71 |
P2: 52 | P3: 8" over two lines — the three priority chips are back.

Checked in dark and light, at 390 px and at 1440 px (where the bar is one row again).
Evidence: [after 390 dark](../tasks/qa-evidence/fix/bug-0818-after-390-dark-en.png) ·
[after 390 light](../tasks/qa-evidence/fix/bug-0818-after-390-light-en.png).

Deployed as `main-2026.10.22-89636` (integration `int-mvjsys09db00cb`), verified on the live site.
