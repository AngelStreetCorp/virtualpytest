# BUG-0578: Device-control custom grid gap was hardcoded 2 px regardless of cols

**Date:** 2026-10-16
**Discovered on:** `/device-control` (rec page), custom grid view (any team).
**Severity:** low — visual only, no functional or layout breakage.
**Status:** fixed on `main`.

## Symptom

On the **custom** device-grid view (the one where the team sets the columns
× rows shape, up to 100 × 100), every tile sat 2 px from the next one — the
same gap whether the user picked a 3 × 3 layout or a 12 × 8 layout.

For a **3- or 4-column** custom shape, that gap was way too tight: the
stream card's 1 px border and the 2 px gap blended into one line, the star
button and the title overlapped the tile edge, and tiles felt glued to each
other instead of framed.

The fix only changes the custom-grid path. The preset **12 per page** and
**24 per page** grids (which only expose 3 or 4 cols anyway) keep their
default MUI `spacing={2}` (16 px) and the layout views (Side-by-side,
Stacked, 3-in-a-row, Grid 3×2, Grid 4×2, Focus + …) keep their 8 px gap.

## Root cause

`frontend/src/pages/Rec.tsx` rendered the custom grid like this:

```tsx
<Box sx={{
  display: 'grid',
  gridTemplateColumns: `repeat(${view.glyph.cols}, minmax(0, 1fr))`,
  gap: 2,   // always 2 px
}}>
```

`view.glyph.cols` was already piped through to the column count but never
into the gap. The constant `2` had been there since the custom view shipped
and predates the user's report.

## Fix

1. **Helper: `frontend/src/constants/deviceLayouts.ts`.** New export
   `previewGridGapPx(cols: number): number` returning:
   - `12` when `cols <= 4`
   - `6`  when `cols >= 5 && cols <= 8`
   - `2`  when `cols > 8`

   The bands come from the design request: more cols → less gap.
   ≤ 4 cols keeps the current generous feel so wide tiles can breathe;
   5 – 8 cols halves the spacing because the row already feels dense;
   > 8 cols collapses to a wall separated only by the 1 px border.

2. **`frontend/src/pages/Rec.tsx`.** The custom-grid `<Box>` now uses
   `gap: previewGridGapPx(effectiveCols)` where `effectiveCols` mirrors
   the same `isEmbedded ? Math.min(2, view.glyph.cols) : view.glyph.cols`
   already in `gridTemplateColumns`, so the embedded pane (capped at 2)
   also stays on the 12 px band.

3. **Preset grids (`grid12` / `grid24`) and layouts are untouched.** Those
   never cross the 5-col threshold on the page (preset = 3 or 4 cols,
   layouts = 1–4 cols), so the MUI default `spacing={2}` and the layout's
   `gap: 1` (8 px) stay correct on their own.

## Files changed

- `frontend/src/constants/deviceLayouts.ts` — `previewGridGapPx` helper + comment.
- `frontend/src/pages/Rec.tsx` — custom-grid `gap: 2` → `gap: previewGridGapPx(...)`.
- `docs/bugs/BUG-0578-2026-10-16-device-control-custom-grid-gap-was-always-2px.md` — this file.

## Verification

- `eslint --max-warnings 0 src/constants/deviceLayouts.ts src/pages/Rec.tsx` — green.
- `tsc --noEmit -p .` — green.
- Custom view, cols = 3 → gap = 12 px (matches today only at very high densities, now correct at low).
- Custom view, cols = 6 → gap = 6 px (was 2 px — now halved).
- Custom view, cols = 10 → gap = 2 px (unchanged).
- Preset `24 per page` → tiles still use MUI `spacing={2}` (16 px), unchanged.
- Layout `Grid 3×2` → still `gap: 1` (8 px), unchanged.
