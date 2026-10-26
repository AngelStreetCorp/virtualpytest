import { Box } from '@mui/material';
import React from 'react';

import { AppIcon } from '../../../constants/icons';
import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../../constants/typography';
import { LOL_SPELL_SLOTS, LolSpells } from '../../../types/game/LolOverlay_Types';

/** Q W E R D F cooldown row: seconds left, or ready (highlighted). Unlearned slots are muted. */
export const LolSpellRow: React.FC<{ spells?: LolSpells }> = ({ spells }) => {
  const P = useAgentChatPalette();
  if (!spells) return null;
  return (
    <Box data-testid="lol-spell-row" sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
      {LOL_SPELL_SLOTS.map((slot) => {
        const s = spells[slot];
        const learned = s?.ready_in_s != null;
        const ready = learned && (s?.ready_in_s ?? 0) <= 0;
        return (
          <Box
            key={slot}
            sx={{
              minWidth: 36, px: 0.75, py: 0.25, borderRadius: 1, textAlign: 'center', fontSize: TYPOGRAPHY.caption.size,
              bgcolor: P.sidebarBg, color: ready ? P.textPrimary : P.textMuted,
              border: `1px solid ${ready ? P.accent : P.borderColor}`, opacity: learned ? 1 : 0.5,
            }}
          >
            {slot} {learned ? (ready ? <AppIcon name="success" /> : `${Math.ceil(s!.ready_in_s!)}s`) : '–'}
          </Box>
        );
      })}
    </Box>
  );
};
