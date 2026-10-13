import { Box, Typography } from '@mui/material';
import React from 'react';

/**
 * A label / big number / caption tile.
 *
 * Extracted from the local `Stat` in features/avq/frontend/AVQDevicePage.tsx so there
 * is one implementation rather than two that drift. `dense` reproduces that page's
 * inline sizing; the default is the larger form the Analytics headline row uses.
 *
 * Proportional figures deliberately — `tabular-nums` makes a large standalone number
 * look loose, and is for columns that must align vertically, not for hero values.
 *
 * `grow` exists because a row of these laid out with `gap` alone does not align, even
 * though every value shares one baseline. Each tile is as wide as its own widest line,
 * so two rows of different content space out differently and the gaps read as ragged.
 * `minWidth` makes that worse whenever it exceeds the content: the leftover sits inside
 * the tile as trailing whitespace, so a tile needing 114px but reserving 150px opens a
 * 36px hole after it. `grow` instead makes every tile in the row an equal share of the
 * available width, which puts all the columns on one grid and every gap on one value.
 */
export interface StatTileProps {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  color?: string;
  dense?: boolean;
  minWidth?: number;
  /** Equal-share column sizing, for a row that must align. See the note above. */
  grow?: boolean;
}

export const StatTile: React.FC<StatTileProps> = ({
  label,
  value,
  sub,
  color,
  dense = false,
  minWidth = 72,
  grow = false,
}) => (
  // `1 1 0` rather than `1 1 auto`: flex-basis 0 makes the equal share independent of
  // content, so one wide value cannot push its neighbours off the grid. minWidth stays
  // as the floor that lets the tile wrap rather than squash on a narrow viewport.
  // A `grow` tile also centres its own text: once the columns are equal, the leftover
  // space sits inside every tile, so left-aligning the content leaves each number
  // hugging its column's left edge with a void to its right — visibly unaligned even
  // though the grid itself is even. `textAlign` also centres the `noWrap` label and the
  // caption, so all three lines stack on one axis.
  <Box sx={grow ? { flex: '1 1 0', minWidth, textAlign: 'center' } : { minWidth }}>
    <Typography
      variant="caption"
      color="text.secondary"
      noWrap
      sx={
        dense
          ? { fontSize: '0.68rem', lineHeight: 1 }
          : {
              fontSize: '0.625rem',
              fontWeight: 600,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              lineHeight: 1,
              display: 'block',
            }
      }
    >
      {label}
    </Typography>
    <Typography
      variant={dense ? 'subtitle1' : 'h4'}
      sx={{
        color: color || 'text.primary',
        lineHeight: 1.2,
        fontWeight: 600,
        mt: dense ? 0 : 0.5,
        fontSize: dense ? undefined : '1.875rem',
      }}
    >
      {value}
    </Typography>
    {sub != null && (
      <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.6875rem' }}>
        {sub}
      </Typography>
    )}
  </Box>
);

export default StatTile;
