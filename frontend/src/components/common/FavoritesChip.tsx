import { Star as StarIcon } from '@mui/icons-material';
import { Chip } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { TYPOGRAPHY } from '../../constants/typography';

interface FavoritesChipProps {
  count: number;
  /** All visible favorites are already selected: the next click clears them. */
  allSelected: boolean;
  onClick: () => void;
  disabled?: boolean;
}

/**
 * Compact "star + count" chip of the executable pickers (TASK-100). It stays on one line in the
 * tight Run Tests headers; the word "Favorites" is the tooltip and the aria-label. First click selects
 * every visible favorite, a second click clears them.
 */
export const FavoritesChip: React.FC<FavoritesChipProps> = ({ count, allSelected, onClick, disabled }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  return (
    <Chip
      size="small"
      title={t('Favorites')}
      aria-label={t('Favorites')}
      aria-pressed={allSelected}
      icon={<StarIcon sx={{ fontSize: TYPOGRAPHY.body.size, color: `${P.gold} !important` }} />}
      label={count}
      onClick={onClick}
      disabled={disabled}
      variant={allSelected ? 'filled' : 'outlined'}
      sx={{
        flexShrink: 0,
        height: 20,
        fontSize: TYPOGRAPHY.caption.size,
        whiteSpace: 'nowrap',
        borderColor: P.gold,
        color: P.textPrimary,
        '.MuiChip-label': { px: 0.75 },
        ...(allSelected ? { bgcolor: P.hoverBg } : {}),
      }}
    />
  );
};
