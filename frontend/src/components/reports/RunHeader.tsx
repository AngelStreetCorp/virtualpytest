/**
 * Header for a run report: title, kind, status and timing, plus an actions slot
 * (share, export, rerun…). Wraps on narrow screens instead of overflowing.
 */

import { Box, Chip, Typography } from '@mui/material';
import React from 'react';

import type { RunKind, RunStatus } from '../../types/reports';
import { StatusChip, formatDateTime, formatDurationMs } from './status';

const KIND_LABELS: Record<RunKind, string> = {
  script: 'Script run',
  campaign: 'Campaign run',
  group: 'Run group',
};

export interface RunHeaderProps {
  kind: RunKind;
  title: string;
  status: RunStatus;
  startedAt?: string | null;
  durationMs?: number | null;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}

export const RunHeader: React.FC<RunHeaderProps> = ({
  kind,
  title,
  status,
  startedAt,
  durationMs,
  subtitle,
  actions,
}) => (
  <Box
    sx={{
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'flex-start',
      justifyContent: 'space-between',
      gap: 1.5,
      mb: 2,
      minWidth: 0,
    }}
  >
    <Box sx={{ minWidth: 0, flex: '1 1 260px' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <Chip size="small" label={KIND_LABELS[kind]} />
        <StatusChip status={status} />
      </Box>
      <Typography variant="h5" component="h1" sx={{ mt: 1, wordBreak: 'break-word' }}>
        {title}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {startedAt ? `Started ${formatDateTime(startedAt)}` : 'Start time not recorded'}
        {durationMs !== undefined && ` · Duration ${formatDurationMs(durationMs)}`}
      </Typography>
      {subtitle}
    </Box>
    {actions && <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>{actions}</Box>}
  </Box>
);
