/**
 * Shared Draggable Command Component
 * 
 * Extracted from TestCaseToolbox - now used by both TestCase and Campaign builders.
 * Renders a draggable command block from the toolbox configuration.
 */

import React from 'react';
import { Paper, Typography } from '@mui/material';

interface CommandConfig {
  type: string;
  label: string;
  icon?: any;
  color?: string;
  description?: string;
  defaultData?: any;
}

interface DraggableCommandProps {
  command: CommandConfig;
  onCloseProgressBar?: () => void;
}

export const DraggableCommand: React.FC<DraggableCommandProps> = ({ command, onCloseProgressBar }) => {
  const onDragStart = (event: React.DragEvent) => {
    // Close progress bar when starting to drag a command
    onCloseProgressBar?.();
    
    const dragData = JSON.stringify({
      type: command.type,
      defaultData: command.defaultData || {}
    });
    event.dataTransfer.setData('application/reactflow', dragData);
    event.dataTransfer.effectAllowed = 'move';
  };

  return (
    <Paper
      onDragStart={onDragStart}
      draggable
      elevation={0}
      sx={{
        py: 0.75,
        px: 1,
        mb: 0.5,
        cursor: 'grab',
        display: 'flex',
        alignItems: 'center',
        lineHeight: 1.5,
        minHeight: '0 !important',
        height: 'auto',
        backgroundColor: 'transparent',
        borderRadius: 0.5,
        '&:hover': {
          backgroundColor: 'action.hover',
          transform: 'translateX(4px)',
        },
        '&:active': {
          cursor: 'grabbing',
          backgroundColor: 'action.selected',
        },
        transition: 'all 0.12s ease',
        borderLeft: `2px solid ${command.color}`,
      }}
      title={command.description}
    >
      <Typography 
        fontSize={12} 
        noWrap 
        sx={{ 
          lineHeight: 1.2, 
          color: 'text.secondary',
          '&:hover': {
            color: 'text.primary',
          },
        }}
      >
        {command.label}
      </Typography>
    </Paper>
  );
};

