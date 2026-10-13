import React from 'react';
import { AGENT_CHAT_PALETTE, AGENT_CHAT_PALETTE_LIGHT } from '../../../constants/agentChatTheme';
import { Box, IconButton } from '@mui/material';
import { ChevronRight as ChevronRightIcon } from '@mui/icons-material';

/**
 * BuilderSidebarContainer - Collapsible sidebar container
 * 
 * CONTAINER ONLY - styling matches TestCaseBuilder exactly.
 * Content is passed as children (toolbox, AI panel, etc.).
 * 
 * Styling: width: 280px, background: palette sidebarBg
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
  const P = actualMode === 'dark' ? AGENT_CHAT_PALETTE : AGENT_CHAT_PALETTE_LIGHT;
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
          background: P.sidebarBg,
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
              background: P.surface,
              border: 1,
              borderLeft: 0,
              borderColor: 'divider',
              '&:hover': {
                background: P.hoverBg,
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

