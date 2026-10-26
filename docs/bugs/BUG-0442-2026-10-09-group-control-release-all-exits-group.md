# BUG-0442 — Group control: Release all (and Esc) should also exit the group

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0442                                                     |
| Reported  | 2026-10-09                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | `1042392e4` (merge: `42636c052`)                             |

## Symptom

Clicking **Release all** in the group modal (TASK-76) closed the modal and
released the devices, but the page stayed in **Group control** mode with the
previous selection still highlighted. Re-opening the group bar on the same
model showed the same devices still picked, even though the user expected a
clean "Pick a device" state. Pressing **Esc** / the browser back button had
the same problem — the modal closed, the group bar stayed, the selection
stayed.

## Repro

1. Open `https://virtualpytest.angelstreet.io/device-control` (desktop, signed in).
2. Click `Group control`, pick 2+ same-model devices with a shared profile,
   click `Control N devices` — the group modal opens.
3. Click **Release all** (top-right of the modal header).
4. The modal closes and the page returns to the device grid… but the
   `Group control` button still says **Exit group** (group mode is still on),
   and the page-level `GroupSelectBar` is back at the bottom with the same
   `model: …` / `controller: …` and the previous selection.
5. Same with **Esc** while the modal is open.

## Root cause

`frontend/src/components/rec/group/GroupControlModal.tsx` — the modal's
`handleRelease` only did `await release(); onClose();`. It never told the
parent to leave group mode or to drop the in-progress selection, so the
parent's `useGroupSelection` state (`isGroupMode`, `selected`,
`remoteProfile`) was untouched.

`useBackToClose(true, handleRelease)` wired Esc / browser back to the same
`handleRelease`, so the gesture had the same gap.

## Fix

`frontend/src/components/rec/group/GroupControlModal.tsx` — added a required
`onExitGroup: () => void` prop. `handleRelease` now calls it after
`onClose()`. The docstring on the prop spells out the contract: the parent
should land back on the normal Edit / Group control + filters row, with the
in-progress selection cleared.

`frontend/src/pages/Rec.tsx` — passes `onExitGroup={groupSelection.toggleGroupMode}`
to the modal. `toggleGroupMode` already clears `selected` and `remoteProfile`
when it toggles off, so a single call covers both the "leave group mode" and
the "drop the previous pick" expectations.

Both `Release all` and the Esc / back-to-close gesture go through the same
`handleRelease`, so they both exit cleanly.

## Verify

- `tsc --noEmit` clean, `node scripts/i18n-check.mjs --quiet` clean
  (313 keys, 0 errors), `vite build` clean (`✓ built in 32.38s`).
- Open `/device-control`, click `Group control`, pick 2 devices, click
  `Control 2 devices` — modal opens.
- Click **Release all** — modal closes, page returns to the normal
  Edit / Group control + filters row, `Group control` button flips back
  to plain text (group mode off), no selection is highlighted, the
  `GroupSelectBar` is gone.
- Same with **Esc** while the modal is open.
- Re-opening `Group control` afterwards starts from a clean
  "Pick a device" state.

## Why this is now a UX rule

`Group control` is a **mode toggle** in the page header (see
`docs/agent/platform/UI_STYLE.md` §5 and §9.6 for the same x/y rule
BUG-0438 codified). Every path that *leaves* the group modal — the
explicit `Release all` button, the `useBackToClose` gesture, the
backdrop click — should also leave group mode on the page; a half-exit
(open modal closed, group mode still on with the previous pick) is
the same class of bug as a half-mode (Edit label flipped without
sizing for the new label) and should be impossible to ship. The fix
on `handleRelease` covers the two paths we ship today; any new
close path added later should reuse it.
