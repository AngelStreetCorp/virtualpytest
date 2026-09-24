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
 */
export interface StatTileProps {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  color?: string;
  dense?: boolean;
  minWidth?: number;
}

export const StatTile: React.FC<StatTileProps> = ({
  label,
  value,
  sub,
  color,
  dense = false,
  minWidth = 72,
}) => (
  <Box sx={{ minWidth }}>
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
