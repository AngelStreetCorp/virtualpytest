import React from 'react';
import { Box } from '@mui/material';

/**
 * BuilderMainContainer - Main content area container
 * 
 * Container for sidebar + canvas.
 * EXACT match to TestCaseBuilder main container structure.
 */

interface BuilderMainContainerProps {
  children: React.ReactNode;
}

export const BuilderMainContainer: React.FC<BuilderMainContainerProps> = ({ children }) => {
  return (
    <Box sx={{ 
      flex: 1,
      display: 'flex', 
      overflow: 'hidden',
      minHeight: 0,
      position: 'relative',
    }}>
      {children}
    </Box>
  );
};
