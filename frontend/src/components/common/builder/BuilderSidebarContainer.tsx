import React from 'react';
import { Box, IconButton } from '@mui/material';
import { ChevronRight as ChevronRightIcon } from '@mui/icons-material';

/**
 * BuilderSidebarContainer - Collapsible sidebar container
 * 
 * CONTAINER ONLY - styling matches TestCaseBuilder exactly.
 * Content is passed as children (toolbox, AI panel, etc.).
 * 
 * Styling: width: 280px, background: dark #0f172a / light #f8f9fa
 */

interface BuilderSidebarContainerProps {
  actualMode: 'light' | 'dark';
  isOpen: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

export const BuilderSidebarContainer: React.FC<BuilderSidebarContainerProps> = ({
  actualMode,
  isOpen,
  onToggle,
  children,
}) => {
  return (
    <>
      {/* Sidebar Container */}
      <Box
        sx={{
          position: 'absolute',
          left: 0,
          top: 0,
          bottom: 0,
          width: isOpen ? '280px' : '0px',
          transition: 'width 0.3s ease',
          overflow: 'hidden',
          borderRight: isOpen ? 1 : 0,
          borderColor: 'divider',
          display: 'flex',
          flexDirection: 'column',
          background: actualMode === 'dark' ? '#0f172a' : '#f8f9fa',
          zIndex: 5,
        }}
      >
        {isOpen && children}
      </Box>
      
      {/* Toggle Button (when sidebar is closed) */}
      {!isOpen && (
        <Box
          sx={{
            position: 'absolute',
            left: 0,
            top: '140px',
            zIndex: 10,
          }}
        >
          <IconButton
            onClick={onToggle}
            sx={{
              borderRadius: '0 8px 8px 0',
              background: actualMode === 'dark' ? '#1e293b' : '#ffffff',
              border: 1,
              borderLeft: 0,
              borderColor: 'divider',
              '&:hover': {
                background: actualMode === 'dark' ? '#334155' : '#f1f5f9',
              },
            }}
          >
            <ChevronRightIcon />
          </IconButton>
        </Box>
      )}
    </>
  );
};

