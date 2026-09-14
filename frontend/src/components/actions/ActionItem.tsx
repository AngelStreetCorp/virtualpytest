import {
  Close as CloseIcon,
  KeyboardArrowUp as KeyboardArrowUpIcon,
  KeyboardArrowDown as KeyboardArrowDownIcon,
  PlayArrow as PlayArrowIcon,
  CheckCircle as CheckCircleIcon,
  Cancel as CancelIcon,
  WarningAmber as WarningAmberIcon,
} from '@mui/icons-material';
import {
  Box,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  IconButton,
  TextField,
  Checkbox,
  Tooltip,
  CircularProgress,
} from '@mui/material';
import React from 'react';

import type { Actions } from '../../types/controller/Action_Types';
import type { Action } from '../../types/pages/Navigation_Types';
import { useDeviceData } from '../../contexts/device/DeviceDataContext';
import { useNavigationOptional } from '../../contexts/navigation/NavigationContext';
import { SearchableSelect, SearchableSelectOption } from '../common/SearchableSelect';
import { RepeatControl } from './RepeatControl';

interface ActionItemProps {
  action: Action;
  index: number;
  availableActions: Actions;
  onActionSelect: (index: number, actionId: string) => void;
  onUpdateAction: (index: number, updates: Partial<Action>) => void;
  onRemoveAction: (index: number) => void;
  onMoveUp: (index: number) => void;
  onMoveDown: (index: number) => void;
  onRun?: (index: number) => void;
  canRun?: boolean;
  isRunning?: boolean;
  runStatus?: 'success' | 'failure' | null;
  disabled?: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
}

export const ActionItem: React.FC<ActionItemProps> = ({
  action,
  index,
  availableActions,
  onActionSelect,
  onUpdateAction,
  onRemoveAction,
  onMoveUp,
  onMoveDown,
  onRun,
  canRun = false,
  isRunning = false,
  runStatus = null,
  disabled = false,
  canMoveUp,
  canMoveDown,
}) => {
  // Get device data context for model references
  const { getModelReferences, references, availableVerificationTypes, userinterfaceName: deviceUserinterfaceName } = useDeviceData();

  // Get userInterface + nodes from the navigation context. Optional: ActionItem
  // is reused in the QuickTest builder, which has no NavigationProvider — there
  // it degrades gracefully (no nodes for the RepeatControl picker; reference key
  // falls back to the DeviceData userinterface name below).
  const nav = useNavigationOptional();
  const userInterface = nav?.userInterface;
  const nodes = nav?.nodes || [];

  // Use userinterface name for reference lookup (navigation context when present,
  // else the DeviceData userinterface name — QuickTest has no NavigationProvider).
  const referenceKey = userInterface?.name || deviceUserinterfaceName || undefined;

  // Get model references using the userinterface name
  // IMPORTANT: Must depend on references state to re-render when references are added
  const modelReferences = React.useMemo(() => {
    if (!referenceKey) return {};
    return getModelReferences(referenceKey);
  }, [getModelReferences, referenceKey, references]);

  // Reference lists can hold hundreds of entries — feed them to
  // SearchableSelect (type-to-filter + Enter picks top match).
  const buildReferenceOptions = (type: 'text' | 'image'): SearchableSelectOption[] =>
    Object.entries(modelReferences)
      .filter(([_internalKey, ref]: [string, any]) => ref.type === type)
      .sort(([aKey, aRef]: [string, any], [bKey, bRef]: [string, any]) =>
        (aRef.name || aKey).toLowerCase().localeCompare((bRef.name || bKey).toLowerCase()),
      )
      .map(([internalKey, ref]: [string, any]) => ({
        value: internalKey,
        label: ref.name || internalKey,
        icon: type === 'text' ? '📝' : '🖼️',
      }));
  const textReferenceOptions = React.useMemo(
    () => buildReferenceOptions('text'),
    [modelReferences],
  );
  const imageReferenceOptions = React.useMemo(
    () => buildReferenceOptions('image'),
    [modelReferences],
  );
  const handleParamChange = (paramName: string, value: string | number) => {
    const newParams = {
      ...(action.params as any),
      [paramName]: value,
    };
    
    console.log('🔍 [ActionItem:handleParamChange] Updating param:', {
      paramName,
      value,
      oldParams: action.params,
      newParams,
      actionIndex: index,
      actionCommand: action.command
    });
    
    onUpdateAction(index, {
      params: newParams,
    });
  };

  // Helper function to safely handle params with null/undefined check
  const safeHandleParamChange = (key: string, value: any) => {
    console.log('🔍 [DEBUG] safeHandleParamChange called:', {
      key,
      value,
      currentParams: action.params,
      actionIndex: index
    });
    handleParamChange(key, value);
  };

  // Helper function to safely get parameter values
  const getParamValue = (key: string): any => {
    return (action.params as any)?.[key] || '';
  };

  const renderParameterFields = () => {
    if (!action.command) return null;

    const fields = [];
    const params = action.params as any;

    // Find the current action definition to check requiresInput
    const currentActionDef = Object.values(availableActions)
      .flat()
      .find((act) => {
        if (act.command !== action.command) return false;
        
        // If action has options (combobox), match by command only - params are user-filled
        if ((act as any).options && Array.isArray((act as any).options) && (act as any).options.length > 0) {
          return true;
        }
        
        // For press_key actions without options (predefined), match the key parameter
        if (action.command === 'press_key' && action.params && act.params) {
          return (action.params as any).key === (act.params as any).key;
        }
        
        // For other actions, just match by command
        return true;
      });

    // Common wait_time field for all actions
    fields.push(
      <TextField
        autoComplete="off"
        key="wait_time"
        label="Wait Time (ms)"
        type="number"
        size="small"
        value={params?.wait_time || 0}
        onChange={(e) => {
          const value = parseInt(e.target.value);
          handleParamChange('wait_time', isNaN(value) ? 0 : value);
        }}
        inputProps={{ min: 0, max: 10000, step: 100 }}
        sx={{
          width: 120,
          '& .MuiInputBase-input': {
            padding: '3px 6px',
            fontSize: '0.75rem',
          },
        }}
      />,
    );

    // Repeat control (Count / Until condition) for non-verification actions only.
    // Replaces the old plain "Iterations" field; keeps the row at the same height
    // (detail for "Until condition" lives in a popover, not extra rows).
    if (action.action_type !== 'verification') {
      fields.push(
        <RepeatControl
          key="repeat"
          action={action}
          index={index}
          onUpdateAction={onUpdateAction}
          nodes={nodes}
          availableVerifications={availableVerificationTypes}
          modelReferences={modelReferences}
          model={referenceKey || ''}
          disabled={disabled}
        />,
      );

      // Continue on fail checkbox for web and mobile actions only
      if (action.action_type === 'web' || action.action_type === 'remote') {
        fields.push(
          <Tooltip key="continue_on_fail" title="Continue execution even if this action fails (useful for optional actions like cookie popups)">
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Checkbox
                checked={action.continue_on_fail || false}
                onChange={(e) => {
                  onUpdateAction(index, { continue_on_fail: e.target.checked });
                }}
                size="small"
                sx={{ padding: '2px' }}
              />
              <Box sx={{ fontSize: '0.7rem', color: 'text.secondary', whiteSpace: 'nowrap' }}>
                Optional
              </Box>
            </Box>
          </Tooltip>,
        );
      }
    }

    // Action-specific parameter fields
    switch (action.command) {
      case 'press_key':
        // Show key field for both remote and web actions if they require input
        if (currentActionDef?.requiresInput) {
          const placeholder = action.action_type === 'web' 
            ? "e.g., BACK, OK, ESCAPE" 
            : "e.g., UP, DOWN, HOME, BACK";
          
          // Check if action definition has options array for dropdown
          const options = (currentActionDef as any)?.options;
          
          console.log('🔍 [ActionItem] press_key options check:', {
            command: action.command,
            action_type: action.action_type,
            currentActionDef,
            hasOptions: !!options,
            optionsLength: options?.length,
            options
          });
          
          if (options && Array.isArray(options) && options.length > 0) {
            // Render dropdown/select
            fields.push(
              <SearchableSelect
                key="key"
                label="Key"
                value={getParamValue('key') || ''}
                onChange={(key) => safeHandleParamChange('key', key)}
                options={options.map((option: string) => ({ value: option, label: option }))}
                sx={{ width: 150 }}
                inputSx={{ padding: '3px 6px', fontSize: '0.75rem' }}
              />,
            );
          } else {
            // Render text input (fallback)
            fields.push(
              <TextField
                autoComplete="off"
                key="key"
                label="Key"
                size="small"
                value={getParamValue('key') || ''}
                onChange={(e) => safeHandleParamChange('key', e.target.value)}
                placeholder={placeholder}
                sx={{
                  width: 150,
                  '& .MuiInputBase-input': {
                    padding: '3px 6px',
                    fontSize: '0.75rem',
                  },
                }}
              />,
            );
          }
        }
        break;

      case 'input_text':
        // Handle both remote and web input_text actions
        if (currentActionDef?.requiresInput) {
          if (action.action_type === 'web') {
            // Web input_text needs selector and text fields
            fields.push(
              <TextField
                autoComplete="off"
                key="selector"
                label="Selector"
                size="small"
                value={getParamValue('selector') || ''}
                onChange={(e) => safeHandleParamChange('selector', e.target.value)}
                placeholder="#username"
                sx={{
                  width: 150,
                  '& .MuiInputBase-input': {
                    padding: '3px 6px',
                    fontSize: '0.75rem',
                  },
                }}
              />,
              <TextField
                autoComplete="off"
                key="text"
                label="Text"
                size="small"
                value={getParamValue('text') || ''}
                onChange={(e) => safeHandleParamChange('text', e.target.value)}
                placeholder="Text to input"
                sx={{
                  width: 150,
                  '& .MuiInputBase-input': {
                    padding: '3px 6px',
                    fontSize: '0.75rem',
                  },
                }}
              />,
            );
          } else {
            // Remote input_text only needs text field
            fields.push(
              <TextField
                autoComplete="off"
                key="text"
                label="Text"
                size="small"
                value={getParamValue('text') || ''}
                onChange={(e) => safeHandleParamChange('text', e.target.value)}
                placeholder="Text to input"
                sx={{
                  width: 220,
                  '& .MuiInputBase-input': {
                    padding: '3px 6px',
                    fontSize: '0.75rem',
                  },
                }}
              />,
            );
          }
        }
        break;

      case 'click_element':
        // UNIFIED: Both remote and web use element_id parameter (same principle: dump UI → find element → click)
        if (currentActionDef?.requiresInput) {
          fields.push(
            <TextField
              autoComplete="off"
              key="element_id"
              label="Element Text/ID"
              size="small"
              value={getParamValue('element_id') || getParamValue('selector') || ''}  // Support legacy selector param
              onChange={(e) => safeHandleParamChange('element_id', e.target.value)}
              placeholder="e.g., Home Button, Submit"
              sx={{
                width: 220,
                '& .MuiInputBase-input': {
                  padding: '3px 6px',
                  fontSize: '0.75rem',
                },
              }}
            />,
          );
        }
        break;

      case 'find_element':
        // Web action: Find element by selector or text (returns element ID and position)
        if (currentActionDef?.requiresInput) {
          fields.push(
            <TextField
              autoComplete="off"
              key="selector"
              label="Selector or Text"
              size="small"
              value={getParamValue('selector') || ''}
              onChange={(e) => safeHandleParamChange('selector', e.target.value)}
              placeholder="e.g., TV Guide, #element-id, .class-name"
              sx={{
                width: 220,
                '& .MuiInputBase-input': {
                  padding: '3px 6px',
                  fontSize: '0.75rem',
                },
              }}
            />,
          );
        }
        break;

      case 'hover_element':
        // Web action: Hover over element to trigger rollover effects
        if (currentActionDef?.requiresInput) {
          fields.push(
            <TextField
              autoComplete="off"
              key="selector"
              label="Selector or Text"
              size="small"
              value={getParamValue('selector') || ''}
              onChange={(e) => safeHandleParamChange('selector', e.target.value)}
              placeholder="e.g., #player-controls, Play Button"
              sx={{
                width: 220,
                '& .MuiInputBase-input': {
                  padding: '3px 6px',
                  fontSize: '0.75rem',
                },
              }}
            />,
          );
        }
        break;

      case 'click_element_by_id':
        // Only show element_id field if the action requires input
        if (currentActionDef?.requiresInput) {
          fields.push(
            <TextField
              autoComplete="off"
              key="element_id"
              label="Element ID"
              size="small"
              value={getParamValue('element_id') || ''}
              onChange={(e) => safeHandleParamChange('element_id', e.target.value)}
              placeholder="e.g., 8, 15, 23"
              sx={{
                width: 220,
                alignSelf: 'flex-start',
                '& .MuiInputBase-input': {
                  padding: '3px 6px',
                  fontSize: '0.75rem',
                },
                '& .MuiInputLabel-root': {
                  transform: 'translate(14px, 4px) scale(1)',
                  '&.MuiInputLabel-shrink': {
                    transform: 'translate(14px, -9px) scale(0.75)',
                  },
                },
              }}
            />,
          );
        }
        break;

      case 'tap_coordinates':
        // Only show coordinate fields if the action requires input
        if (currentActionDef?.requiresInput) {
          fields.push(
            <Box key="coordinates" sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
              <TextField
                autoComplete="off"
                label="X"
                type="number"
                size="small"
                value={getParamValue('x') || ''}
                onChange={(e) => safeHandleParamChange('x', parseInt(e.target.value) || 0)}
                sx={{
                  width: 70,
                  '& .MuiInputBase-input': {
                    padding: '3px 6px',
                    fontSize: '0.75rem',
                  },
                }}
              />
              <TextField
                autoComplete="off"
                label="Y"
                type="number"
                size="small"
                value={getParamValue('y') || ''}
                onChange={(e) => safeHandleParamChange('y', parseInt(e.target.value) || 0)}
                sx={{
                  width: 70,
                  '& .MuiInputBase-input': {
                    padding: '3px 6px',
                    fontSize: '0.75rem',
                  },
                }}
              />
            </Box>,
          );
        }
        break;

      case 'swipe':
        fields.push(
          <TextField
            autoComplete="off"
            key="from_x"
            label="From X"
            type="number"
            size="small"
            value={getParamValue('from_x') || ''}
            onChange={(e) => safeHandleParamChange('from_x', parseInt(e.target.value) || 0)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="from_y"
            label="From Y"
            type="number"
            size="small"
            value={getParamValue('from_y') || ''}
            onChange={(e) => safeHandleParamChange('from_y', parseInt(e.target.value) || 0)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="to_x"
            label="To X"
            type="number"
            size="small"
            value={getParamValue('to_x') || ''}
            onChange={(e) => safeHandleParamChange('to_x', parseInt(e.target.value) || 0)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="to_y"
            label="To Y"
            type="number"
            size="small"
            value={getParamValue('to_y') || ''}
            onChange={(e) => safeHandleParamChange('to_y', parseInt(e.target.value) || 0)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="duration"
            label="Duration (ms)"
            type="number"
            size="small"
            value={getParamValue('duration') || 300}
            onChange={(e) => safeHandleParamChange('duration', parseInt(e.target.value) || 300)}
            inputProps={{ min: 100, max: 2000, step: 100 }}
            sx={{
              width: 100,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
        );
        break;

      case 'swipe_up':
        fields.push(
          <TextField
            autoComplete="off"
            key="from_x"
            label="From X"
            type="number"
            size="small"
            value={getParamValue('from_x') || 500}
            onChange={(e) => safeHandleParamChange('from_x', parseInt(e.target.value) || 500)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="from_y"
            label="From Y"
            type="number"
            size="small"
            value={getParamValue('from_y') || 1500}
            onChange={(e) => safeHandleParamChange('from_y', parseInt(e.target.value) || 1500)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="to_x"
            label="To X"
            type="number"
            size="small"
            value={getParamValue('to_x') || 500}
            onChange={(e) => safeHandleParamChange('to_x', parseInt(e.target.value) || 500)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="to_y"
            label="To Y"
            type="number"
            size="small"
            value={getParamValue('to_y') || 500}
            onChange={(e) => safeHandleParamChange('to_y', parseInt(e.target.value) || 500)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="duration"
            label="Duration (ms)"
            type="number"
            size="small"
            value={getParamValue('duration') || 300}
            onChange={(e) => safeHandleParamChange('duration', parseInt(e.target.value) || 300)}
            inputProps={{ min: 100, max: 2000, step: 100 }}
            sx={{
              width: 100,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
        );
        break;

      case 'swipe_down':
        fields.push(
          <TextField
            autoComplete="off"
            key="from_x"
            label="From X"
            type="number"
            size="small"
            value={getParamValue('from_x') || 500}
            onChange={(e) => safeHandleParamChange('from_x', parseInt(e.target.value) || 500)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="from_y"
            label="From Y"
            type="number"
            size="small"
            value={getParamValue('from_y') || 500}
            onChange={(e) => safeHandleParamChange('from_y', parseInt(e.target.value) || 500)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="to_x"
            label="To X"
            type="number"
            size="small"
            value={getParamValue('to_x') || 500}
            onChange={(e) => safeHandleParamChange('to_x', parseInt(e.target.value) || 500)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="to_y"
            label="To Y"
            type="number"
            size="small"
            value={getParamValue('to_y') || 1500}
            onChange={(e) => safeHandleParamChange('to_y', parseInt(e.target.value) || 1500)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="duration"
            label="Duration (ms)"
            type="number"
            size="small"
            value={getParamValue('duration') || 300}
            onChange={(e) => safeHandleParamChange('duration', parseInt(e.target.value) || 300)}
            inputProps={{ min: 100, max: 2000, step: 100 }}
            sx={{
              width: 100,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
        );
        break;

      case 'swipe_left':
        fields.push(
          <TextField
            autoComplete="off"
            key="from_x"
            label="From X"
            type="number"
            size="small"
            value={getParamValue('from_x') || 800}
            onChange={(e) => safeHandleParamChange('from_x', parseInt(e.target.value) || 800)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="from_y"
            label="From Y"
            type="number"
            size="small"
            value={getParamValue('from_y') || 1000}
            onChange={(e) => safeHandleParamChange('from_y', parseInt(e.target.value) || 1000)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="to_x"
            label="To X"
            type="number"
            size="small"
            value={getParamValue('to_x') || 200}
            onChange={(e) => safeHandleParamChange('to_x', parseInt(e.target.value) || 200)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="to_y"
            label="To Y"
            type="number"
            size="small"
            value={getParamValue('to_y') || 1000}
            onChange={(e) => safeHandleParamChange('to_y', parseInt(e.target.value) || 1000)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="duration"
            label="Duration (ms)"
            type="number"
            size="small"
            value={getParamValue('duration') || 300}
            onChange={(e) => safeHandleParamChange('duration', parseInt(e.target.value) || 300)}
            inputProps={{ min: 100, max: 2000, step: 100 }}
            sx={{
              width: 100,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
        );
        break;

      case 'swipe_right':
        fields.push(
          <TextField
            autoComplete="off"
            key="from_x"
            label="From X"
            type="number"
            size="small"
            value={getParamValue('from_x') || 200}
            onChange={(e) => safeHandleParamChange('from_x', parseInt(e.target.value) || 200)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="from_y"
            label="From Y"
            type="number"
            size="small"
            value={getParamValue('from_y') || 1000}
            onChange={(e) => safeHandleParamChange('from_y', parseInt(e.target.value) || 1000)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="to_x"
            label="To X"
            type="number"
            size="small"
            value={getParamValue('to_x') || 800}
            onChange={(e) => safeHandleParamChange('to_x', parseInt(e.target.value) || 800)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="to_y"
            label="To Y"
            type="number"
            size="small"
            value={getParamValue('to_y') || 1000}
            onChange={(e) => safeHandleParamChange('to_y', parseInt(e.target.value) || 1000)}
            sx={{
              width: 70,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="duration"
            label="Duration (ms)"
            type="number"
            size="small"
            value={getParamValue('duration') || 300}
            onChange={(e) => safeHandleParamChange('duration', parseInt(e.target.value) || 300)}
            inputProps={{ min: 100, max: 2000, step: 100 }}
            sx={{
              width: 100,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
        );
        break;

      case 'launch_app':
      case 'close_app':
        // Only show package field if the action requires input
        if (currentActionDef?.requiresInput) {
          fields.push(
            <TextField
              autoComplete="off"
              key="package"
              label="Package Name"
              size="small"
              value={getParamValue('package') || ''}
              onChange={(e) => safeHandleParamChange('package', e.target.value)}
              placeholder="e.g., com.example.app"
              sx={{
                width: 220,
                '& .MuiInputBase-input': {
                  padding: '3px 6px',
                  fontSize: '0.75rem',
                },
              }}
            />,
          );
        }
        break;

      case 'wait':
        fields.push(
          <TextField
            autoComplete="off"
            key="duration"
            label="Duration (s)"
            type="number"
            size="small"
            value={getParamValue('duration') || 1}
            onChange={(e) => safeHandleParamChange('duration', parseFloat(e.target.value) || 1)}
            inputProps={{ min: 0.1, max: 60, step: 0.1 }}
            sx={{
              width: 100,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
        );
        break;

      case 'scroll':
        // Scroll actions have hardcoded direction and amount in backend params
        // No user input required - scroll_up/down/left/right are predefined actions
        break;

      case 'auto_return':
        fields.push(
          <TextField
            autoComplete="off"
            key="timer"
            label="Timer (ms)"
            type="number"
            size="small"
            value={getParamValue('timer') || 2000}
            onChange={(e) => safeHandleParamChange('timer', parseInt(e.target.value) || 2000)}
            inputProps={{ min: 0, max: 30000, step: 100 }}
            sx={{
              width: 120,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
          <TextField
            autoComplete="off"
            key="target_node_id"
            label="Target Node ID"
            size="small"
            value={getParamValue('target_node_id') || ''}
            onChange={(e) => safeHandleParamChange('target_node_id', e.target.value)}
            placeholder="Node to return to"
            sx={{
              width: 180,
              '& .MuiInputBase-input': {
                padding: '3px 6px',
                fontSize: '0.75rem',
              },
            }}
          />,
        );
        break;

      case 'waitForTextToAppear':
      case 'waitForTextToDisappear':
        // Debug verification action properties
        console.log('[ActionItem] Text verification action debug:', {
          command: action.command,
          action_type: action.action_type,
          verification_type: action.verification_type,
          full_action: action
        });
        
        // Check if this is a verification action with text type
        if (action.action_type === 'verification' && action.verification_type === 'text') {
          console.log('[ActionItem] Rendering text verification UI');
          // Text reference selection (same as VerificationItem.tsx for text)
          fields.push(
            <SearchableSelect
              key="text_reference"
              label="Text Reference"
              value={action.params?.reference_name || ''}
              onChange={(internalKey) => {
                const selectedRef = modelReferences[internalKey];
                if (selectedRef && selectedRef.type === 'text') {
                  // Update both parameters in a single call to avoid state race condition
                  onUpdateAction(index, {
                    params: {
                      ...(action.params as any),
                      reference_name: internalKey,
                      text: selectedRef.text || '',
                    },
                  });
                }
              }}
              options={textReferenceOptions}
              emptyText="No text references available"
              sx={{ width: 250 }}
            />,
          );
        } else {
          console.log('[ActionItem] NOT rendering text verification UI - check failed');
        }
        break;

      case 'waitForImageToAppear':
      case 'waitForImageToDisappear':
        // Debug verification action properties
        console.log('[ActionItem] Image verification action debug:', {
          command: action.command,
          action_type: action.action_type,
          verification_type: action.verification_type,
          full_action: action
        });
        
        // Check if this is a verification action with image type
        if (action.action_type === 'verification' && action.verification_type === 'image') {
          console.log('[ActionItem] Rendering image verification UI');
          // Image reference selection (same as VerificationItem.tsx for image)
          fields.push(
            <SearchableSelect
              key="image_reference"
              label="Image Reference"
              value={action.params?.reference_name || ''}
              onChange={(internalKey) => {
                const selectedRef = modelReferences[internalKey];
                if (selectedRef && selectedRef.type === 'image') {
                  // Update both parameters in a single call to avoid state race condition
                  onUpdateAction(index, {
                    params: {
                      ...(action.params as any),
                      reference_name: internalKey,
                      image_path: selectedRef.name || internalKey,
                    },
                  });
                }
              }}
              options={imageReferenceOptions}
              emptyText="No image references available"
              sx={{ width: 250 }}
            />,
          );
        } else {
          console.log('[ActionItem] NOT rendering image verification UI - check failed');
        }
        break;

      case 'waitForImageToAppearThenDisappear':
        // Debug action properties
        console.log('[ActionItem] Image appear-then-disappear action debug:', {
          command: action.command,
          action_type: action.action_type,
          verification_type: action.verification_type,
          full_action: action
        });
        
        // Check if this is a verification action with image type
        if (action.action_type === 'verification' && action.verification_type === 'image') {
          console.log('[ActionItem] Rendering image appear-then-disappear UI');
          // Image reference selection (same as other image verifications)
          fields.push(
            <SearchableSelect
              key="image_reference"
              label="Image Reference"
              value={action.params?.reference_name || ''}
              onChange={(internalKey) => {
                const selectedRef = modelReferences[internalKey];
                if (selectedRef && selectedRef.type === 'image') {
                  // Update both parameters in a single call to avoid state race condition
                  onUpdateAction(index, {
                    params: {
                      ...(action.params as any),
                      reference_name: internalKey,
                      image_path: selectedRef.name || internalKey,
                    },
                  });
                }
              }}
              options={imageReferenceOptions}
              emptyText="No image references available"
              sx={{ width: 250 }}
            />,
          );
        } else {
          console.log('[ActionItem] NOT rendering image appear-then-disappear UI - check failed');
        }
        break;

      case 'waitForElementToAppear':
      case 'waitForElementToDisappear':
        // Debug verification action properties
        console.log('[ActionItem] Web element verification action debug:', {
          command: action.command,
          action_type: action.action_type,
          verification_type: action.verification_type,
          full_action: action
        });
        
        // Check if this is a verification action with appium type (web automation)
        if (action.action_type === 'verification' && action.verification_type === 'appium') {
          console.log('[ActionItem] Rendering web element verification UI (text input like ADB)');
          // Simple text input for search term (like ADB verifications - consistent parameter name)
          fields.push(
            <TextField
              autoComplete="off"
              key="search_term"
              label="Element Text/ID"
              size="small"
              value={getParamValue('search_term') || ''}
              onChange={(e) => safeHandleParamChange('search_term', e.target.value)}
              placeholder="e.g., Submit, Login Button, #element-id"
              sx={{
                width: 250,
                '& .MuiInputBase-input': {
                  padding: '3px 6px',
                  fontSize: '0.75rem',
                },
              }}
            />,
          );
        } else {
          console.log('[ActionItem] NOT rendering web element verification UI - check failed');
        }
        break;

      // Desktop actions (PyAutoGUI and Bash)
      case 'execute_pyautogui_click':
      case 'execute_pyautogui_rightclick':
      case 'execute_pyautogui_doubleclick':
      case 'execute_pyautogui_move':
        if (currentActionDef?.requiresInput) {
          fields.push(
            <Box key="coordinates" sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
              <TextField
                autoComplete="off"
                label="X"
                type="number"
                size="small"
                value={getParamValue('x') || ''}
                onChange={(e) => safeHandleParamChange('x', parseInt(e.target.value) || 0)}
                sx={{
                  width: 70,
                  '& .MuiInputBase-input': {
                    padding: '3px 6px',
                    fontSize: '0.75rem',
                  },
                }}
              />
              <TextField
                autoComplete="off"
                label="Y"
                type="number"
                size="small"
                value={getParamValue('y') || ''}
                onChange={(e) => safeHandleParamChange('y', parseInt(e.target.value) || 0)}
                sx={{
                  width: 70,
                  '& .MuiInputBase-input': {
                    padding: '3px 6px',
                    fontSize: '0.75rem',
                  },
                }}
              />
            </Box>,
          );
        }
        break;

      case 'execute_pyautogui_keypress':
        if (currentActionDef?.requiresInput) {
          // Check if action definition has options array for dropdown
          const options = (currentActionDef as any)?.options;
          
          if (options && Array.isArray(options) && options.length > 0) {
            // Render dropdown/select
            fields.push(
              <SearchableSelect
                key="key"
                label="Key"
                value={getParamValue('key') || ''}
                onChange={(key) => safeHandleParamChange('key', key)}
                options={options.map((option: string) => ({ value: option, label: option }))}
                sx={{ width: 150 }}
                inputSx={{ padding: '3px 6px', fontSize: '0.75rem' }}
              />,
            );
          } else {
            // Render text input (fallback)
            fields.push(
              <TextField
                autoComplete="off"
                key="key"
                label="Key"
                size="small"
                value={getParamValue('key') || ''}
                onChange={(e) => safeHandleParamChange('key', e.target.value)}
                placeholder="enter, space, tab, ctrl"
                sx={{
                  width: 150,
                  '& .MuiInputBase-input': {
                    padding: '3px 6px',
                    fontSize: '0.75rem',
                  },
                }}
              />
            );
          }
        }
        break;

      case 'execute_pyautogui_type':
        if (currentActionDef?.requiresInput) {
          fields.push(
            <TextField
              autoComplete="off"
              key="text"
              label="Text"
              size="small"
              value={getParamValue('text') || ''}
              onChange={(e) => safeHandleParamChange('text', e.target.value)}
              placeholder="Text to type"
              sx={{
                width: 200,
                '& .MuiInputBase-input': {
                  padding: '3px 6px',
                  fontSize: '0.75rem',
                },
              }}
            />,
          );
        }
        break;

      case 'execute_pyautogui_scroll':
        if (currentActionDef?.requiresInput) {
          fields.push(
            <TextField
              autoComplete="off"
              key="clicks"
              label="Scroll Clicks"
              type="number"
              size="small"
              value={getParamValue('clicks') || 1}
              onChange={(e) => safeHandleParamChange('clicks', parseInt(e.target.value) || 1)}
              placeholder="Positive=up, Negative=down"
              sx={{
                width: 120,
                '& .MuiInputBase-input': {
                  padding: '3px 6px',
                  fontSize: '0.75rem',
                },
              }}
            />,
          );
        }
        break;

      case 'execute_pyautogui_locate':
      case 'execute_pyautogui_locate_and_click':
        if (currentActionDef?.requiresInput) {
          fields.push(
            <TextField
              autoComplete="off"
              key="image_path"
              label="Image Path"
              size="small"
              value={getParamValue('image_path') || ''}
              onChange={(e) => safeHandleParamChange('image_path', e.target.value)}
              placeholder="/path/to/image.png"
              sx={{
                width: 250,
                '& .MuiInputBase-input': {
                  padding: '3px 6px',
                  fontSize: '0.75rem',
                },
              }}
            />,
          );
        }
        break;

      case 'execute_pyautogui_launch':
        if (currentActionDef?.requiresInput) {
          fields.push(
            <TextField
              autoComplete="off"
              key="app_name"
              label="App Name"
              size="small"
              value={getParamValue('app_name') || ''}
              onChange={(e) => safeHandleParamChange('app_name', e.target.value)}
              placeholder="notepad, calc, firefox"
              sx={{
                width: 180,
                '& .MuiInputBase-input': {
                  padding: '3px 6px',
                  fontSize: '0.75rem',
                },
              }}
            />,
          );
        }
        break;

      case 'execute_bash_command':
        if (currentActionDef?.requiresInput) {
          fields.push(
            <TextField
              autoComplete="off"
              key="command"
              label="Bash Command"
              size="small"
              value={getParamValue('command') || getParamValue('bash_command') || ''}
              onChange={(e) => safeHandleParamChange('command', e.target.value)}
              placeholder="ls -la, ps aux, echo hello"
              sx={{
                width: 300,
                '& .MuiInputBase-input': {
                  padding: '3px 6px',
                  fontSize: '0.75rem',
                },
              }}
            />,
          );
        }
        break;

      // Web actions (Playwright)
      case 'navigate_to_url':
        if (currentActionDef?.requiresInput) {
          fields.push(
            <TextField
              autoComplete="off"
              key="url"
              label="URL"
              size="small"
              value={getParamValue('url') || ''}
              onChange={(e) => safeHandleParamChange('url', e.target.value)}
              placeholder="https://google.com"
              sx={{
                width: 250,
                '& .MuiInputBase-input': {
                  padding: '3px 6px',
                  fontSize: '0.75rem',
                },
              }}
            />,
          );
        }
        break;



      case 'tap_x_y':
        // Handle web tap_x_y
        if (action.action_type === 'web' && currentActionDef?.requiresInput) {
          fields.push(
            <Box key="coordinates" sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
              <TextField
                autoComplete="off"
                label="X"
                type="number"
                size="small"
                value={getParamValue('x') || ''}
                onChange={(e) => safeHandleParamChange('x', parseInt(e.target.value) || 0)}
                sx={{
                  width: 70,
                  '& .MuiInputBase-input': {
                    padding: '3px 6px',
                    fontSize: '0.75rem',
                  },
                }}
              />
              <TextField
                autoComplete="off"
                label="Y"
                type="number"
                size="small"
                value={getParamValue('y') || ''}
                onChange={(e) => safeHandleParamChange('y', parseInt(e.target.value) || 0)}
                sx={{
                  width: 70,
                  '& .MuiInputBase-input': {
                    padding: '3px 6px',
                    fontSize: '0.75rem',
                  },
                }}
              />
            </Box>,
          );
        }
        break;

      case 'execute_javascript':
        if (currentActionDef?.requiresInput) {
          fields.push(
            <TextField
              autoComplete="off"
              key="script"
              label="JavaScript"
              size="small"
              value={getParamValue('script') || ''}
              onChange={(e) => safeHandleParamChange('script', e.target.value)}
              placeholder="alert('Hello World')"
              sx={{
                width: 300,
                '& .MuiInputBase-input': {
                  padding: '3px 6px',
                  fontSize: '0.75rem',
                },
              }}
            />,
          );
        }
        break;

      case 'browser_use_task':
        if (currentActionDef?.requiresInput) {
          fields.push(
            <TextField
              autoComplete="off"
              key="task"
              label="Task Description"
              size="small"
              value={getParamValue('task') || ''}
              onChange={(e) => safeHandleParamChange('task', e.target.value)}
              placeholder="Search for Python tutorials"
              sx={{
                width: 300,
                '& .MuiInputBase-input': {
                  padding: '3px 6px',
                  fontSize: '0.75rem',
                },
              }}
            />,
          );
        }
        break;

    }

    // Organize fields based on count
    if (fields.length <= 3) {
      // ≤3 parameters: show in one line
      return (
        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center', flexWrap: 'nowrap' }}>
          {fields}
        </Box>
      );
    } else {
      // >3 parameters: show 3 per line
      const rows = [];
      for (let i = 0; i < fields.length; i += 3) {
        const rowFields = fields.slice(i, i + 3);
        rows.push(
          <Box key={i} sx={{ display: 'flex', gap: 0.5, alignItems: 'center', mb: 0.5 }}>
            {rowFields}
          </Box>,
        );
      }
      return <Box>{rows}</Box>;
    }
  };

  return (
    <Box
      sx={{
        mb: 0.5,
        px: 0.5,
        py: 0.5,
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 1,
      }}
    >
      {/* Line 1: Action command dropdown */}
      <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center', mb: 0.5 }}>
        <FormControl size="small" sx={{ flex: 1, minWidth: 200, maxWidth: 300 }}>
          <InputLabel>Action</InputLabel>
          {(() => {
            const matchedAction = action.command
              ? Object.values(availableActions)
                  .flat()
                  .find((act) => {
                    if (act.command !== action.command) return false;

                    // If action has options (combobox), match by command only - params are user-filled
                    if ((act as any).options && Array.isArray((act as any).options) && (act as any).options.length > 0) {
                      return true;
                    }

                    // For press_key actions without options (predefined), match the key parameter
                    if (action.command === 'press_key' && action.params && act.params) {
                      return (action.params as any).key === (act.params as any).key;
                    }

                    // For scroll actions (predefined), match the direction parameter
                    if (action.command === 'scroll' && action.params && act.params) {
                      return (action.params as any).direction === (act.params as any).direction;
                    }

                    // For other actions, just match by command
                    return true;
                  })
              : undefined;

            // When the saved command isn't exposed by the current device (e.g. a
            // power_on failure action authored on a host with a Tapo plug, then
            // viewed on a host without one), keep the value visible instead of
            // collapsing the dropdown to empty. We synthesize an id so MUI has a
            // matching MenuItem to anchor on, render the saved command as the
            // visible label, and let the user pick a real action to overwrite it.
            const unmatchedId = action.command ? `__saved__:${action.command}` : '';
            const currentValue = matchedAction?.id || unmatchedId;
            const isUnmatched = !!action.command && !matchedAction;
            const formatSavedCommand = (cmd: string) => cmd.replace(/_/g, ' ').trim();

            return (
          <Select
            value={currentValue}
            onChange={(e) => onActionSelect(index, e.target.value)}
            label="Action"
            size="small"
            disabled={disabled}
            sx={{
              '& .MuiSelect-select': {
                fontSize: '0.8rem',
                py: 0.5,
              },
              '& .MuiInputBase-root': {
                minHeight: '24px',
              },
            }}
            renderValue={(selected) => {
              // Find the selected action and return its label
              const selectedAction = Object.values(availableActions)
                .flat()
                .find((act) => act.id === selected);
              if (selectedAction) {
                return selectedAction.label;
              }
              if (isUnmatched && action.command) {
                return formatSavedCommand(action.command);
              }
              return selected;
            }}
          >
            {isUnmatched && (
              <MenuItem
                key={unmatchedId}
                value={unmatchedId}
                sx={{ display: 'none' }}
              >
                {formatSavedCommand(action.command!)}
              </MenuItem>
            )}
            {Object.entries(availableActions).map(([category, actions]) => {
              // Ensure actions is an array
              if (!Array.isArray(actions)) {
                console.warn(
                  `[@component:ActionItem] Invalid actions for category ${category}:`,
                  actions,
                );
                return null;
              }

              return [
                <MenuItem
                  key={`header-${category}`}
                  disabled
                  sx={{ fontWeight: 'bold', fontSize: '0.65rem', minHeight: '20px' }}
                >
                  {category.replace(/_/g, ' ').toUpperCase()}
                </MenuItem>,
                ...actions.map((actionDef) => (
                  <MenuItem
                    key={actionDef.id}
                    value={actionDef.id}
                    sx={{ pl: 3, fontSize: '0.7rem', minHeight: '20px' }}
                  >
                    {actionDef.label}
                  </MenuItem>
                )),
              ];
            })}
          </Select>
            );
          })()}
        </FormControl>

        {(() => {
          // Warn the user when the saved command isn't exposed by the current
          // device's controllers. Same matching rules as the Select above.
          if (!action.command) return null;
          const matched = Object.values(availableActions)
            .flat()
            .some((act) => act.command === action.command);
          if (matched) return null;
          return (
            <Tooltip title="Device does not support this command">
              <WarningAmberIcon
                fontSize="small"
                sx={{ color: 'warning.main', flexShrink: 0 }}
              />
            </Tooltip>
          );
        })()}

        {/* Run single action button */}
        {onRun && (
          <Tooltip title="Run this action">
            <span>
              <IconButton
                size="small"
                onClick={() => onRun(index)}
                disabled={!canRun || disabled}
                sx={{ p: 0.5, minWidth: 24, width: 24, height: 24, ml: 0.25 }}
              >
                {isRunning ? (
                  <CircularProgress size={14} />
                ) : runStatus === 'success' ? (
                  <CheckCircleIcon sx={{ fontSize: '1rem', color: 'success.main' }} />
                ) : runStatus === 'failure' ? (
                  <CancelIcon sx={{ fontSize: '1rem', color: 'error.main' }} />
                ) : (
                  <PlayArrowIcon sx={{ fontSize: '1rem' }} />
                )}
              </IconButton>
            </span>
          </Tooltip>
        )}

        {/* Move buttons */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
          <IconButton
            size="small"
            onClick={() => onMoveUp(index)}
            disabled={!canMoveUp || disabled}
            sx={{ p: 0.5, minWidth: 24, width: 24, height: 20 }}
          >
            <KeyboardArrowUpIcon sx={{ fontSize: '1rem' }} />
          </IconButton>
          <IconButton
            size="small"
            onClick={() => onMoveDown(index)}
            disabled={!canMoveDown || disabled}
            sx={{ p: 0.5, minWidth: 24, width: 24, height: 20 }}
          >
            <KeyboardArrowDownIcon sx={{ fontSize: '1rem' }} />
          </IconButton>
        </Box>

        {/* Remove button */}
        <IconButton
          size="small"
          onClick={() => onRemoveAction(index)}
          disabled={disabled}
          sx={{ p: 0.5, minWidth: 24, width: 24, height: 24, ml: 0.5 }}
        >
          <CloseIcon sx={{ fontSize: '1rem' }} />
        </IconButton>
      </Box>

      {/* Parameter fields section - organized by count */}
      {action.command && renderParameterFields()}
    </Box>
  );
};
