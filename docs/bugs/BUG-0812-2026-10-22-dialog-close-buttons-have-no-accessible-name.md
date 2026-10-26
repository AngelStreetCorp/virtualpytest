# BUG-0812 — 18 of the 28 dialog close buttons render only an icon and have no accessible name, for example the Run page's Device Info dialog

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0812                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Low                                                       |
| Area      | frontend / accessibility                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding TESTER-12, in `docs/tasks/QA-TESTER-findings.md`); reproduced against the live app.

- **Page / route:** any dialog; measured on the Run page Device Info dialog
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open Test > Run Tests, pick a target and a script.
2. Press Device Info on the Selected Items card.
3. Inspect the X button (or use a screen reader).

**Expected:** The button announces "Close".

**Actual:** `aria-label` is null and there is no text, so a screen reader announces an unlabelled button. Counting `IconButton`s that render a `CloseIcon` across `frontend/src`: 18 of 28 have no `aria-label` (for example `Navigation_NodeDomDialog`, `Navigation_NodeEditDialog`, `LoopConfigDialog`, `ActionConfigDialog`, `VerificationConfigDialog`, `LogTerminalPanel`, `LinkTestcasePickerModal`). `frontend/src/components/run/DeviceInfoModal.tsx:120` is one.

Evidence:

- [tester-14-device-info-dialog.png](../tasks/qa-evidence/tester/tester-14-device-info-dialog.png)

## Root cause

Not diagnosed yet: the QA sweep reported the symptom only.

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.
