# BUG-0440 — Group tile UX batch 2: tooltips, 1-line focused header, drop `Focus + right`, fixed-height hint, unfocus restores layout

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0440                                                     |
| Reported  | 2026-10-09                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | Unreleased                                                   |
| Commit    | `f1ea6720f` (merge: `f69fbb685`)                             |

## Symptom

Six small Group-tile UX fixes, all reported together on the deployed
`/device-control` after TASK-76 landed:

1. **No tooltips on `Group control` and `Edit`.** Their short labels do not
   explain what they do, so the user has to click to find out.
2. **`View [grid] Focus + right` shows in the page-level View menu.** The
   focus layouts are useful inside the group tile but not as a page-level
   choice; the option should not be there.
3. **`Included` reads `Included`.** The same chip on every other place in
   the app reads `Selected`; the group tile was inconsistent.
4. **Focused cell's bottom info row is 2 lines** when the device has an
   error/ack chip — the badge pushes the row to two lines and the row
   stops being a clean 1-line strip. The user wants one line:
   `stb4 · vpt-pi3 · [Selected] · [Unfocus]`.
5. **`Sends to N devices: stb4, stb4`** header line in the remote-side bar
   is redundant (the group grid already shows which members are in the
   group).
6. **Per-event `press_key → 1/2 · 18435 ms` debug log** at the bottom of
   the remote-side bar is debug output bleeding into the UI.
7. **GroupSelectBar hint text** wraps and pushes the bar taller every time
   a key press arrives mid-edit, causing the row to reflow.
8. **Unfocusing** closes the focused stream's modal but does not return
   the layout to the one the user had selected before — it stays in the
   focus layout.

## Repro

1. Open `https://virtualpytest.angelstreet.io/device-control` (desktop, signed in).
2. Hover `Group control` and `Edit` — no tooltip appears.
3. Click `Group control`, pick two devices, click `Control 2 together` →
   the group modal opens. The View menu in the page header (visible in
   the strip behind the modal) shows `Focus + right` and `Focus + below`.
4. Click a stream — the focused cell's bottom row shows:
   `stb4 vpt-pi3 [Error chip] [Included] [Focus]`, two lines.
5. The right pane of the modal shows the `Sends to 2 devices: stb4, stb4`
   line, and below the remote a `12:31:38 press_key → 1/2 · 18435 ms`
   log line.
6. The sticky `GroupSelectBar` at the bottom of the page wraps its hint
   text and the bar grows taller on every key press.
7. Click `Unfocus` — the modal closes, but the layout stays in
   `Focus + right` instead of returning to the grid the user had.

## Root cause

- `frontend/src/pages/Rec.tsx` — Group control and Edit buttons had no
  `Tooltip` wrapper.
- `frontend/src/components/rec/layout/ViewMenu.tsx` — rendered every entry
  in `LAYOUT_VIEWS`; nothing filtered out the focus layouts.
- `frontend/src/components/rec/group/GroupStreamCell.tsx` — label
  hard-coded to `t('Included')`; the row had `flexWrap: 'wrap'` and the
  `GroupAckChip` was always rendered.
- `frontend/src/components/rec/group/GroupRemoteSide.tsx` — header line
  `Sends to {count} device(s)` and the per-event log were always
  rendered.
- `frontend/src/components/rec/group/GroupSelectBar.tsx` — hint was a
  free `Typography` with no height cap.
- `frontend/src/components/rec/group/GroupStreamGrid.tsx` — on
  `onToggleFocus`, the layout was set to `focusRight` but never reset on
  unfocus.

## Fix

`frontend/src/pages/Rec.tsx` — wrap `Group control` in
`<Tooltip title={t('Take control of several devices together')}>` and
`Edit` in `<Tooltip title={t('Edit tag')}>`. `t` is now imported.

`frontend/src/components/rec/layout/ViewMenu.tsx` — filter the
`LAYOUT_VIEWS` map to `!v.focus`, so the focus layouts disappear from
the menu. They are still used internally by the group tile's
`fitLayout` / `layoutForCount` helpers.

`frontend/src/components/rec/group/GroupStreamCell.tsx`:
- `label={t('Selected')}` instead of `t('Included')`.
- `flexWrap: 'nowrap'` on the bottom row (was `'wrap'`).
- `<GroupAckChip … />` only renders when `!isFocused`, so a focused cell
  has a clean 1-line strip and the chip is still visible on the
  un-focused members.

`frontend/src/components/rec/group/GroupRemoteSide.tsx`:
- Drop the `Sends to {count} device(s)` header line.
- Drop the per-event `press_key → n/m · ms` log block.
- The component no longer needs `targets` or `log`; both are kept on
  the type as optional for caller compatibility.

`frontend/src/components/rec/group/GroupSelectBar.tsx` — hint `Typography`
gets `height: 40, maxHeight: 40, overflow: 'auto', display: 'flex',
alignItems: 'center', lineHeight: 1.4`. A longer translation scrolls
inside the same 40-px box; the bar height never changes.

`frontend/src/components/rec/group/GroupStreamGrid.tsx`:
- Track the last non-focus `viewId` in a `useRef`.
- On `focusKey → null`, switch `viewId` back to the ref's value.
- The user can still pick a focus layout manually from the View menu
  (now hidden in the page-level menu but still exposed inside the group
  tile if the caller passes `layoutsOnly={false}`).

## Verify

- `tsc --noEmit` clean, `vite build` clean (`✓ built in 38.22s`).
- Group tile: hover `Group control` → "Take control of several devices
  together"; hover `Edit` → "Edit tag".
- Page View menu no longer lists `Focus + right` or `Focus + below`.
- Group tile: every cell's `Included` chip now reads `Selected`.
- Focused cell bottom row is one line; no error/ack chip on the focused
  cell.
- The right pane of the modal has no `Sends to N devices` line and no
  per-event log.
- GroupSelectBar height is fixed at 40 px; the hint scrolls if it would
  overflow.
- Focus → Unfocus returns the grid to the user's last non-focus layout
  (the auto-fit default if they never picked one).

## Why this is now a UI/UX rule

The same row-height / one-line / fixed-size rules from
`docs/agent/platform/UI_STYLE.md` §5 and §9.6 (Mode-toggle buttons) also
cover the GroupSelectBar and the focused cell. BUG-0438 was the first
mode-toggle case; BUG-0440 is the second (focus / unfocus + selected
chip + view menu); the §5 / §9.6 entry already says the next page header
should not repeat it.
