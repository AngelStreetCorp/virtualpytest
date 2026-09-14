import { Box, Typography } from '@mui/material';
import React from 'react';
import { formatCompactTimestamp } from '../../utils/recUtils';

interface RestartOverlayProps {
  sx?: any;
  timestamp?: string; // Timestamp to display
  onRestart?: () => void;
}

export const RestartOverlay: React.FC<RestartOverlayProps> = ({ timestamp }) => {
  return (
    <>
      {/* Timestamp overlay - top right */}
      {timestamp && (
        <Box
          sx={{
            position: 'absolute',
            top: 16,
            right: 16,
            zIndex: 20,
            p: 1,
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            borderRadius: 1,
            pointerEvents: 'none', // Don't interfere with clicks
            border: '1px solid rgba(255, 255, 255, 0.2)',
          }}
        >
          <Typography
            variant="body2"
            sx={{
              color: '#ffffff',
              fontSize: '0.8rem',
              fontWeight: 'bold',
              textShadow: '1px 1px 2px rgba(0,0,0,0.8)',
            }}
          >
            {formatCompactTimestamp(timestamp)}
          </Typography>
        </Box>
      )}
    </>
  );
};
