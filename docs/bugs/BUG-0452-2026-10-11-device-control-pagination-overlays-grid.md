# BUG-0452 — Device Control: pagination overlays the preview grid

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0452                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

## Symptom

On `https://virtualpytest.angelstreet.io/device-control` the page footer
Pagination row (`« ‹ 1 2 3 › »`) is misaligned and overlays the bottom row of
preview tiles in the Grid view (any of **Grid · 12 / 24 / 48 per page**). The
preview cards behind the pager are partially hidden; the user can no longer
click the bottom-left tile without aiming around the pager buttons.

## Repro

1. Open `https://virtualpytest.angelstreet.io/device-control` (desktop, signed in).
2. Pick any Grid size in the View menu (default = **24 per page**).
3. Filter or pick a fleet that needs more than one page — the user reported it
   with the default fleet (3 pages), but any fleet whose filtered cards span
   two or more rows is enough.
4. Scroll to the bottom of the device grid: the pager sits on top of the
   last row of cards. The overlap is visible regardless of which page is
   active (1, 2 or 3).

## Root cause

[BUG-XXXX (commit `640907df0`)](BUG-XXXX-rec-player-bug.md) locked every
`<Grid item>` on the per-page Grid views to `aspect-ratio: 16 / 9` so a
9:16 phone stream no longer stretches its row. The fix only changed the
Grid item; the inner `<Card>` inside `RecHostPreview` still has a fixed
`sx={{ height: 180 }}` of its own.

On viewports where the aspectRatio-computed Grid item height drops below
180 px (any container width where `itemWidth × 9 / 16 < 180` — roughly
1200–1280 px at `lg` (25 %), 900–960 px at `md` (33 %) and 600–770 px at
`sm` (50 %)), the 180 px Card overflows its Grid item. The Grid container
itself stays sized to the aspectRatio rows, so the overflow bleeds past
the container's bottom edge. The Pagination row (positioned 16 px below
the container with `mt: 2`) lands directly on top of that overflow.

The Layout views (`Side by side`, `Grid 2×2`, `Focus + below` …) go through
`<DeviceLayout>` instead, which already overrides the Card to `height: 100%`
via `& > .MuiCard-root, & > * > .MuiCard-root` and were never affected.
Same fix shape is used in `<GroupStreamCell>` for the group-control tile.

## Fix

Force the preview Card inside every per-page Grid item to fill its Grid
item, matching the override `<DeviceLayout>` already applies to its slots.
`frontend/src/pages/Rec.tsx`:

```tsx
<Grid
  item
  xs={12}
  sm={6}
  md={4}
  lg={3}
  key={deviceKey}
  sx={{
    aspectRatio: '16 / 9',
    // BUG-0452: Card inside RecHostPreview keeps a fixed height: 180.
    // When aspectRatio above computes < 180 (any container between the
    // breakpoints where 16/9 × itemWidth drops under 180 px) the Card
    // overflows the Grid item and bleeds past the Grid container into the
    // Pagination row below. Mirror the override DeviceLayout already
    // uses on its grid slots so the 16/9 ratio always wins.
    '& > .MuiCard-root, & > * > .MuiCard-root': { height: '100%' },
  }}
>
```

The Card's `flexDirection: 'column'` body still lays out the header (32 px)
on top and stretches the preview to the remaining space (`flex: 1,
minHeight: 0` on the preview Box), so the tiles keep the same content
arrangement they had before — they only stop overflowing their slot.

## Verification

1. `cd frontend && ./node_modules/.bin/tsc --noEmit` — clean.
2. `cd frontend && ./node_modules/.bin/eslint src/pages/Rec.tsx` — clean.
3. Open `/device-control` in a desktop browser:
   - At **1312 × …** viewport (the user's screenshot width), confirm the
     Pagination row sits cleanly below the last row of tiles with the
     normal `mt: 2` gap. No tile bleeds into the pager.
   - Resize the window between 1100 px (md, 33 %) and 1240 px (lg, 25 %)
     and back: tiles keep the same 16/9 shape across breakpoints, the
     pager never overlaps the grid.
4. Smoke-test a Layout view (e.g. **Grid 3×2**): unchanged. The fix only
   touches the Grid branch; Layout views already had the override.
5. Smoke-test Edit mode and Group mode on a Grid view: card selection and
   the reserved mode line above the grid still behave as before.