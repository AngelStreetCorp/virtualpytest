# BUG-0366 — Top-bar items shifted sideways on every navigation

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0366                                                     |
| Reported  | 2026-10-05 (user screenshot)                                 |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low — visual flash, uneven spacing                           |
| Area      | `frontend/src/components/common/Navigation_*.tsx`            |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

Clicking a top-bar item made the other items jump horizontally (a flashing effect). Spacing between items was uneven — wide empty space around **AI**. In light mode the active item's pink label was hard to read on the blue bar.

Switching language resized the dropdown menus (another flash).

## Root cause

- The active item switched `fontWeight` 400 → 600; the bolder label is wider and, under `justify-content: space-between`, every other item moved.
- The active colour was the theme's `secondary` — `#dc004e` on the light bar's `#1976d2` is ~1.3:1 contrast.
- Each item had a fixed `minWidth: 108` with its label centred, so short labels ("AI" + arrow ≈ 45px) carried ~30px of dead space per side on top of the space-between gap, while long ones ("Monitoring") had none.

## Fix

One shared `navItemSx(active)` in `Navigation_ItemStyle.ts`, used by the bar, the dropdown and the grouped dropdown: constant weight, no fixed width, equal padding. The active item is marked by a translucent pill plus a 2px underline (inset box-shadow, no layout impact); marked in the app's gold accent: dark mode gold label + gold underline (6.7:1); light mode white label + bright gold underline (no gold reaches text contrast on the blue bar).

Dropdown menus (`Navigation_Dropdown`) have a fixed 240px width, sized to the widest locale (DE "Dokumentation" ~232px, FR "IA" ~228px).

## Verification

- `tsc --noEmit` passes.
- Local dev server at 1600px: item x-positions identical on `/`, `/device-control` and back; gaps between items all 28–29px; active item checked in light and dark.
