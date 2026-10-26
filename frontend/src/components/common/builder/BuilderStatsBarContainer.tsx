import React from 'react';
import { Box, Paper } from '@mui/material';

/**
 * BuilderStatsBarContainer - Bottom stats bar container
 * 
 * CONTAINER ONLY - styling matches TestCaseBuilder exactly.
 * Content is passed as children.
 * 
 * Styling: height: 32px, background: palette sidebarBg
 */

interface BuilderStatsBarContainerProps {
  actualMode: 'light' | 'dark';
  children: React.ReactNode;
}

export const BuilderStatsBarContainer: React.FC<BuilderStatsBarContainerProps> = ({
  children,
}) => {
  return (
    <Box
      component={Paper}
      elevation={0}
      square
      sx={{
        height: '32px',
        borderTop: 1,
        borderColor: 'divider',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        px: 2,
        flexShrink: 0,
      }}
    >
      {children}
    </Box>
  );
};

