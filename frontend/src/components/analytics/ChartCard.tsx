import { Box, Card, CardContent, CircularProgress, Typography } from '@mui/material';
import React from 'react';

/**
 * The frame every Analytics chart sits in: title, subtitle, and the loading /
 * empty / error gates.
 *
 * No Grafana link here on purpose. One per card crowded the header — 'Disk usage'
 * wrapped onto three lines and no longer lined up with its neighbours — and repeated
 * the same destination up to four times per tab. It lives once, in the page header.
 *
 * Gating rules that matter:
 *
 *   - `loading` is a BOOLEAN, never "is the array empty". An empty array is a real,
 *     renderable answer ("no incidents"), and treating it as loading leaves a spinner
 *     up forever on a healthy fleet.
 *   - A refetch does NOT re-show the spinner. Once there is content, a background
 *     refresh dims it to 60% instead, so switching tabs never causes a layout jump
 *     or a skeleton flash.
 */
export interface ChartCardProps {
  title: string;
  subtitle?: string;
  /** True only while there is nothing to show yet. */
  loading?: boolean;
  /** True while refreshing content that is already on screen. */
  refreshing?: boolean;
  error?: string | null;
  /** Rendered instead of children when there is no data. */
  empty?: boolean;
  emptyMessage?: string;
  minHeight?: number;
  flex?: number | string;
  children: React.ReactNode;
}

export const ChartCard: React.FC<ChartCardProps> = ({
  title,
  subtitle,
  loading = false,
  refreshing = false,
  error = null,
  empty = false,
  emptyMessage = 'Nothing recorded in this window',
  minHeight = 220,
  flex = 1,
  children,
}) => (
  <Card variant="outlined" sx={{ flex, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
    <CardContent
      sx={{ p: 2, pb: '16px !important', display: 'flex', flexDirection: 'column', flexGrow: 1 }}
    >
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, mb: 1.5 }}>
        <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary' }}>
          {title}
        </Typography>
        {subtitle && (
          <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.6875rem' }}>
            {subtitle}
          </Typography>
        )}
      </Box>

      <Box
        sx={{
          flexGrow: 1,
          minHeight,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: loading || error || empty ? 'center' : 'flex-start',
          alignItems: loading || error || empty ? 'center' : 'stretch',
          // A refresh dims what is already there rather than replacing it with a
          // skeleton — no flash, no reflow.
          opacity: refreshing && !loading ? 0.6 : 1,
          transition: 'opacity 120ms ease',
        }}
      >
        {loading ? (
          <CircularProgress size={22} />
        ) : error ? (
          <Typography variant="caption" color="error" sx={{ textAlign: 'center' }}>
            {error}
          </Typography>
        ) : empty ? (
          <Typography variant="caption" color="text.secondary">
            {emptyMessage}
          </Typography>
        ) : (
          children
        )}
      </Box>
    </CardContent>
  </Card>
);

export default ChartCard;
