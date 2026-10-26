# BUG-0799 — The first keyboard tab stop of the app, the scope picker, shows no visible focus indicator

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0799                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                       |
| Severity  | Medium                                                       |
| Area      | frontend / accessibility                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding DEVELOPER-08, in `docs/tasks/QA-DEVELOPER-findings.md`); reproduced against the live app.

- **Page / route:** every page (top bar scope picker)
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open any page and press Tab once.
2. Look at the control that receives focus.

**Expected:** A visible focus indicator (WCAG 2.4.7).

**Actual:** Focus lands on the scope picker (`Mui-focusVisible`) with `outline: 0px none` and no box-shadow, so nothing changes. The next stop, the Dashboard link, shows a gold underline, so the bar is inconsistent.

Evidence:

- [developer-08-scope-picker-no-focus.png](../tasks/qa-evidence/developer/developer-08-scope-picker-no-focus.png)

## Root cause

`frontend/src/components/common/ScopePicker.tsx` — the chip is a MUI `ButtonBase`, and the button
base resets the outline (`outline: 0px none`). The chip's own `sx` had no `:focus-visible` rule, so
the first Tab of the app moved the focus to the scope picker without anything changing on the
screen. The next stop (the Dashboard link) shows a gold underline, so the bar was inconsistent.

## Fix

`frontend/src/components/common/ScopePicker.tsx`:

- The chip draws a 2 px outline in the accent colour when it is focused by the keyboard
  (`&:focus-visible`), the pattern the rest of the app uses.
- The rows of the open picker (Server, Workspace, Project) get the same, with an inset outline so it
  does not collide with the popover edge.

## Verification

- `tests/frontend/allServer/ScopePicker.test.tsx`: the chip and the rows of the open picker carry a
  `:focus-visible` rule. Without the fix both tests fail.

In the browser: pressing Tab on any page puts a gold outline around the scope picker, and Tab
inside the open picker outlines the focused row
(screenshot: `../tasks/qa-evidence/fix/bug-0799-scope-picker-focus.png`).
