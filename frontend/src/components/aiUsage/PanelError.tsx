/** The one failure line of every panel on the AI usage page: plain words, error style, a Retry. */
import { ErrorOutline as ErrorIcon } from '@mui/icons-material';
import { Box, Button, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';

export const PanelError: React.FC<{ what: string; onRetry: () => void }> = ({ what, onRetry }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  return (
    <Box role="alert" sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 1, minHeight: 40 }}>
      <ErrorIcon sx={{ fontSize: 18, color: P.error, flexShrink: 0 }} />
      <Typography sx={{ fontSize: '0.85rem', color: P.error }}>{t("Couldn't load {what}.", { what })}</Typography>
      <Button size="small" onClick={onRetry} disableRipple sx={{ textTransform: 'none', transition: 'none', flexShrink: 0, whiteSpace: 'nowrap' }}>
        {t('Retry')}
      </Button>
    </Box>
  );
};
