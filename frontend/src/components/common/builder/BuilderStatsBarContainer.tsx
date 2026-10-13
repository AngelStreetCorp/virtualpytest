import React from 'react';
import { AGENT_CHAT_PALETTE, AGENT_CHAT_PALETTE_LIGHT } from '../../../constants/agentChatTheme';
import { Box } from '@mui/material';

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
  actualMode,
  children,
}) => {
  const P = actualMode === 'dark' ? AGENT_CHAT_PALETTE : AGENT_CHAT_PALETTE_LIGHT;
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
        background: P.sidebarBg,
        flexShrink: 0,
      }}
    >
      {children}
    </Box>
  );
};

