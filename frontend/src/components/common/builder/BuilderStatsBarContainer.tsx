import React from 'react';
import { Box } from '@mui/material';

/**
 * BuilderStatsBarContainer - Bottom stats bar container
 * 
 * CONTAINER ONLY - styling matches TestCaseBuilder exactly.
 * Content is passed as children.
 * 
 * Styling: height: 32px, background: dark #1e293b / light #f1f5f9
 */

interface BuilderStatsBarContainerProps {
  actualMode: 'light' | 'dark';
  children: React.ReactNode;
}

export const BuilderStatsBarContainer: React.FC<BuilderStatsBarContainerProps> = ({
  actualMode,
  children,
}) => {
  return (
    <Box
      sx={{
        height: '32px',
        borderTop: 1,
        borderColor: 'divider',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        px: 2,
        background: actualMode === 'dark' ? '#1e293b' : '#f1f5f9',
        flexShrink: 0,
      }}
    >
      {children}
    </Box>
  );
};

