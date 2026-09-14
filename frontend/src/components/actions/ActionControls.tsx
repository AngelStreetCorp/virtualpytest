import { Box, TextField } from '@mui/material';
import React from 'react';

import type { Action } from '../../types/controller/Action_Types';

interface ActionControlsProps {
  action: Action;
  index: number;
  onUpdateAction: (index: number, updates: Partial<Action>) => void;
}

export const ActionControls: React.FC<ActionControlsProps> = ({
  action,
  index,
  onUpdateAction,
}) => {
  // Don't show controls if no action is selected
  if (!action.command) {
    return null;
  }

  const handleInputValueChange = (value: string) => {
    const updatedParams: any = { ...action.params };

    // Update params based on action command
    if (action.command === 'launch_app') {
      updatedParams.package = value;
    } else if (action.command === 'input_text') {
      updatedParams.text = value;
    } else if (action.command === 'click_element') {
      updatedParams.element_id = value;
    } else if (action.command === 'coordinate_tap' || action.command === 'tap_coordinates') {
      const coords = value.split(',').map((coord) => parseInt(coord.trim()));
      if (coords.length === 2 && !isNaN(coords[0]) && !isNaN(coords[1])) {
        updatedParams.x = coords[0];
        updatedParams.y = coords[1];
        updatedParams.coordinates = value; // Keep original format too
      }
    } else if (action.command === 'press_key') {
      updatedParams.key = value;
    }

    onUpdateAction(index, {
      inputValue: value,
      params: updatedParams,
    } as Partial<Action>);
  };

  // Only show input field if action requires input
  const actionWithInput = action as Action & { requiresInput?: boolean };
  if (!actionWithInput.requiresInput) {
    return null;
  }

  const getInputValue = (action: Action): string => {
    // First check if action has an inputValue already set
    const actionWithInput = action as Action & { inputValue?: string };
    if (actionWithInput.inputValue !== undefined) {
      return actionWithInput.inputValue;
    }

    // Safe property access with type checking
    const getRemoteParam = (key: keyof import('../../types/controller/Action_Types').RemoteActionParams): string => {
      if (action.action_type === 'remote' && action.params) {
        const params = action.params as import('../../types/controller/Action_Types').RemoteActionParams;
        return String(params[key] || '');
      }
      return '';
    };

    // Otherwise, extract from params based on action command (for loaded actions)
    if (action.command === 'launch_app') {
      return getRemoteParam('package');
    } else if (action.command === 'input_text') {
      return getRemoteParam('text');
    } else if (action.command === 'click_element') {
      return getRemoteParam('element_id');
    } else if (action.command === 'coordinate_tap' || action.command === 'tap_coordinates') {
      if (action.action_type === 'remote' && action.params) {
        const params = action.params as import('../../types/controller/Action_Types').RemoteActionParams;
        if (params.coordinates) {
          return params.coordinates;
        } else if (params.x !== undefined && params.y !== undefined) {
          return `${params.x},${params.y}`;
        }
      }
      return '';
    } else if (action.command === 'press_key') {
      return getRemoteParam('key');
    }

    return '';
  };

  const getPlaceholder = () => {
    switch (action.command) {
      case 'launch_app':
        return 'com.example.app';
      case 'input_text':
        return 'Enter text';
      case 'click_element':
        return 'Element text (e.g., "OK|Accept")';
      case 'coordinate_tap':
      case 'tap_coordinates':
        return 'x,y (e.g., "100,200")';
      case 'press_key':
        return 'Key name (e.g., "UP", "DOWN", "ENTER")';
      default:
        return 'Enter value';
    }
  };

  return (
    <Box sx={{ mb: 0.5 }}>
      <TextField
        size="small"
        value={getInputValue(action)}
        onChange={(e) => handleInputValueChange(e.target.value)}
        placeholder={getPlaceholder()}
        autoComplete="off"
        fullWidth
        sx={{
          '& .MuiInputBase-input': {
            fontSize: '0.8rem',
            py: 0.5,
          },
        }}
      />
    </Box>
  );
};
