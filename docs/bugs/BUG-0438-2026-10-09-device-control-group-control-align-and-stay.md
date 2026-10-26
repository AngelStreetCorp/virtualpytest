# BUG-0438 — Device Control: Group control left of Edit; both buttons stay at fixed x/y

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0438                                                     |
| Reported  | 2026-10-09                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | `530a31cd7` (merge: `9f49d906b`)                             |

## Symptom

On `/device-control` (desktop), the TASK-76 "Group control" feature added a second
header button next to the existing "Edit" button. Two new problems:

1. **Wrong order.** "Edit" rendered before "Group control" in the JSX, so the visual
   row was `[Edit] [Group control] [Filters] …`. The desired layout is
   `[Group control] [Edit] [Filters] …` — Group control sits to the immediate left of
   Edit (the original "Edit" position was always leftmost).
2. **Buttons move when toggled.** Clicking **Edit** hid both buttons (`!isEditMode`
   guards on Edit and Group control) and replaced the row with the bulk-action block
   (Cancel + tag input + Add + Save). Clicking **Group control** hid Edit
   (`!isGroupMode` guard on Edit) and the row width changed because the Group control
   label grew from "Group control" to "Exit group" + a gold outline. The eye had to
   re-track the row on every click.

## Repro

1. Open `https://virtualpytest.angelstreet.io/device-control` (desktop, signed in).
2. The header shows `[Edit] [Group control] [All Targets] …` — note the order, then
   measure the y of "Edit".
3. Click "Group control". "Edit" disappears, "Group control" gets a border and
   becomes "Exit group". The row width changes.
4. Click "Group control" again. "Edit" comes back, the border goes away.
5. Click "Edit". Both buttons disappear, the row is replaced by the tag input.

## Root cause

`frontend/src/pages/Rec.tsx:765-803` (and the prior fix at 728-744 from BUG-0437) —
the two header buttons had mode-dependent guards:

- Edit: `{!isMobile && !isEditMode && !groupSelection.isGroupMode && …}` — hidden
  whenever edit OR group mode is on.
- Group control: `{!isMobile && !isEditMode && …}` — hidden in edit mode.
- The "Cancel" button inside the edit-mode bulk-action block then occupied Edit's
  slot but was a separate `<Button>` rendered inside a sibling `<Box>`, so its y
  matched by virtue of `height: 40` but its x was a few px to the right of Edit
  (because of the Box's `gap: 1`).

## Fix

`frontend/src/pages/Rec.tsx:760-808`:

- Swap the JSX order: Group control renders first, Edit second. Result: the visual
  order is `[Group control] [Edit]`, with Group control to the left of Edit.
- Remove `!isEditMode` / `!groupSelection.isGroupMode` guards from both buttons.
  Both are now always rendered on desktop, in the same row, at the same x and y,
  regardless of which mode is active.
- Edit's label flips between `"Edit"` and `"Cancel"` based on `isEditMode`
  (`{isEditMode ? 'Cancel' : 'Edit'}`), with the same `onClick={handleEditModeToggle}`.
  The Cancel label uses the same slot, so its x and y match Edit exactly.
- Group control's label already flipped between `"Group control"` and
  `"Exit group"`, and the variant already flipped between `text` and `outlined` —
  those changes are now visible in place, not by swapping the button out.
- Remove the redundant standalone `<Button>Cancel</Button>` at the start of the
  edit-mode bulk-action block (`Rec.tsx:835-857` before the fix). Cancel now lives
  on the Edit button above; the bulk-action block only contains the tag field,
  the inline Add button, the Save button, and the chips/select-all row.

## Verify

- Toggle Edit → Cancel → Edit. The slot never moves. Group control does not move
  either (it sits one button to the left, same y).
- Toggle Group control → Exit group → Group control. The button gets a border and
  the label grows; the row does not reflow. Edit stays in place.
- Type-check: `cd frontend && ./node_modules/.bin/tsc --noEmit` — clean.

## Why this is now a UI/UX rule

`docs/agent/platform/UI_STYLE.md` §5 (Mode-toggle buttons in a header) and
`docs/agent/platform/UI_STYLE.md` §9.6 (Mode-toggle buttons don't move) document
this for every page. BUG-0437 was the first instance; BUG-0438 was the second;
the doc prevents a third.
