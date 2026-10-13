import { Box, Tooltip, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../../../frontend/src/constants/agentChatTheme';
import { useI18n } from '../../../../../frontend/src/i18n/useI18n';
import { listedNames } from '../actions';
import { useOnline } from '../hooks/useOnline';

/** "● 3 online" in the top bar; the tooltip lists who. */
export const OnlineChip: React.FC = () => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const presence = useOnline();
  if (!presence) return null;

  const { names, more } = listedNames(presence);
  const tooltip = (
    <Box>
      {names.map((name) => (
        <Typography key={name} sx={{ fontSize: '0.75rem' }}>
          {name}
        </Typography>
      ))}
      {more > 0 && <Typography sx={{ fontSize: '0.75rem' }}>{t('+{count} more', { count: more })}</Typography>}
      {presence.sharedSessions > 0 && (
        <Typography sx={{ fontSize: '0.7rem', opacity: 0.8, mt: 0.5 }}>
          {tn(presence.sharedSessions, '{count} shared session', '{count} shared sessions')}
        </Typography>
      )}
    </Box>
  );

  return (
    <Tooltip title={tooltip}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, px: 1, cursor: 'default' }}>
        <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: presence.online ? P.success : P.textMuted }} />
        <Typography sx={{ fontSize: '0.8rem', color: P.textSecondary, whiteSpace: 'nowrap' }}>
          {tn(presence.online, '{count} online', '{count} online')}
        </Typography>
      </Box>
    </Tooltip>
  );
};
