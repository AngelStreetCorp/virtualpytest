# BUG-0445 — Device Control: move the mode bar from below the grid to a reserved line in the header

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0445                                                     |
| Reported  | 2026-10-10                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | `5a63a4f51` (merge: `243076349`)                             |

## Symptom

After BUG-0444, the Edit tag-input bar and the `GroupSelectBar` share
a single 56-px-tall sticky slot at the bottom of the page. The slot is
"always reserved" so the device grid never shifts, but the bar
physically sits *below* the device list and reads as a footer that
interrupts the grid. On a small page the bar is the first thing the
user sees after the header — visually out of place, and it stays put
when the user scrolls.

## Repro

1. Open `https://virtualpytest.angelstreet.io/device-control` (desktop, signed in).
2. Click `Group control`, pick 3 same-model devices → the
   `GroupSelectBar` appears at the bottom of the page. From any
   scroll position, the bar is the last line in the page — under
   the device grid, not next to the header.
3. Click the bar's `Group control` icon to exit → the slot stays
   reserved (56 px of empty space) but the bar is gone. The device
   grid is at the same y as before, but the empty footer area
   still feels like it belongs to the device list, not the header.

## Root cause

`frontend/src/pages/Rec.tsx` — the bottom slot was a `Box` with
`position: sticky; bottom: 8; zIndex: 2; mt: 2; minHeight: 56` rendered
at the bottom of the page (after the device grid and the layout
summary block). The sticky positioning is the right idea — the bar
should never overlap the grid — but the *location* is wrong: the bar
should be part of the header chrome, not a footer.

## Fix

`frontend/src/pages/Rec.tsx`:

- The reserved line moves from the bottom of the page to right
  between the page header (`<Box>` that wraps the title, icon
  buttons, filters, and View menu) and the device grid. Same
  56-px `minHeight`, same `mt: 2`, no `position: sticky`, no
  `zIndex`. The line is always rendered — empty in idle, filled
  with the Edit bar in Edit mode or the `GroupSelectBar` in
  Group mode.
- The Edit and Group mutual exclusion from BUG-0444 is unchanged;
  only one bar can be visible at a time.
- The icon-button toggles in the header work exactly the same way
  (click the pencil to enter Edit, click the grid to enter Group,
  click the active icon again to exit and clear the slot).
- The "old bottom slot" code is removed entirely (the `position:
  sticky, bottom: 8` `<Box>` and the 200+ lines of Edit-bar /
  `GroupSelectBar` content that lived there). The same content now
  lives in the new line above the grid.

## Verify

- `tsc --noEmit` clean, `node scripts/i18n-check.mjs --quiet`
  shows only the two pre-existing `ModsPage` errors (unrelated),
  `vite build` clean (`✓ built in 41.60s`).
- Local preview on `https://127.0.0.1:5077/device-control` shows
  the new layout: topbar → page header (Device + icon buttons +
  filters + View) → reserved 56-px line (empty in idle) → device
  grid. The line is in the header chrome, above the grid, not
  below it.
- Click the grid icon → the `GroupSelectBar` fills the line above
  the device grid. Click again → the line goes empty. The device
  grid does not move in either case.
- Click the pencil icon → the Edit bar (tag input + chips + Save)
  fills the line. Click again → empty.

## Why this is now a UX rule

`UI_STYLE.md` §5 "Mode-toggle bar (Edit workflow, Group bar,
future mode bars)" already required a reserved slot. BUG-0445
clarifies the *position*: the slot lives in the header area,
between the page header and the device grid, not at the bottom
of the page. The bottom of the page belongs to the device grid
(and the layout summary); a bar below the grid reads as a footer
even when the user has just scrolled past it. The updated row in
`UI_STYLE.md` will spell this out explicitly.
