/**
 * Run status presentation: one colour and label per RunStatus, from the analytics palette.
 * Identity is never colour alone — every chip carries its text.
 */

import { Chip, type ChipProps } from '@mui/material';
import React from 'react';

import { STATUS } from '../analytics/palette';
import { AGENT_CHAT_PALETTE, onPalettesChange } from '../../constants/agentChatTheme';
import type { RunStatus } from '../../types/reports';

// Not a component (no hooks): rebuilt in place on a colour-theme switch. Running = the theme accent,
// skipped / unknown = the muted text grey. Status colours (passed/failed/...) are never themed.
const buildStatusColors = (): Record<RunStatus, string> => ({
  passed: STATUS.good,
  failed: STATUS.critical,
  running: AGENT_CHAT_PALETTE.accent,
  pending: STATUS.warning,
  skipped: AGENT_CHAT_PALETTE.textMuted,
  cancelled: STATUS.serious,
  unknown: AGENT_CHAT_PALETTE.textMuted,
});

export const STATUS_COLORS: Record<RunStatus, string> = buildStatusColors();
onPalettesChange(() => Object.assign(STATUS_COLORS, buildStatusColors()));

export const STATUS_LABELS: Record<RunStatus, string> = {
  passed: 'Passed',
  failed: 'Failed',
  running: 'Running',
  pending: 'Pending',
  skipped: 'Skipped',
  cancelled: 'Cancelled',
  unknown: 'Unknown',
};

export interface StatusChipProps {
  status: RunStatus;
  size?: ChipProps['size'];
}

export const StatusChip: React.FC<StatusChipProps> = ({ status, size = 'small' }) => (
  <Chip
    size={size}
    label={STATUS_LABELS[status]}
    data-status={status}
    variant="outlined"
    sx={{
      borderColor: STATUS_COLORS[status],
      color: STATUS_COLORS[status],
      fontWeight: 600,
      height: size === 'small' ? 22 : undefined,
    }}
  />
);

export const formatDurationMs = (ms: number | null | undefined): string => {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const totalSeconds = Math.round(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
};

export const formatDateTime = (iso: string | null | undefined): string => {
  if (!iso) return '—';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
};
