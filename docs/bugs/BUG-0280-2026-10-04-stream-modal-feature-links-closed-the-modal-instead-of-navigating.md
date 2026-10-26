# BUG-0280 — Feature links in the device stream modal header closed the modal instead of opening the page

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0280                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On Device Control, opening a device's stream modal and clicking an optional-feature icon in its
header (e.g. AVQ) closed the modal and left you on the Device Control page. The same icon on the
device preview card navigated to the AVQ page as expected.

## Root cause

`RecStreamModalHeader` called `onClose()` then `navigate(...)`. The modal uses
`useBackToClose`, which pushes a history entry while open and, when the modal unmounts without
having been closed by Back, calls `window.history.back()` to drop that entry. By the time that
cleanup ran, the router had already pushed the AVQ route, so `history.back()` popped the AVQ
navigation and returned to Device Control.

## Fix

- `frontend/src/hooks/useBackToClose.ts` — the cleanup only calls `history.back()` while the
  overlay's own entry is still the current one (`history.state.vptOverlay`), so a close caused
  by navigating elsewhere no longer undoes that navigation.
- `frontend/src/components/rec/RecStreamModalHeader.tsx` — feature links navigate with
  `replace: true`, taking the overlay's history entry, so Back from the feature page returns to
  Device Control in one press.

## Verification

Device Control → open a device's stream modal → click the AVQ icon in the header: the AVQ page
for that device opens. Back returns to Device Control. Closing the modal with its X and then
pressing Back still leaves the page in one press.
