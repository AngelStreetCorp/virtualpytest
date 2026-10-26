import React from 'react';
import { Box, Paper } from '@mui/material';

/**
 * BuilderHeaderContainer - Header container
 * 
 * CONTAINER ONLY - styling matches TestCaseBuilder exactly.
 * Content is passed as children (device controls, buttons, etc.).
 * 
 * Styling: height: 46px, themed Paper (card transparency)
 */

interface BuilderHeaderContainerProps {
  actualMode: 'light' | 'dark';
  children: React.ReactNode;
}

export const BuilderHeaderContainer: React.FC<BuilderHeaderContainerProps> = ({
  children,
}) => {
  return (
    <Box
      component={Paper}
      elevation={0}
      square
      sx={{
        px: 2,
        py: 0,
        borderBottom: 1,
        borderColor: 'divider',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        height: '46px',
        flexShrink: 0,
      }}
    >
      {children}
    </Box>
  );
};

