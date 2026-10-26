import { Star as StarIcon, StarBorder as StarBorderIcon } from '@mui/icons-material';
import { IconButton, Tooltip } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useDeviceFavorites } from '../../hooks/useDeviceFavorites';
import { ExecutableKind, useExecutableFavorites } from '../../hooks/useExecutableFavorites';
import { useI18n } from '../../i18n/useI18n';

interface FavoriteStarButtonProps {
  active: boolean;
  onToggle: () => void;
  size?: 'small' | 'medium';
}

/**
 * The one favorites star of every picker (TASK-99 devices, TASK-100 executables): gold and filled =
 * favorite, muted outline = not. Always visible (touch devices and the APK have no hover). A click
 * toggles the favorite and never reaches the row, so it does not change the selection.
 */
export const FavoriteStarButton: React.FC<FavoriteStarButtonProps> = ({ active, onToggle, size = 'small' }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const label = active ? t('Remove from favorites') : t('Add to favorites');
  const Icon = active ? StarIcon : StarBorderIcon;

  return (
    <Tooltip title={label}>
      <IconButton
        size={size}
        aria-label={label}
        aria-pressed={active}
        onClick={(e) => {
          e.stopPropagation();
          e.preventDefault();
          onToggle();
        }}
        // Select/Menu items select on mousedown/keydown, so stop those too.
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
        sx={{ p: 0.25, flexShrink: 0, color: active ? P.gold : P.textMuted, '&:hover': { color: P.gold } }}
      >
        <Icon sx={{ fontSize: size === 'small' ? 18 : 22 }} />
      </IconButton>
    </Tooltip>
  );
};

interface DeviceFavoriteStarProps {
  hostName: string;
  deviceId: string;
  size?: 'small' | 'medium';
}

export const DeviceFavoriteStar: React.FC<DeviceFavoriteStarProps> = ({ hostName, deviceId, size }) => {
  const { isFavorite, toggle } = useDeviceFavorites();
  return <FavoriteStarButton active={isFavorite(hostName, deviceId)} onToggle={() => void toggle(hostName, deviceId)} size={size} />;
};

interface ExecutableFavoriteStarProps {
  kind: ExecutableKind;
  itemId: string;
  size?: 'small' | 'medium';
}

/** Star of a script, test case, virtual script or campaign row (TASK-100). */
export const ExecutableFavoriteStar: React.FC<ExecutableFavoriteStarProps> = ({ kind, itemId, size }) => {
  const { isFavorite, toggle } = useExecutableFavorites();
  return <FavoriteStarButton active={isFavorite(kind, itemId)} onToggle={() => void toggle(kind, itemId)} size={size} />;
};
