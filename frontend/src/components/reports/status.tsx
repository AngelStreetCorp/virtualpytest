/**
 * Run status presentation: one colour and label per RunStatus, from the analytics palette.
 * Identity is never colour alone — every chip carries its text.
 */

import { Chip, type ChipProps } from '@mui/material';
import React from 'react';

import { STATUS } from '../analytics/palette';
import { AGENT_CHAT_PALETTE } from '../../constants/agentChatTheme';
import type { RunStatus } from '../../types/reports';

// Static (no hooks in this module): both themes use the same neutral grey for unknown status,
// same muted grey for skipped. The palette's textMuted stays neutral across light/dark.
const NEUTRAL = AGENT_CHAT_PALETTE.textMuted;

export const STATUS_COLORS: Record<RunStatus, string> = {
  passed: STATUS.good,
  failed: STATUS.critical,
  running: AGENT_CHAT_PALETTE.accent, // running = the app's gold accent (static: same in both themes)
  pending: STATUS.warning,
  skipped: AGENT_CHAT_PALETTE.textMuted,
  cancelled: STATUS.serious,
  unknown: NEUTRAL,
};

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
