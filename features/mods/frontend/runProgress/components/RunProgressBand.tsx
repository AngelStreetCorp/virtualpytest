import { Close } from '@mui/icons-material';
import { Box, Button, IconButton, LinearProgress, Tooltip, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../../../frontend/src/constants/agentChatTheme';
import { useI18n } from '../../../../../frontend/src/i18n/useI18n';
import type { ModApi } from '../../../../../frontend/src/mods/core/types';
import { PANE_ID } from '../constants';
import { useRunProgress } from '../hooks/useRunProgress';

/** The thin bar under the top bar while runs are listed. */
export const RunProgressBand: React.FC<{ $: ModApi }> = ({ $ }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { summary, hidden, hide } = useRunProgress();

  if (hidden || summary.total === 0) return null;

  const barColor = summary.running ? P.accent : summary.failed ? P.error : P.success;

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1.5,
        px: 2,
        py: 0.5,
        bgcolor: P.surface,
        borderBottom: `1px solid ${P.borderColor}`,
      }}
    >
      <LinearProgress
        variant="determinate"
        value={summary.percent}
        sx={{
          flex: 1,
          height: 6,
          borderRadius: 3,
          bgcolor: P.hoverBg,
          '& .MuiLinearProgress-bar': { bgcolor: barColor },
        }}
      />
      <Typography sx={{ fontSize: '0.75rem', color: P.textSecondary, whiteSpace: 'nowrap' }}>
        {summary.percent}% ·{' '}
        {t('{running} running · {passed} passed · {failed} failed', {
          running: summary.running,
          passed: summary.passed,
          failed: summary.failed,
        })}
      </Typography>
      <Button size="small" onClick={() => $.ui.openPane(PANE_ID)} sx={{ color: P.accentText, minWidth: 0 }}>
        {t('Details')}
      </Button>
      <Tooltip title={t('Hide')}>
        <IconButton size="small" onClick={hide} sx={{ color: P.textMuted }}>
          <Close sx={{ fontSize: 16 }} />
        </IconButton>
      </Tooltip>
    </Box>
  );
};
