# BUG-0814 — The "Window" label on the Quality page is painted behind its select, so only the top few pixels of the word show

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0814                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | Low                                                       |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |
---

## Symptom

Found by the QA sweep of 2026-10-22 (finding ANALYST-A-03, in `docs/tasks/QA-ANALYST-findings.md`); reproduced against the live app.

- **Page / route:** /test-results/quality
- **Viewport / theme:** 1440 px, dark and light

Steps to reproduce:

1. Open `/test-results/quality`.
2. Look at the select left of the Export button.

**Expected:** A readable label.

**Actual:** Only the top of the letters is visible: the label box spans y 188-202 while the select starts at y 197. The subtitle repeats the range, but the control itself is broken.

Evidence:

- [quality.png](../tasks/qa-evidence/analyst/pass1/quality.png)
- [deep1-quality-label-dom.png](../tasks/qa-evidence/analyst/deep1-quality-label-dom.png)

## Root cause

`frontend/src/components/reports/QualityPageShell.tsx:100-104` has an `<InputLabel>` child and `label="Window"` on the `<Select>`: two labels on one control.

## Fix

The window selector carries **one** label, and that label is plain text next to the field
(`frontend/src/components/reports/QualityPageShell.tsx`):

```tsx
<Typography id="quality-window-label" component="label" htmlFor="quality-window" …>Window</Typography>
<Select id="quality-window" labelId="quality-window-label" size="small" … />
```

The old markup had an `<InputLabel>` next to a `<Select label="Window">` — two labels on one
control — and the app paints an opaque background on every outlined field
(`MuiOutlinedInput` `backgroundColor: P.inputBg` in `frontend/src/contexts/ThemeContext.tsx`).
MUI positions a floating label partly **inside** the field's box, so that background covers the
lower half of the word: only the top row of pixels was left. The label is now a sibling of the
select, so no field background can reach it, and `labelId` keeps the accessible name (the
combobox is named by the visible label).

## Tests

`tests/frontend/QualityWindowSelector.test.tsx` — 3 cases: the word "Window" appears once, it is
a `<label>` that names the select (`for` + `aria-labelledby`), and it sits outside the field.

Verified against the pre-fix sources via `git stash`: **3 failed**; on the fixed sources
**3 passed**.

## Verification

Measured on the worktree build at 1440 px: the label is one `<label>` element, 46 px wide and
20 px tall, painted next to the select and fully readable (before, the only pixels visible were
the top row of the letters at y 159, the rest covered by the field's own background).

Checked in dark and light, at 1440 px and at 390 px, in EN / FR / DE — the word "Window" is
readable in every combination and the select shows "14 days".
Evidence: [after 1440 dark](../tasks/qa-evidence/fix/bug-0814-after-1440-dark-en.png) ·
[after 1440 light](../tasks/qa-evidence/fix/bug-0814-after-1440-light-en.png).

Deployed as `main-2026.10.22-89636` (integration `int-mvjsys09db00cb`), verified on the live site.
