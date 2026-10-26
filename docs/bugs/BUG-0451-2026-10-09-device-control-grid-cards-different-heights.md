# BUG-0451 — Device Control: grid cards have different heights in the same row

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0451                                                     |
| Reported  | 2026-10-09                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

## Symptom

On `/device-control` (`frontend/src/pages/Rec.tsx`) the **Grid · 24 per page**
view (and the other grid sizes) renders cards in the same row at *different*
heights: the appletv / Honor / Vega / Fire TV tiles no longer line up across
the row, so the operator gets an irregular, hard-to-scan grid. The grid
worked (all cards the same height as the tallest in the row) before the
[BUG-0439](BUG-0439-2026-10-09-device-control-streams-reload-on-view-change.md)
fix landed.

Example from the operator's desktop, **Grid · 24 per page**, three devices
on the same row (`appletv1 · vpt-mf1`, `FireTv · vpt-pi3`, `Honor ·
vpt-mf1`):

- `appletv1` — tall card, ~ 600 px, landscape image bottom-aligned
- `FireTv` — short card, ~ 470 px, all black (stream not yet up)
- `Honor` — tall card, ~ 600 px, portrait phone screenshot filling the box

The visual grid is now a stack of three different-sized tiles, not a row of
matching-height tiles.

## Repro

1. Open `https://virtualpytest.angelstreet.io/device-control` (desktop,
   logged in) — or any build that includes the BUG-0439 fix.
2. Pick **Grid · 24 per page** in the View menu (default).
3. Compare any row of tiles once the streams come up: cards in the same row
   are visibly different heights.
4. Hover a tile to switch from snapshot to live — the same tile re-measures
   to its real aspect ratio, but the row above it stays at the snapshot
   height, so the irregular layout persists.

## Root cause

[BUG-0439](BUG-0439-2026-10-09-device-control-streams-reload-on-view-change.md)
unified the grid and layout tiles under a single `<DeviceLayout>` CSS grid
stage (`frontend/src/components/rec/layout/DeviceLayout.tsx`). For the
`GridView` branch the stage uses
`grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))` and lets each
tile set its own row height through its content.

The HLS player inside the tile is sized by `StreamViewerLayoutConfig` (see
`frontend/src/config/layoutConfig.ts`):

- non-mobile (Apple TV, Fire TV, Vega…) → `minHeight: 300px`,
  `aspectRatio: 16/9`
- mobile (Honor, Android phones, etc.) → `minHeight: 400px`,
  `aspectRatio: 9/16`

For a non-mobile device on a 461 px wide tile, the natural height is
~ 259 px (16:9 of 461) and `minHeight: 300` lifts it to 300 px. For a
mobile device the natural height is ~ 820 px (9:16 of 461) and `minHeight:
400` does not lift it further. The two `minHeight` / `aspectRatio` pairs
produce very different intrinsic heights for the same card width, and
because the grid items no longer share a fixed row height in the unified
stage, each card settles at its own intrinsic height — the snapshot-only
card (no stream up yet) sits at the smaller value, the live mobile sits
much taller, and the live non-mobile sits in between.

The previous MUI Grid branch (`<Grid item xs={12} sm={6} md={4} lg={3}>`)
solved this by accident: the parent flex container defaulted to
`align-items: stretch`, so every tile in a row matched the tallest one
regardless of its content. The BUG-0439 unification kept
`align-items: stretch` (the CSS Grid default) but each card's own
`height: 180` plus the `minHeight` / `aspectRatio` pair inside the HLS
player won over the grid row height, so the cards sized to their own
content instead of the row.

## Fix

Revert [BUG-0439](BUG-0439-2026-10-09-device-control-streams-reload-on-view-change.md).

`frontend/src/pages/Rec.tsx`:

- The `view.kind === 'grid'` branch is back to
  `<Grid container spacing={2}>` with `<Grid item xs={12} sm={6} md={4}
  lg={3}>` per tile.
- The `view.kind === 'layout'` branch still uses `<DeviceLayout view={view}
  onSwap={…} />`, so the layouts (Side by side, Stacked, 3 in a row, Grid
  2×2 / 3×2 / 4×2, Focus + below, Focus + right, One full) keep the
  explicit columns / rows / areas and the drag-to-swap they had.

`frontend/src/components/rec/layout/DeviceLayout.tsx`:

- `view` is back to `LayoutView` (the device-grid branch was the only
  caller using `DeviceView`).
- Empty slots and drag-to-swap are layout-only, the `gridTileMinWidth` prop
  and the `isGridView` helper are gone.

This restores the same-height behaviour for the grid and the existing
behaviour for the layouts. It also re-introduces the BUG-0439 symptom
(streams reload on view change); that bug is now back to **Open** and is
tracked again as the same BUG-0439 — see the "Status" field on its file
once it is re-added to the index.

## Verify

- Open `/device-control` on the build that contains this revert.
- Pick **Grid · 24 per page**. All cards in the same row are now the same
  height (the tallest in the row, as before BUG-0439).
- Switch to **Grid · 12** and **Grid · 48** — same-height rows.
- Switch to **Focus + right** — the big slot + the three thumbnails still
  fill the layout, drag-to-swap still works.
- Switching from any grid size to any layout (or back) re-flashes the
  HLS players — that is the BUG-0439 symptom we are accepting again to
  get the same-height grid back. A follow-up fix for BUG-0439 will
  need to re-unify the React parent *without* breaking the row height.
- `cd frontend && ./node_modules/.bin/tsc --noEmit` clean,
  `npm run lint` clean on the two changed files,
  `node scripts/i18n-check.mjs` clean.
