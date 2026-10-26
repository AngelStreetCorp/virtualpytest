# BUG-0819 — On a 390 px phone the Interface table breaks interface names in the middle of the word

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0819                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | Low                                                       |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |
---

## Symptom

Found by the QA sweep of 2026-10-22 (finding CHAOS-09, in `docs/tasks/QA-CHAOS-findings.md`); reproduced against the live app.

- **Page / route:** /configuration/interface
- **Viewport / theme:** 390 px, dark and light

Steps to reproduce:

1. Open `/configuration/interface` at 390 x 844.

**Expected:** Whole identifiers, or horizontal scrolling.

**Actual:** Names break at character level (`stb_android_mobil` / `e`, `android_tablet_tes` / `t`), "Variants" becomes `Varian` / `ts`, "Active" is cut to `Acti`, and one cell is clipped to 8 px (`scrollWidth 81` vs `clientWidth 8`). Not the same as BUG-0768 (header and body in two geometries): check both when fixing this page.

Evidence:

- [phone-dark-configuration-interface.jpg](../tasks/qa-evidence/chaos/phone-dark-configuration-interface.jpg)

Related bugs: BUG-0768.

## Root cause

Not diagnosed yet: the QA sweep reported the symptom only.

## Fix

The table asks for a minimum width and the container scrolls sideways instead of clipping
(`frontend/src/pages/UserInterface.tsx`):

```tsx
<Table size="small" sx={{ tableLayout: 'fixed', width: '100%', minWidth: isMobile ? 520 : undefined, … }}>
…
<TableContainer component={Paper} variant="outlined" sx={{ boxShadow: 'none', overflowX: 'auto' }}>
```

The container had `overflowX: 'hidden'`, so the table was cut instead of scrolled, and the
percentage widths of the fixed layout left the Name column a few characters wide — hence
`stb_android_mobil` / `e`. With a minimum width the columns keep their space and the user
scrolls the table sideways.

## Tests

`tests/frontend/InterfaceTablePhone.test.tsx` — 1 case: the table has a minimum width and its
container scrolls.

Verified against the pre-fix sources via `git stash`: **1 failed**; on the fixed sources
**1 passed**.

## Verification

Measured on the worktree build at 390 px: the table is 520 px wide in a 356 px container
(`overflow-x: auto`) and the Name column is 234 px — `stb_android_mobile`, `virtualpytest_test`
and `android_tablet_test` are written whole, no character-level breaks.

Checked in dark and light. Evidence:
[after 390 dark](../tasks/qa-evidence/fix/bug-0819-after-390-dark-en.png) ·
[after 390 light](../tasks/qa-evidence/fix/bug-0819-after-390-light-en.png).

Deployed as `main-2026.10.22-89636` (integration `int-mvjsys09db00cb`), verified on the live site.
