import React from 'react';
import { Box } from '@mui/material';
import { AGENT_CHAT_PALETTE, AGENT_CHAT_PALETTE_LIGHT } from '../../../constants/agentChatTheme';

/**
 * BuilderHeaderContainer - Header container
 * 
 * CONTAINER ONLY - styling matches TestCaseBuilder exactly.
 * Content is passed as children (device controls, buttons, etc.).
 * 
 * Styling: height: 46px, background: palette surface
 */

interface BuilderHeaderContainerProps {
  actualMode: 'light' | 'dark';
  children: React.ReactNode;
}

export const BuilderHeaderContainer: React.FC<BuilderHeaderContainerProps> = ({
  actualMode,
  children,
}) => {
  return (
    <Box
      sx={{
        px: 2,
        py: 0,
        borderBottom: 1,
        borderColor: 'divider',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: actualMode === 'dark' ? AGENT_CHAT_PALETTE.surface : AGENT_CHAT_PALETTE_LIGHT.surface,
        height: '46px',
        flexShrink: 0,
      }}
    >
      {children}
    </Box>
  );
};

