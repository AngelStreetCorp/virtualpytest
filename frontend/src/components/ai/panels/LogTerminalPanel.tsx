import React from 'react';
import { Box, Typography, IconButton } from '@mui/material';
import { 
  Close as CloseIcon, 
  Terminal as TerminalIcon
} from '@mui/icons-material';
import { useAIContext } from '../../../contexts/AIContext';

export const LogTerminalPanel: React.FC = () => {
  const { toggleLogs } = useAIContext();

  return (
    <Box
      sx={{
        position: 'fixed',
        left: 0,
        right: 0,
        bottom: 0,
        height: 200,
        bgcolor: '#1e1e1e', // Dark terminal background
        color: '#f0f0f0',
        borderTop: '1px solid #333',
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
        bgcolor: '#2d2d2d', 
        borderBottom: '1px solid #333' 
      }}>
        <TerminalIcon sx={{ mr: 1, fontSize: 16, color: '#aaa' }} />
        <Typography variant="caption" sx={{ flex: 1, fontFamily: 'monospace', color: '#aaa' }}>
          System Logs
        </Typography>
        <IconButton size="small" onClick={toggleLogs} sx={{ color: '#aaa', p: 0.5 }}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* Log Content */}
      <Box sx={{ flex: 1, overflowY: 'auto', p: 1.5, fontSize: '0.85rem' }}>
        <div style={{ color: '#4caf50' }}>➜  System initialized.</div>
        <div style={{ color: '#aaa' }}>[INFO] Listening for AI events...</div>
        {/* Placeholder logs */}
      </Box>
    </Box>
  );
};

