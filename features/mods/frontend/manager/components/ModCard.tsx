import { Extension } from '@mui/icons-material';
import { Box, Card, Switch, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../../../frontend/src/constants/agentChatTheme';
import { useI18n } from '../../../../../frontend/src/i18n/useI18n';
import type { ModDefinition } from '../../../../../frontend/src/mods/core/types';

interface Props {
  mod: ModDefinition;
  enabled: boolean;
  onToggle: (on: boolean) => void;
}

/** One installed mod with its on/off switch, like a browser extension card. */
export const ModCard: React.FC<Props> = ({ mod, enabled, onToggle }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();

  return (
    <Card sx={{ p: 2, display: 'flex', gap: 1.5, alignItems: 'flex-start', bgcolor: P.surface }}>
      <Extension sx={{ color: enabled ? P.accentText : P.textMuted, mt: 0.25 }} />
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography sx={{ fontSize: '0.95rem', fontWeight: 600, color: P.textPrimary }}>{t(mod.name)}</Typography>
        <Typography sx={{ fontSize: '0.8rem', color: P.textSecondary, mt: 0.25 }}>{t(mod.description)}</Typography>
        <Typography sx={{ fontSize: '0.7rem', color: P.textMuted, fontFamily: 'monospace', mt: 0.5 }}>{mod.id}</Typography>
      </Box>
      <Switch
        checked={enabled}
        onChange={(e) => onToggle(e.target.checked)}
        inputProps={{ 'aria-label': t(mod.name) }}
      />
    </Card>
  );
};
