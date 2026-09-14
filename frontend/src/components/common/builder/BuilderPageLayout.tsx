import React from 'react';
import { Box } from '@mui/material';

/**
 * BuilderPageLayout - Page-level container
 * 
 * Fixed positioning below navigation (top: 64px) and above footer (bottom: 32px).
 * EXACT match to TestCaseBuilder page structure.
 */

interface BuilderPageLayoutProps {
  children: React.ReactNode;
}

export const BuilderPageLayout: React.FC<BuilderPageLayoutProps> = ({ children }) => {
  return (
    <Box sx={{ 
      position: 'fixed',
      top: 64,
      left: 0,
      right: 0,
      bottom: 32, // Leave space for shared Footer (minHeight 24 + py 8 = 32px)
      display: 'flex', 
      flexDirection: 'column', 
      overflow: 'hidden',
      zIndex: 1,
    }}>
      {children}
    </Box>
  );
};

