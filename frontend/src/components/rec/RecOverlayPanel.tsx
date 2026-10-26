import CloseIcon from '@mui/icons-material/Close';
import { Box, IconButton, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { TYPOGRAPHY } from '../../constants/typography';

interface RecOverlayPanelProps {
  title: string;
  onClose: () => void;
  /** Optional control placed in the header row, between the title and the close button. */
  headerExtra?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * Shared slot for the panels opened from the Actions menu (AI Prompt, Go to node):
 * same position, width, surface and header row (title + close X).
 */
export const RecOverlayPanel: React.FC<RecOverlayPanelProps> = ({ title, onClose, headerExtra, children }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  return (
    <Box
      sx={{
        position: 'absolute',
        top: 10,
        left: 10,
        // Above the stream caption/transcript/restart overlays (hardcoded ~1250-1000040 z-indexes).
        zIndex: 1000050,
        pointerEvents: 'auto',
        width: 420,
        maxWidth: 'calc(100% - 20px)',
        maxHeight: 'calc(100% - 20px)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        bgcolor: P.surface,
        color: P.textPrimary,
        borderRadius: 2,
        border: `1px solid ${P.borderColor}`,
      }}
    >
      <Box sx={{ p: 2, pb: 0, flexShrink: 0 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, mb: 1.5 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, whiteSpace: 'nowrap', fontSize: TYPOGRAPHY.navbarItem.size }}>
            {title}
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0 }}>
            {headerExtra}
            <IconButton size="small" aria-label={t('Close')} onClick={onClose} sx={{ color: P.textMuted }}>
              <CloseIcon fontSize="small" />
            </IconButton>
          </Box>
        </Box>
      </Box>
      <Box
        sx={{
          p: 2,
          pt: 0,
          minHeight: 0,
          overflowY: 'auto',
          scrollbarWidth: 'thin',
          scrollbarColor: 'transparent transparent',
          '&:hover': { scrollbarColor: `${P.borderColor} transparent` },
          '&::-webkit-scrollbar': { width: 6 },
          '&::-webkit-scrollbar-thumb': { background: 'transparent', borderRadius: 3 },
          '&:hover::-webkit-scrollbar-thumb': { background: P.borderColor },
        }}
      >
        {children}
      </Box>
    </Box>
  );
};

export default RecOverlayPanel;
