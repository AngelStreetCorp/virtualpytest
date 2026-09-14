/**
 * Dynamic Parameter Form Component
 * 
 * Automatically renders form fields based on parameter type metadata.
 * Supports: STRING, NUMBER, BOOLEAN, AREA, SELECT types.
 */

import React from 'react';
import {
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Checkbox,
  FormControlLabel,
  Box,
  Typography,
  Button
} from '@mui/material';
import { ParamDefinition, ParamType, getParamDisplayType } from '../../../types/paramTypes';

interface DynamicParamFormProps {
  params: Record<string, ParamDefinition>;
  values: Record<string, any>;
  onChange: (paramName: string, value: any) => void;
  onAreaSelect?: (paramName: string) => void;
  layout?: 'vertical' | 'horizontal'; // NEW: Support horizontal layout for compact displays
}

export const DynamicParamForm: React.FC<DynamicParamFormProps> = ({
  params,
  values,
  onChange,
  onAreaSelect,
  layout = 'vertical' // Default to vertical layout
}) => {
  const isHorizontal = layout === 'horizontal';
  
  const renderParamField = (paramName: string, param: ParamDefinition) => {
    const displayType = getParamDisplayType(param);
    const value = values[paramName] ?? param.default;

    switch (displayType) {
      case 'text':
        return (
          <TextField
            fullWidth={!isHorizontal}
            label={param.description}
            placeholder={param.placeholder || ''}
            value={value || ''}
            onChange={(e) => onChange(paramName, e.target.value)}
            required={param.required}
            helperText={isHorizontal ? '' : (param.required ? 'Required' : '')}
            size="small"
            sx={isHorizontal ? {
              minWidth: '120px',
              '& .MuiInputBase-input': {
                padding: '4px 8px',
                fontSize: '0.8rem',
              },
            } : {}}
          />
        );

      case 'number':
        return (
          <TextField
            fullWidth={!isHorizontal}
            type="number"
            label={param.description}
            placeholder={param.placeholder || ''}
            value={value ?? ''}
            onChange={(e) => {
              const numValue = e.target.value === '' ? '' : Number(e.target.value);
              onChange(paramName, numValue);
            }}
            required={param.required}
            helperText={isHorizontal ? '' : (
              param.required
                ? 'Required'
                : param.min !== undefined && param.max !== undefined
                ? `Range: ${param.min} - ${param.max}`
                : ''
            )}
            inputProps={{
              min: param.min,
              max: param.max,
              step: param.type === ParamType.NUMBER && param.min !== undefined && param.min < 1 ? 0.1 : 1
            }}
            size="small"
            sx={isHorizontal ? {
              minWidth: '70px',
              '& .MuiInputBase-input': {
                padding: '4px 8px',
                fontSize: '0.8rem',
              },
            } : {}}
          />
        );

      case 'checkbox':
        return (
          <FormControlLabel
            control={
              <Checkbox
                checked={value ?? param.default ?? false}
                onChange={(e) => onChange(paramName, e.target.checked)}
              />
            }
            label={param.description}
          />
        );

      case 'select':
        return (
          <FormControl fullWidth={!isHorizontal} size="small" sx={isHorizontal ? { minWidth: '120px' } : {}}>
            <InputLabel sx={isHorizontal ? { fontSize: '0.8rem' } : {}}>{param.description}</InputLabel>
            <Select
              value={value ?? param.default ?? ''}
              onChange={(e) => onChange(paramName, e.target.value)}
              label={param.description}
              required={param.required}
              sx={isHorizontal ? {
                '& .MuiSelect-select': {
                  padding: '4px 8px',
                  fontSize: '0.8rem',
                },
              } : {}}
            >
              {param.options?.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        );

      case 'area-picker':
        return (
          <Box>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              {param.description}
              {!param.required && ' (Optional)'}
            </Typography>
            {value ? (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                  x:{value.x}, y:{value.y}, w:{value.width}, h:{value.height}
                </Typography>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => onAreaSelect?.(paramName)}
                >
                  Change Area
                </Button>
                {!param.required && (
                  <Button
                    size="small"
                    color="error"
                    onClick={() => onChange(paramName, null)}
                  >
                    Clear
                  </Button>
                )}
              </Box>
            ) : (
              <Button
                fullWidth
                variant="outlined"
                onClick={() => onAreaSelect?.(paramName)}
              >
                Select Area on Screen
              </Button>
            )}
          </Box>
        );

      default:
        return (
          <TextField
            fullWidth
            label={param.description}
            placeholder={param.placeholder || ''}
            value={value || ''}
            onChange={(e) => onChange(paramName, e.target.value)}
            required={param.required}
            size="small"
          />
        );
    }
  };

  return (
    <Box sx={{ 
      display: 'flex', 
      flexDirection: isHorizontal ? 'row' : 'column', 
      gap: isHorizontal ? 0.5 : 2,
      alignItems: isHorizontal ? 'center' : 'stretch',
      mb: isHorizontal ? 0 : 0,
      px: isHorizontal ? 0 : 0,
      mx: isHorizontal ? 0 : 0
    }}>
      {Object.entries(params).map(([paramName, param]) => (
        <Box key={paramName}>
          {renderParamField(paramName, param)}
        </Box>
      ))}
    </Box>
  );
};

