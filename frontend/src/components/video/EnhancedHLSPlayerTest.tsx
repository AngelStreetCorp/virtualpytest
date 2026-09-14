import React from 'react';
import { Box, Typography } from '@mui/material';
import { EnhancedHLSPlayer } from './EnhancedHLSPlayer';

/**
 * Test component for Enhanced HLS Player
 * Use this to test the player functionality independently
 */
export const EnhancedHLSPlayerTest: React.FC = () => {
  return (
    <Box sx={{ p: 2, maxWidth: 800, mx: 'auto' }}>
      <Typography variant="h4" gutterBottom>
        Enhanced HLS Player Test
      </Typography>
      
      <Typography variant="body1" sx={{ mb: 2 }}>
        This player should show:
        <br />• Live/24h toggle at the top
        <br />• Timeline scrubber when in 24h mode
        <br />• Custom controls at the bottom
      </Typography>

      <EnhancedHLSPlayer
        deviceId="device1"
        hostName="test-host"
        width="100%"
        height={400}
      />
      
      <Typography variant="caption" sx={{ mt: 2, display: 'block' }}>
        Stream URL: /host/stream/capture1/segments/output.m3u8
      </Typography>
    </Box>
  );
};
