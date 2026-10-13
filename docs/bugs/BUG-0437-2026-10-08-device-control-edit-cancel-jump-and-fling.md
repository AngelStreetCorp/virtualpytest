# BUG-0437 — Device Control: Edit/Cancel jump and grid fling

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0437                                                     |
| Reported  | 2026-10-08                                                   |
| Status    | Open                                                        |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

## Symptom

On `/device-control` (desktop, ≥ md):

1. **Edit ↔ Cancel button jump.** The "Edit" button (normal mode) and the "Cancel"
   button (edit mode) are not anchored at the same x/y. Switching into edit mode,
   the row grows ~8 px taller than the filter row; Cancel (top-aligned, 40 px)
   sits above the visual midline that Edit previously occupied (center-aligned,
   32 px). The button visibly jumps one row when toggled.
2. **Fling past the grid.** When the device grid scrolls vertically on mobile
   (and on trackpad/touch when the OS passes momentum), a flick overscrolls the
   page itself — i.e. scroll chains to the body, and the grid rubber-bands at
   top and bottom. Same prop also stops iOS Safari from carry-on flicking
   beyond the grid's bounds.

## Repro

1. Open `https://virtualpytest.angelstreet.io/device-control` (desktop,
   logged in).
2. Note the y of "Edit" relative to the dropdown headers' mid-line.
3. Click "Edit". Observe the Cancel button now sits one row higher.
4. Click "Cancel", then back to "Edit", to confirm the snap.
5. On mobile, scroll the grid fast → grid passes its end and the whole page
   also flicks, with empty space at the boundary.

## Root cause

`frontend/src/pages/Rec.tsx:728-744` — "Edit" used `Button size="small"`
(no explicit height) and inherited the parent Stack's `alignItems: 'center'`.
"Cancel" had `height: 40` and an `alignItems: 'flex-start'` row, so its
y-anchor differed from Edit's by ~4 px plus the 32 → 40 row-height delta.

`frontend/src/pages/Rec.tsx:987-996` — the scroll container had
`WebkitOverflowScrolling: 'touch'` on mobile but no
`overscroll-behavior`, so the panel inherits the page scroll, no chaining
boundary.

## Fix

`frontend/src/pages/Rec.tsx`:

- Edit button now matches Cancel: `height: 40` and `alignSelf: 'flex-start'`.
  Both buttons occupy the same x/y in normal mode and edit mode.
- Device-grid scroll box adds `overscrollBehavior: 'contain'` on mobile,
  so a flick stays inside the grid and the grid doesn't rubber-band past
  its own top/bottom.

## Verify

- Toggle Edit → Cancel → Edit; the button never moves more than 0 px.
- Mobile scroll: scroll the grid to its bottom — the page does not flick.
- `vite build` clean. `tsc --noEmit` clean.
