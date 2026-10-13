import { ChevronLeft, ChevronRight, Close, Settings } from '@mui/icons-material';
import { Box, IconButton, Tooltip, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../../constants/agentChatTheme';
import { useI18n } from '../../../../i18n/useI18n';
import { WIDGET_SPAN } from '../../constants';
import type { WidgetSize } from '../../types';
import { ModErrorBoundary } from '../ModErrorBoundary';

interface Props {
  title: string;
  size: WidgetSize;
  hasSettings: boolean;
  isFirst: boolean;
  isLast: boolean;
  onSettings: () => void;
  onMove: (step: -1 | 1) => void;
  onRemove: () => void;
  children: React.ReactNode;
}

/** Card around one widget; its controls show on hover. A widget that throws shows a note, not a blank page. */
export const WidgetFrame: React.FC<Props> = ({ title, size, hasSettings, isFirst, isLast, onSettings, onMove, onRemove, children }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const controlSx = { color: P.textMuted, p: 0.25 };

  return (
    <Box
      sx={{
        gridColumn: { xs: 'span 6', md: `span ${WIDGET_SPAN[size]}` },
        border: `1px solid ${P.borderColor}`,
        borderRadius: 3,
        bgcolor: P.surface,
        minWidth: 0,
        '&:hover .widget-controls': { opacity: 1 },
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', px: 1.5, pt: 1 }}>
        <Typography sx={{ fontSize: '0.85rem', fontWeight: 600, color: P.textPrimary, flex: 1 }} noWrap>
          {title}
        </Typography>
        <Box className="widget-controls" sx={{ display: 'flex', opacity: { xs: 1, md: 0 }, transition: 'opacity 0.15s' }}>
          <Tooltip title={t('Move left')}>
            <span>
              <IconButton size="small" disabled={isFirst} onClick={() => onMove(-1)} sx={controlSx}>
                <ChevronLeft fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title={t('Move right')}>
            <span>
              <IconButton size="small" disabled={isLast} onClick={() => onMove(1)} sx={controlSx}>
                <ChevronRight fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
          {hasSettings && (
            <Tooltip title={t('Widget settings')}>
              <IconButton size="small" onClick={onSettings} sx={controlSx}>
                <Settings fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
          <Tooltip title={t('Remove')}>
            <IconButton size="small" onClick={onRemove} sx={controlSx}>
              <Close fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>
      <Box sx={{ px: 1.5, pb: 1.5, pt: 0.5 }}>
        <ModErrorBoundary
          slot={`widget ${title}`}
          fallback={<Typography sx={{ fontSize: '0.8rem', color: P.textMuted }}>{t('This widget failed to load.')}</Typography>}
        >
          {children}
        </ModErrorBoundary>
      </Box>
    </Box>
  );
};
