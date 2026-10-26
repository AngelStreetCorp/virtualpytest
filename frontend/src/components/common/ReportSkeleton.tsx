/**
 * Data-loading skeletons for the report pages (`/test-results/*`).
 *
 * Why this exists: the report pages used to greet the user with `N/A%` / `N/A` in the stat
 * tiles and a lone `<CircularProgress>` floating in an otherwise empty page. Two problems:
 * a value that is not known yet is not a value that is wrong, so `N/A` read as a failure
 * (it was coloured `P.error`, because `Number('N/A')` is `NaN` and fell through every rate
 * threshold); and a centred spinner in a big empty area gives the eye nothing to land on, so
 * the page visibly "popped" when the data landed ~1.5 s later.
 *
 * The rule this implements is UI_STYLE §10 S6 and contract #29 — a loading state is the SIZE
 * of the content it replaces, and it is gated on the `loading` boolean, never on "the data is
 * empty".
 *
 * Both pages share this module so `/test-results/reports` and `/test-results/cicd-reports`
 * pulse identically instead of drifting apart behind two hand-rolled loaders.
 */
import React from 'react';
import { Box, Skeleton, TableCell, TableRow } from '@mui/material';
import type { SxProps, Theme } from '@mui/material/styles';

/** Height of a table-row placeholder bar, in px. */
export const BAR_HEIGHT = 16;

/**
 * Vertical cell padding that fits a `BAR_HEIGHT` bar inside a `rowHeight` row, leaving the
 * row's own 1 px bottom border the remainder.
 *
 * Returns an explicit `Npx` STRING on purpose. MUI's `sx` runs bare numbers in padding
 * through the theme's `spacing` (8 by default), so `py: 6.5` became 52 px and every skeleton
 * row on `/test-results/cicd-reports` rendered 125 px tall instead of 42 — measured, not
 * guessed. The unit suffix skips that transform. Never inline this arithmetic into `sx`.
 */
export const rowPaddingY = (rowHeight: number): string =>
  `${Math.max(0, Math.floor((rowHeight - BAR_HEIGHT - 1) / 2))}px`;

/**
 * One grey bar standing in for a stat value. Default width matches a 2–3 digit figure with
 * its unit ("82", "57%", "17.1s"), which is what these tiles usually carry.
 *
 * `height` should match the live value's line box, so swapping bar for number moves nothing.
 */
export const ValueSkeleton: React.FC<{
  width?: number | string;
  height?: number;
  sx?: SxProps<Theme>;
}> = ({ width = 56, height = 26, sx }) => (
  <Skeleton variant="text" width={width} height={height} animation="wave" sx={sx} />
);

/**
 * A whole stat tile as grey bars — label, value, sub — at the line heights the live
 * `caption` / value / `caption` render at. Its box is `p: 2 / flex: 1 / minWidth: 100`, the
 * shape `KpiCard` uses in the CI/CD feature, so the tile row does not resize when the real
 * numbers land.
 *
 * Where a page already owns its tile chrome (Test Reports keeps its own labels), stub just the
 * value with `ValueSkeleton` and leave the real label in place.
 */
export const StatTileSkeleton: React.FC<{ sx?: SxProps<Theme>; sub?: boolean }> = ({ sx, sub = true }) => (
  <Box
    aria-hidden="true"
    sx={{
      p: 2,
      flex: 1,
      minWidth: 100,
      display: 'flex',
      flexDirection: 'column',
      gap: 0.25,
      ...(sx as object),
    }}
  >
    {/* 16 / 19 / 16 px: the measured line boxes of the live `caption` / `h5` / `caption`
        card this stands in for (tile 88 px with `p: 2` and a 2 px row gap). Anything taller
        makes the row jump when the real card lands. */}
    <Skeleton variant="text" width={64} height={16} animation="wave" />
    <Skeleton variant="text" width={48} height={19} animation="wave" />
    {sub && <Skeleton variant="text" width={76} height={16} animation="wave" />}
  </Box>
);

/**
 * Placeholder rows for a table body. `widths` is one entry per visible column: a percentage
 * string, a pixel number, or `null` for a cell that is an icon or another block (status dot,
 * action button) rather than text.
 *
 * Render inside a `<TableBody>`; it emits `<TableRow>`s and nothing else. The real header row
 * above it is static text, so it stays mounted during loading and the columns never shift.
 */
export const TableRowsSkeleton: React.FC<{
  rows?: number;
  widths: Array<number | string | null>;
  /** Row height in px; defaults to the report tables' comfortable row. */
  rowHeight?: number;
}> = ({ rows = 8, widths, rowHeight = 34 }) => {
  const paddingY = rowPaddingY(rowHeight);

  return (
    <>
      {Array.from({ length: rows }).map((_, r) => (
        <TableRow
          key={r}
          aria-hidden="true"
          // The row height is pinned rather than derived: a `<tr>` also grows to its tallest
          // cell, so a single block taller than `rowHeight - 2 * paddingY` would silently
          // push it past the live row. `height` is a `Npx` string for the same sx reason as
          // `rowPaddingY` — a bare number would be multiplied by the theme's spacing.
          sx={{
            height: `${rowHeight}px`,
            '&:hover': { backgroundColor: 'transparent !important' },
          }}
        >
          {widths.map((w, c) => (
            <TableCell key={c} sx={{ paddingTop: paddingY, paddingBottom: paddingY }}>
              {w === null ? (
                // An icon-sized block, matching the real control it stands in for.
                <Skeleton variant="rounded" width={52} height={BAR_HEIGHT} animation="wave" />
              ) : (
                <Skeleton
                  variant="rounded"
                  height={BAR_HEIGHT}
                  animation="wave"
                  // Vary the width per row and column so the block reads as pending content
                  // rather than as a striped table painted on the page.
                  sx={{ width: w ?? `${70 - ((r * 13 + c * 7) % 45)}%` }}
                />
              )}
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
};

export default ValueSkeleton;