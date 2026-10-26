import { Extension } from '@mui/icons-material';
import { Box, Card, Switch, Tooltip, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../../../frontend/src/constants/agentChatTheme';
import { useI18n } from '../../../../../frontend/src/i18n/useI18n';
import type { ModDefinition } from '../../../../../frontend/src/mods/core/types';

interface Props {
  mod: ModDefinition;
  enabled: boolean;
  onToggle: (on: boolean) => void;
}

/** One installed mod — single-row layout: icon on the left, centered name, switch on
 *  the right. The blurb is not in the body (it was cutting off in long descriptions
 *  and made the card too wordy at 20+ mods); it lives in a tooltip on the name so
 *  it is still one click away. The human name is the only label (no duplicate
 *  `mod.id` slug). A small gold dot top-right lights up when the mod is On,
 *  echoing the qa-agent "This computer" cards.  */
export const ModCard: React.FC<Props> = ({ mod, enabled, onToggle }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();

  return (
    <Card
      sx={{
        p: '8px 14px',
        display: 'grid',
        gridTemplateColumns: '32px 1fr auto',
        alignItems: 'center',
        gap: 1.25,
        bgcolor: P.surface,
        position: 'relative',
        transition: 'border-color 0.15s, transform 0.15s',
        '&:hover': {
          borderColor: P.accentText,
          transform: 'translateY(-1px)',
        },
      }}
    >
      {/* Status dot, only visible when the mod is On — qa-agent-style glance indicator */}
      {enabled && (
        <Box
          aria-hidden
          sx={{
            position: 'absolute',
            top: 8,
            right: 8,
            width: 7,
            height: 7,
            borderRadius: '50%',
            bgcolor: P.accentText,
          }}
        />
      )}

      {/* Icon on the left — soft accent tile */}
      <Box
        sx={{
          width: 32,
          height: 32,
          borderRadius: 1.5,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: enabled ? P.selectedBg : P.hoverBg,
          color: enabled ? P.accentText : P.textMuted,
          opacity: enabled ? 1 : 0.7,
          flexShrink: 0,
        }}
      >
        <Extension sx={{ fontSize: 17 }} />
      </Box>

      {/* Centered name; full blurb on hover. Truncates gracefully on a narrow card. */}
      <Tooltip title={t(mod.description)} placement="top" disableInteractive>
        <Box sx={{ minWidth: 0, textAlign: 'center' }}>
          <Typography
            noWrap
            sx={{ fontSize: '0.92rem', fontWeight: 600, color: P.textPrimary, lineHeight: 1.2 }}
          >
            {t(mod.name)}
          </Typography>
        </Box>
      </Tooltip>

      <Switch
        checked={enabled}
        onChange={(e) => onToggle(e.target.checked)}
        inputProps={{ 'aria-label': t(mod.name) }}
        sx={{ flexShrink: 0 }}
      />
    </Card>
  );
};
