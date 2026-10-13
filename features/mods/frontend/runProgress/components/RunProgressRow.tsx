import { Box, Button, LinearProgress, Typography } from '@mui/material';
import React from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { useAgentChatPalette } from '../../../../../frontend/src/constants/agentChatTheme';
import { useI18n } from '../../../../../frontend/src/i18n/useI18n';
import { rowPercent } from '../actions';
import { liveRunPath } from '../constants';
import type { RunRow } from '../types';

import { RunStatusIcon } from './RunStatusIcon';

const outcomeColor = (row: RunRow, P: ReturnType<typeof useAgentChatPalette>) =>
  row.outcome === 'passed' ? P.success : row.outcome === 'failed' ? P.error : P.accent;

export const RunProgressRow: React.FC<{ row: RunRow }> = ({ row }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const pct = rowPercent(row);
  const where = [row.hostName, row.deviceId].filter(Boolean).join(' · ');
  const detail =
    row.outcome === 'failed' && row.error
      ? row.error
      : row.stepNumber !== undefined && row.totalSteps
        ? `${t('Step {current}/{total}', { current: row.stepNumber, total: row.totalSteps })}${row.step ? `: ${row.step}` : ''}`
        : row.message;

  return (
    <Box sx={{ py: 1.25, borderBottom: `1px solid ${P.borderColor}` }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <RunStatusIcon outcome={row.outcome} />
        <Typography sx={{ fontSize: '0.8rem', fontWeight: 600, color: P.textPrimary }}>{row.kind}</Typography>
        <Typography sx={{ fontSize: '0.7rem', fontFamily: 'monospace', color: P.textMuted }} noWrap>
          {row.id.slice(0, 8)}
        </Typography>
        <Box sx={{ flex: 1 }} />
        {pct !== undefined && (
          <Typography sx={{ fontSize: '0.75rem', color: P.textSecondary }}>{pct}%</Typography>
        )}
      </Box>
      {where && (
        <Typography sx={{ fontSize: '0.75rem', color: P.textSecondary, mt: 0.25 }} noWrap>
          {where}
        </Typography>
      )}
      <LinearProgress
        variant={pct === undefined ? 'indeterminate' : 'determinate'}
        value={pct ?? 0}
        sx={{
          mt: 0.75,
          height: 4,
          borderRadius: 2,
          bgcolor: P.hoverBg,
          '& .MuiLinearProgress-bar': { bgcolor: outcomeColor(row, P) },
        }}
      />
      <Box sx={{ display: 'flex', alignItems: 'center', mt: 0.5, gap: 1 }}>
        <Typography
          sx={{ fontSize: '0.75rem', color: row.outcome === 'failed' ? P.error : P.textMuted, flex: 1 }}
          noWrap
          title={detail}
        >
          {detail || (row.outcome === 'running' ? t('Waiting for progress…') : '')}
        </Typography>
        {row.kind === 'script' && (
          <Button
            size="small"
            component={RouterLink}
            to={liveRunPath(row.id)}
            sx={{ color: P.accentText, minWidth: 0, fontSize: '0.75rem', py: 0 }}
          >
            {t('Open live')}
          </Button>
        )}
      </Box>
    </Box>
  );
};
