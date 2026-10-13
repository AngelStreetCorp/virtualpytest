import { Box, Tooltip } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { useI18n } from '../../../i18n/useI18n';
import type { GroupAck } from '../../../types/pages/groupControl.types';

/**
 * One group member's status: a dot plus the last command's result word, in a
 * fixed-width slot so the row never shifts. While a send is in flight the slot
 * keeps the previous result (no flash); the reason of an error is in the tooltip.
 */
export const GroupStatusLed: React.FC<{ controlled: boolean; ack: GroupAck | null; error: string | null }> = ({
  controlled,
  ack,
  error,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();

  const state = !controlled ? 'error' : ack ?? 'ok';
  const color = { ok: P.success, error: P.error, skipped: P.warning }[state];
  const label = controlled && ack ? { ok: t('Sent'), error: t('Error'), skipped: t('Skipped') }[ack] : '';

  return (
    <Tooltip title={error ?? ''} disableHoverListener={!error}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, width: 76, flexShrink: 0, minWidth: 0 }}>
        <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: color, flexShrink: 0 }} />
        <Box
          component="span"
          sx={{ fontSize: '0.7rem', fontWeight: 600, color, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
        >
          {label}
        </Box>
      </Box>
    </Tooltip>
  );
};
