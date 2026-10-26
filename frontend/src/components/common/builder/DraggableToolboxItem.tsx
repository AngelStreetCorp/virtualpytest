/**
 * Draggable Toolbox Item Component
 * 
 * Shared draggable item for builder toolboxes.
 * Used for testcases, scripts, and other drag-and-drop items.
 * Clean, minimal design - color-coded left accent indicates category.
 */

import React from 'react';
import { Box, Typography, SvgIconProps } from '@mui/material';
import { TYPOGRAPHY } from '../../../constants/typography';

interface DraggableToolboxItemProps {
  /** Item label */
  label: string;
  /** Optional subtitle (e.g., folder path) */
  subtitle?: string;
  /** Optional icon component (omit for cleaner look) */
  icon?: React.ReactElement<SvgIconProps>;
  /** Accent color for left border and hover */
  accentColor: string;
  /** Drag start handler */
  onDragStart: (e: React.DragEvent) => void;
  /** Optional control at the right edge (e.g. the favorites star). */
  trailing?: React.ReactNode;
}

export const DraggableToolboxItem: React.FC<DraggableToolboxItemProps> = ({
  label,
  subtitle,
  icon,
  accentColor,
  onDragStart,
  trailing,
}) => {
  return (
    <Box
      draggable
      onDragStart={onDragStart}
      sx={{
        py: 0.75,
        px: 1,
        backgroundColor: 'transparent',
        borderLeft: `2px solid ${accentColor}`,
        borderRadius: 0.5,
        cursor: 'grab',
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        transition: 'all 0.12s ease',
        '&:hover': {
          backgroundColor: 'action.hover',
          transform: 'translateX(4px)',
        },
        '&:active': {
          cursor: 'grabbing',
        },
      }}
    >
      {icon && React.cloneElement(icon, { sx: { color: accentColor, fontSize: TYPOGRAPHY.navbarItem.size } })}
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography 
          fontSize="0.75rem"
          sx={{ 
            lineHeight: 1.2, 
            color: 'text.secondary',
            '&:hover': { color: 'text.primary' },
          }} 
          noWrap
        >
          {label}
        </Typography>
        {subtitle && (
          <Typography 
            fontSize="0.625rem"
            color="text.disabled" 
            noWrap
          >
            {subtitle}
          </Typography>
        )}
      </Box>
      {trailing}
    </Box>
  );
};

