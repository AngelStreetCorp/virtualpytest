import React from 'react';
import { Box, Typography, IconButton } from '@mui/material';
import {
  Close as CloseIcon,
  Terminal as TerminalIcon
} from '@mui/icons-material';
import { useAIContext } from '../../../contexts/AIContext';
import { useAgentChatPalette } from '../../../constants/agentChatTheme';

export const LogTerminalPanel: React.FC = () => {
  const { toggleLogs } = useAIContext();
  const P = useAgentChatPalette();

  return (
    <Box
      sx={{
        position: 'fixed',
        left: 0,
        right: 0,
        bottom: 0,
        height: 200,
        bgcolor: P.surface,
        color: P.textPrimary,
        borderTop: `1px solid ${P.borderColor}`,
        zIndex: 1200,
        display: 'flex',
        flexDirection: 'column',
        fontFamily: 'monospace'
      }}
    >
      {/* Header */}
      <Box sx={{
        px: 2, py: 0.5,
        display: 'flex',
        alignItems: 'center',
        bgcolor: P.sidebarBg,
        borderBottom: `1px solid ${P.borderColor}`
      }}>
        <TerminalIcon sx={{ mr: 1, fontSize: 16, color: P.textMuted }} />
        <Typography variant="caption" sx={{ flex: 1, fontFamily: 'monospace', color: P.textMuted }}>
          System Logs
        </Typography>
        <IconButton size="small" onClick={toggleLogs} sx={{ color: P.textMuted, p: 0.5 }}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* Log Content */}
      <Box sx={{ flex: 1, overflowY: 'auto', p: 1.5, fontSize: '0.85rem' }}>
        <div style={{ color: P.success }}>➜  System initialized.</div>
        <div style={{ color: P.textMuted }}>[INFO] Listening for AI events...</div>
        {/* Placeholder logs */}
      </Box>
    </Box>
  );
};

