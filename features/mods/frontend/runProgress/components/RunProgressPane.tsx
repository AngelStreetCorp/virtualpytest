import { Close } from '@mui/icons-material';
import { Box, IconButton, Tooltip, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../../../frontend/src/constants/agentChatTheme';
import { useI18n } from '../../../../../frontend/src/i18n/useI18n';
import type { ModApi } from '../../../../../frontend/src/mods/core/types';
import { useRunProgress } from '../hooks/useRunProgress';

import { RunProgressRow } from './RunProgressRow';

/** Side pane: one row per run, running first. */
export const RunProgressPane: React.FC<{ $: ModApi }> = ({ $ }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { rows, summary } = useRunProgress();

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', px: 2, py: 1.5, borderBottom: `1px solid ${P.borderColor}` }}>
        <Box sx={{ flex: 1 }}>
          <Typography sx={{ fontSize: '1rem', fontWeight: 600, color: P.textPrimary }}>{t('Run progress')}</Typography>
          <Typography sx={{ fontSize: '0.75rem', color: P.textMuted }}>
            {t('{running} running · {passed} passed · {failed} failed', {
              running: summary.running,
              passed: summary.passed,
              failed: summary.failed,
            })}
          </Typography>
        </Box>
        <Tooltip title={t('Close')}>
          <IconButton size="small" onClick={$.ui.closePane} sx={{ color: P.textMuted }}>
            <Close fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
      <Box sx={{ flex: 1, overflowY: 'auto', px: 2 }}>
        {rows.length === 0 ? (
          <Typography sx={{ fontSize: '0.8rem', color: P.textMuted, py: 3, textAlign: 'center' }}>
            {t('No run in progress')}
          </Typography>
        ) : (
          rows.map((row) => <RunProgressRow key={row.id} row={row} />)
        )}
      </Box>
    </Box>
  );
};
