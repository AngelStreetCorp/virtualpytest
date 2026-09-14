import React from 'react';
import { Box, Typography } from '@mui/material';
import { Handle, Position, NodeProps } from 'reactflow';
import NavigationIcon from '@mui/icons-material/Navigation';
import { useTheme } from '../../../contexts/ThemeContext';
import { NavigationBlockData } from '../../../types/testcase/TestCase_Types';

/**
 * Navigation Block - Executes goto navigation
 * Has both success and failure output handles
 */
export const NavigationBlock: React.FC<NodeProps> = ({ data, selected, dragging }) => {
  const { actualMode } = useTheme();
  const navigationData = data as NavigationBlockData;
  
  const isConfigured = Boolean(navigationData.target_node_label);
  
  return (
    <Box
      sx={{
        minWidth: 180,
        border: selected ? '3px solid #fbbf24' : `2px solid ${actualMode === 'dark' ? '#10b981' : '#059669'}`,
        borderRadius: 2,
        background: actualMode === 'dark' ? '#1f2937' : '#ffffff',
        boxShadow: 2,
        cursor: 'pointer',
        opacity: dragging ? 0.5 : (isConfigured ? 1 : 0.6),
        transition: 'opacity 0.2s',
        '&:hover': {
          boxShadow: 4,
        },
      }}
    >
      {/* Header */}
      <Box
        sx={{
          background: actualMode === 'dark' ? '#10b981' : '#059669',
          p: 1,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
        }}
      >
        <NavigationIcon sx={{ color: 'white', fontSize: 18 }} />
        <Typography color="white" fontWeight="bold" fontSize={13}>
          NAVIGATION
        </Typography>
      </Box>
      
      {/* Content */}
      <Box sx={{ p: 1.5 }}>
        {isConfigured ? (
          <>
            <Typography fontSize={11} color="text.secondary">
              goto
            </Typography>
            <Typography fontSize={14} fontWeight="medium" mt={0.5}>
              {navigationData.target_node_label}
            </Typography>
          </>
        ) : (
          <Typography fontSize={12} color="text.secondary">
            Click to select node
          </Typography>
        )}
      </Box>
      
      {/* Input handle at top - circle */}
      <Handle
        type="target"
        position={Position.Top}
        id="input"
        style={{
          background: actualMode === 'dark' ? '#10b981' : '#059669',
          width: 12,
          height: 12,
          borderRadius: '50%',
          border: '2px solid white',
          top: -6,
        }}
      />
      
      {/* Output handles at bottom - circles */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="success"
        style={{
          left: '35%',
          background: '#10b981',
          width: 12,
          height: 12,
          borderRadius: '50%',
          border: '2px solid white',
          bottom: -6,
        }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="failure"
        style={{
          left: '65%',
          background: '#ef4444',
          width: 12,
          height: 12,
          borderRadius: '50%',
          border: '2px solid white',
          bottom: -6,
        }}
      />
    </Box>
  );
};

