# BUG-0444 — Device Control: icon toggles + reserved bottom slot

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0444                                                     |
| Reported  | 2026-10-09                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | `4cdaeed5f` (merge: `fc50f81a3`)                             |

## Symptom

After BUG-0438 + 0440 + 0443, the two header buttons (`Group control`
and `Edit`) on `/device-control` are the same plain gold text and sit at
the same x/y, but they still read as "the same kind of control as the
filter dropdowns next to them" — a first-time user has to read them to
know they're mode toggles. Worse, the Edit workflow expands the top
header in place, pushing the device grid down ~50 px on entry. Group
mode has the same problem from the bottom — its `GroupSelectBar` appears
from nothing and the grid jumps up.

## Repro

1. Open `https://virtualpytest.angelstreet.io/device-control` (desktop, signed in).
2. Hover `Group control` and `Edit` — the labels are short, the
   tooltips say "Take control of several devices together" / "Edit tag"
   (BUG-0440), but the buttons themselves are visually identical to
   the dropdowns next to them. A new user has to click to find out.
3. Click `Edit` — the top header expands, the filter dropdowns vanish
   (replaced by the tag input), and the device grid shifts down by
   ~50 px. Click `Cancel` (now back to "Edit") — the filters return,
   the grid shifts up.
4. Click `Group control` — the `GroupSelectBar` appears at the bottom
   and the grid shifts up. Click `Exit group` — the bar disappears and
   the grid shifts down.

## Root cause

`frontend/src/pages/Rec.tsx` — the two `Button` components in the
header rendered plain gold text, but at 116 + 80 px wide they were
just two text buttons among the dropdowns. The Edit workflow lived
inline in the top header (it conditionally replaced the
`<DeviceFilterBar />`), and the GroupSelectBar was rendered
separately at the bottom of the page with no reserved space.

## Fix

`frontend/src/pages/Rec.tsx`:

- The two `Button` components become two `IconButton` (40×40) using
  `DashboardIcon` and `EditIcon` from `@mui/icons-material`. The label
  never changes (no `Group control` ⇄ `Exit group` flip, no `Edit`
  ⇄ `Cancel` flip). Width is always 40 px; tooltips carry the full
  meaning (`Take control of several devices together` /
  `Exit group` / `Edit tag` / `Exit Edit mode`). The active state is
  a soft gold tint (`P.accent` at ~15 % alpha) — no border, no pulse,
  no hover ripple on top.

- The Edit workflow (tag input + chips/count row + Save button) is
  moved from the top header to a new reserved bottom slot. The
  `GroupSelectBar` (which was already at the bottom) is moved into
  the same slot. The slot is a `Box` with `position: sticky,
  bottom: 8, mt: 2, minHeight: 56` — always at least 56 px tall, so
  the device grid never shifts when a mode is toggled.

- Edit and Group are now mutually exclusive. New
  `handleGroupModeToggle` exits Edit mode when the user enters Group
  mode; `handleEditModeToggle` exits Group mode when the user enters
  Edit mode. Both clear the selection of the mode being exited (the
  edit-selection map and the group-selection map are separate). The
  two modes used to be orthogonal, which let the page show both bars
  at once; the new bottom slot can only hold one.

- The `<DeviceFilterBar />` and `viewMenu` are no longer hidden in
  Edit mode — they always show in the top header, so the user can
  filter while editing instead of losing the filter picks when the
  tag input expands.

`frontend/src/i18n/locales/fr.json` / `de.json` — added `Exit group`
and `Exit Edit mode` to match the new tooltips.

## Verify

- `tsc --noEmit` clean, `node scripts/i18n-check.mjs --quiet`
  shows 2 errors (both pre-existing in `features/mods/.../ModsPage.tsx`,
  unrelated to this change), `vite build` clean (`✓ built in 34.42s`).
- Local preview on `https://127.0.0.1:5076/device-control` shows the
  two icon buttons between the title and the filters; both are 40×40,
  both have hover tooltips, neither has a border. The empty bottom
  area below the device grid is a 56-px reserved slot.
- Click the pencil icon → bottom slot fills with the tag input +
  chips + Save; the top filters stay in place; the device grid does
  not move. Click the pencil again → bottom slot goes empty; grid
  stays.
- Click the dashboard icon (from idle) → bottom slot fills with the
  `GroupSelectBar`; the top filters stay; grid does not move. Click
  it again → bottom slot goes empty; grid stays.
- Click the pencil while the dashboard icon is active → Edit opens,
  Group closes. Click the dashboard while the pencil is active →
  Group opens, Edit closes.

## Why this is now a UX rule

BUG-0438 + BUG-0443 set the rule that the two header buttons must
never change width or variant on toggle, and must always sit at the
same x/y. BUG-0444 closes the last loophole: the buttons themselves
can still look like the dropdowns. Iconic 40×40 buttons with tooltips
are the only visual that reads as a mode toggle at a glance, and the
reserved bottom slot is the only way to keep the grid still when a
mode bar appears or disappears. `UI_STYLE.md` §5 / §9.6 already has
the row; this bug extends it to "any new mode bar (Edit, Group, or
future) lives in the same bottom slot, and the slot is always
reserved" — to be added to the ship-checklist as item 6b.
