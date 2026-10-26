import React from 'react';
import { Box, Typography } from '@mui/material';
import { Handle, Position, NodeProps } from 'reactflow';
import { useTheme } from '../../../contexts/ThemeContext';
import { useAgentChatPalette } from '../../../constants/agentChatTheme';

interface TerminalBlockProps extends NodeProps {
  label: string;
  color: string;
}

/**
 * Terminal Block - Generic component for PASS/FAIL blocks
 * Used by SuccessBlock and FailureBlock
 * Clean, minimal design matching other blocks
 */
export const TerminalBlock: React.FC<TerminalBlockProps> = ({ label, color, selected, dragging }) => {
  const { actualMode } = useTheme();
  const P = useAgentChatPalette();
  
  // Muted colors for professional look
  const accentColor = color === '#10b981' ? P.success : P.error;
  
  return (
    <Box
      sx={{
        minWidth: 80,
        minHeight: 40,
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
        fontSize="0.75rem" 
        fontWeight={600} 
        sx={{ color: accentColor }}
      >
        {label}
      </Typography>
      
      {/* Transparent larger handle for better grabbing */}
      <Handle
        type="target"
        position={Position.Top}
        id="input-hitarea"
        style={{
          background: 'transparent',
          width: 24,
          height: 24,
          borderRadius: '50%',
          border: 'none',
          top: -12,
          pointerEvents: 'all',
        }}
      />
      
      {/* Visible input handle at top - small circle */}
      <Handle
        type="target"
        position={Position.Top}
        id="input"
        style={{
          background: accentColor,
          width: 14,
          height: 14,
          borderRadius: '50%',
          border: 'none',
          top: -7,
          boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
          pointerEvents: 'none',
        }}
      />
    </Box>
  );
};
