import React from 'react';
import { Box, Typography } from '@mui/material';
import { Handle, Position, NodeProps } from 'reactflow';
import { useTheme } from '../../../contexts/ThemeContext';
import { useAgentChatPalette } from '../../../constants/agentChatTheme';

/**
 * Start Block - Entry point for testcase execution
 * Only has output handles (success/failure)
 */
export const StartBlock: React.FC<NodeProps> = ({ selected, dragging }) => {
  const { actualMode } = useTheme();
  const P = useAgentChatPalette();
  const accentColor = P.accent;
  
  return (
    <Box
      sx={{
        minWidth: 100,
        minHeight: 44,
        px: 2,
        py: 1,
        background: P.surfaceSolid,
        border: selected ? `2px solid ${P.accent}` : `1px solid ${P.borderColor}`,
        borderLeft: `3px solid ${accentColor}`,
        borderRadius: 1.5,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        opacity: dragging ? 0.5 : 1,
        transition: 'all 0.2s ease',
        boxShadow: actualMode === 'dark' 
          ? '0 2px 8px rgba(0,0,0,0.3)' 
          : '0 2px 8px rgba(0,0,0,0.08)',
        '&:hover': {
          boxShadow: actualMode === 'dark' 
            ? '0 4px 16px rgba(0,0,0,0.4)' 
            : '0 4px 16px rgba(0,0,0,0.12)',
        },
      }}
    >
      <Typography 
        fontSize="0.8125rem" 
        fontWeight={600} 
        sx={{ color: P.accentText }}
      >
        START
      </Typography>
      
      {/* Transparent larger handle for better grabbing */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="success-hitarea"
        style={{
          background: 'transparent',
          width: 24,
          height: 24,
          borderRadius: '50%',
          border: 'none',
          bottom: -12,
          pointerEvents: 'all',
        }}
      />
      
      {/* Visible output handle at bottom - small circle */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="success"
        style={{
          background: accentColor,
          width: 14,
          height: 14,
          borderRadius: '50%',
          border: 'none',
          bottom: -7,
          boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
          pointerEvents: 'none',
        }}
      />
    </Box>
  );
};

