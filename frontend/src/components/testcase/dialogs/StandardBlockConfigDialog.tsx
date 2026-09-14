/**
 * StandardBlockConfigDialog
 * 
 * Universal configuration dialog for standard blocks (evaluate_condition, custom_code, etc.)
 * Supports dependent dropdowns where one field's choices depend on another field's value
 */

import React, { useState, useEffect, useMemo } from 'react';
import {
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Box,
  Typography,
  Chip,
  IconButton,
  Menu,
  ListSubheader,
  InputAdornment,
} from '@mui/material';
import AddCircleOutlineIcon from '@mui/icons-material/AddCircleOutline';

import { StyledDialog } from '../../common/StyledDialog';

// Available variable for insertion
interface AvailableVariable {
  name: string;
  type: string;
  source: 'input' | 'output' | 'variable' | 'block_output';
  blockId?: string; // For block outputs
  value?: any; // Current/default value to display
}

interface ParamDef {
  type: string;
  required?: boolean;
  default?: any;
  description?: string;
  choices?: Array<{ label: string; value: string }>;
  depends_on?: string;  // Field that this field depends on
  choices_map?: Record<string, Array<{ label: string; value: string }>>;  // Choices grouped by parent value
  placeholder?: string;
  min?: number;
  max?: number;
}

interface StandardBlockConfigDialogProps {
  open: boolean;
  blockCommand: string;  // e.g., 'evaluate_condition'
  blockLabel: string;    // e.g., 'Evaluate Condition'
  params: Record<string, ParamDef>;  // Parameter definitions from get_block_info()
  initialData?: Record<string, any>;  // Initial values
  onSave: (data: Record<string, any>) => void;
  onCancel: () => void;
  availableVariables?: AvailableVariable[];  // NEW: Variables that can be inserted
}

export const StandardBlockConfigDialog: React.FC<StandardBlockConfigDialogProps> = ({
  open,
  blockCommand,
  blockLabel,
  params,
  initialData = {},
  onSave,
  onCancel,
  availableVariables = [],
}) => {
  // Initialize form data from initial values or defaults
  const [formData, setFormData] = useState<Record<string, any>>(() => {
    const initial: Record<string, any> = {};
    Object.entries(params).forEach(([key, paramDef]) => {
      initial[key] = initialData[key] !== undefined 
        ? initialData[key] 
        : (paramDef.default !== undefined ? paramDef.default : '');
    });
    return initial;
  });
  
  // Variable menu state
  const [variableMenuAnchor, setVariableMenuAnchor] = useState<HTMLElement | null>(null);
  const [currentField, setCurrentField] = useState<string | null>(null);
  
  // Filter variables by type for evaluate_condition - memoized to update when operand_type changes
  const getFilteredVariables = useMemo(() => {
    // Type compatibility check - strict matching for evaluate_condition
    const isTypeCompatible = (varType: string, expectedType: string): boolean => {
      if (!expectedType || expectedType === 'any') return true;
      if (varType === 'any') return true;
      
      // Type mapping: backend uses 'str', frontend inputs use 'string'
      const normalizeType = (type: string) => {
        if (type === 'string') return 'str';
        if (type === 'str') return 'str';
        return type;
      };
      
      // Strict matching: only show exact type matches
      return normalizeType(varType) === normalizeType(expectedType);
    };
    
    return (paramName: string): AvailableVariable[] => {
      if (blockCommand !== 'evaluate_condition') return availableVariables;
      if (paramName !== 'left_operand' && paramName !== 'right_operand') return availableVariables;
      
      const operandType = formData['operand_type'] || 'int';
      return availableVariables.filter(v => isTypeCompatible(v.type, operandType));
    };
  }, [blockCommand, availableVariables, formData]);
  
  // Group filtered variables by source
  const groupVariablesBySource = (variables: AvailableVariable[]) => {
    const groups = {
      inputs: variables.filter(v => v.source === 'input'),
      outputs: variables.filter(v => v.source === 'output'),
      variables: variables.filter(v => v.source === 'variable'),
      blockOutputs: variables.filter(v => v.source === 'block_output'),
    };
    return groups;
  };
  
  const handleOpenVariableMenu = (event: React.MouseEvent<HTMLElement>, paramName: string) => {
    setVariableMenuAnchor(event.currentTarget);
    setCurrentField(paramName);
  };
  
  const handleCloseVariableMenu = () => {
    setVariableMenuAnchor(null);
    setCurrentField(null);
  };
  
  const handleSelectVariable = (variableName: string) => {
    if (currentField) {
      // Just insert the variable reference
      handleChange(currentField, `{${variableName}}`);
    }
    handleCloseVariableMenu();
  };

  // Reset form data when dialog opens with new initial data
  useEffect(() => {
    if (open) {
      const initial: Record<string, any> = {};
      Object.entries(params).forEach(([key, paramDef]) => {
        initial[key] = initialData[key] !== undefined 
          ? initialData[key] 
          : (paramDef.default !== undefined ? paramDef.default : '');
      });
      setFormData(initial);
    }
  }, [open, initialData, params]);

  const handleChange = (paramName: string, value: any) => {
    setFormData(prev => {
      const updated = { ...prev, [paramName]: value };
      
      // If this field has dependent fields, reset them to default
      Object.entries(params).forEach(([key, paramDef]) => {
        if (paramDef.depends_on === paramName) {
          // Reset dependent field to its default
          updated[key] = paramDef.default !== undefined ? paramDef.default : '';
        }
      });
      
      return updated;
    });
  };

  const handleSave = () => {
    onSave(formData);
  };

  const renderParam = (paramName: string, paramDef: ParamDef) => {
    const value = formData[paramName];
    
    // Handle dependent ENUM: get choices based on parent field value
    if (paramDef.type === 'enum' && paramDef.depends_on && paramDef.choices_map) {
      const parentValue = formData[paramDef.depends_on];
      const dependentChoices = paramDef.choices_map[parentValue] || [];
      
      return (
        <FormControl key={paramName} fullWidth sx={{ mb: 2 }}>
          <InputLabel>{paramDef.description || paramName}</InputLabel>
          <Select
            value={value}
            label={paramDef.description || paramName}
            onChange={(e) => handleChange(paramName, e.target.value)}
            disabled={!parentValue}  // Disable if parent not selected
          >
            {dependentChoices.map((choice) => (
              <MenuItem key={choice.value} value={choice.value}>
                {choice.label}
              </MenuItem>
            ))}
          </Select>
          {!parentValue && (
            <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>
              Select {paramDef.depends_on} first
            </Typography>
          )}
        </FormControl>
      );
    }
    
    // Handle regular ENUM
    if (paramDef.type === 'enum' && paramDef.choices) {
      return (
        <FormControl key={paramName} fullWidth sx={{ mb: 2 }}>
          <InputLabel>{paramDef.description || paramName}</InputLabel>
          <Select
            value={value}
            label={paramDef.description || paramName}
            onChange={(e) => handleChange(paramName, e.target.value)}
          >
            {paramDef.choices.map((choice) => (
              <MenuItem key={choice.value} value={choice.value}>
                {choice.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      );
    }
    
    // Handle NUMBER
    if (paramDef.type === 'number') {
      return (
        <TextField
          key={paramName}
          fullWidth
          type="number"
          label={paramDef.description || paramName}
          value={value}
          onChange={(e) => handleChange(paramName, parseFloat(e.target.value) || 0)}
          placeholder={paramDef.placeholder}
          inputProps={{
            min: paramDef.min,
            max: paramDef.max,
          }}
          sx={{ mb: 2 }}
        />
      );
    }
    
    // Handle BOOLEAN
    if (paramDef.type === 'boolean') {
      return (
        <FormControl key={paramName} fullWidth sx={{ mb: 2 }}>
          <InputLabel>{paramDef.description || paramName}</InputLabel>
          <Select
            value={value ? 'true' : 'false'}
            label={paramDef.description || paramName}
            onChange={(e) => handleChange(paramName, e.target.value === 'true')}
          >
            <MenuItem value="true">True</MenuItem>
            <MenuItem value="false">False</MenuItem>
          </Select>
        </FormControl>
      );
    }
    
    // Default to STRING
    // Check if this field should have variable insertion (operand fields)
    const supportsVariables = blockCommand === 'evaluate_condition' && 
                              (paramName === 'left_operand' || paramName === 'right_operand');
    
    if (supportsVariables) {
      // Check if current value is a variable reference
      const isVariableRef = typeof value === 'string' && value.match(/^\{(.+)\}$/);
      const varName = isVariableRef ? value.match(/^\{(.+)\}$/)?.[1] : null;
      const resolvedVar = varName ? availableVariables.find(v => v.name === varName) : null;
      
      return (
        <Box key={paramName} sx={{ display: 'flex', gap: 1, alignItems: 'flex-start', mb: 2 }}>
          <TextField
            fullWidth
            label={paramDef.description || paramName}
            value={value}
            onChange={(e) => handleChange(paramName, e.target.value)}
            placeholder={paramDef.placeholder}
            required={paramDef.required}
            InputProps={{
              endAdornment: resolvedVar && resolvedVar.value !== undefined ? (
                <InputAdornment position="end">
                  <Typography variant="body2" sx={{ display: 'flex', gap: 0.5 }}>
                    <Box component="span" sx={{ color: 'text.disabled' }}>|</Box>
                    <Box component="span" sx={{ color: 'text.secondary' }}>{resolvedVar.type}</Box>
                    <Box component="span" sx={{ color: 'info.main' }}>= {JSON.stringify(resolvedVar.value)}</Box>
                  </Typography>
                </InputAdornment>
              ) : undefined
            }}
          />
          <IconButton
            size="small"
            onClick={(e) => handleOpenVariableMenu(e, paramName)}
            sx={{ mt: 1 }}
            title="Insert variable"
          >
            <AddCircleOutlineIcon />
          </IconButton>
        </Box>
      );
    }
    
    return (
      <TextField
        key={paramName}
        fullWidth
        label={paramDef.description || paramName}
        value={value}
        onChange={(e) => handleChange(paramName, e.target.value)}
        placeholder={paramDef.placeholder}
        required={paramDef.required}
        sx={{ mb: 2 }}
      />
    );
  };

  return (
    <>
      <StyledDialog 
        open={open} 
        onClose={onCancel} 
        maxWidth="sm" 
        fullWidth
      >
        <DialogTitle sx={{ borderBottom: 1, borderColor: 'divider', pb: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="h6">Configure {blockLabel}</Typography>
            <Chip label="Standard" size="small" sx={{ bgcolor: '#6b7280', color: 'white' }} />
          </Box>
      </DialogTitle>
        <DialogContent sx={{ pt: 3 }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', pt: 1 }}>
          {Object.entries(params).map(([paramName, paramDef]) => 
            renderParam(paramName, paramDef)
          )}
        </Box>
      </DialogContent>
        <DialogActions sx={{ borderTop: 1, borderColor: 'divider', pt: 2, pb: 2, px: 3 }}>
          <Button 
            onClick={onCancel}
            variant="outlined"
          >
            Cancel
          </Button>
          <Button 
            onClick={handleSave} 
            variant="contained"
          >
          Save
        </Button>
      </DialogActions>
    </StyledDialog>
      
      {/* Variable Selection Menu */}
      <Menu
        anchorEl={variableMenuAnchor}
        open={Boolean(variableMenuAnchor)}
        onClose={handleCloseVariableMenu}
        PaperProps={{
          sx: { maxHeight: 400, width: 350 }
        }}
      >
        {(() => {
          const filtered = currentField ? getFilteredVariables(currentField) : [];
          const groups = groupVariablesBySource(filtered);
          const hasAny = filtered.length > 0;
          
          if (!hasAny) {
            return [
              <MenuItem key="no-vars" disabled>
                <Typography variant="body2" color="text.secondary">
                  No compatible variables available
                </Typography>
              </MenuItem>
            ];
          }
          
          const items: React.ReactNode[] = [];
          
          // INPUTS
          if (groups.inputs.length > 0) {
            items.push(<ListSubheader key="inputs-header">INPUTS ({groups.inputs.length})</ListSubheader>);
            groups.inputs.forEach((v) => {
              items.push(
                <MenuItem key={`input-${v.name}`} onClick={() => handleSelectVariable(v.name)}>
                  <Typography variant="body2">
                    {v.name}: <Box component="span" sx={{ color: 'text.secondary' }}>{v.type}</Box>
                    {v.value !== undefined && v.value !== '' && (
                      <Box component="span" sx={{ color: 'info.main' }}> = {JSON.stringify(v.value)}</Box>
                    )}
                  </Typography>
                </MenuItem>
              );
            });
          }
          
          // OUTPUTS
          if (groups.outputs.length > 0) {
            items.push(<ListSubheader key="outputs-header">OUTPUTS ({groups.outputs.length})</ListSubheader>);
            groups.outputs.forEach((v) => {
              items.push(
                <MenuItem key={`output-${v.name}`} onClick={() => handleSelectVariable(v.name)}>
                  <Typography variant="body2">
                    {v.name}: <Box component="span" sx={{ color: 'text.secondary' }}>{v.type}</Box>
                    {v.value !== undefined && (
                      <Box component="span" sx={{ color: 'info.main' }}> = {JSON.stringify(v.value)}</Box>
                    )}
                  </Typography>
                </MenuItem>
              );
            });
          }
          
          // VARIABLES
          if (groups.variables.length > 0) {
            items.push(<ListSubheader key="variables-header">VARIABLES ({groups.variables.length})</ListSubheader>);
            groups.variables.forEach((v) => {
              items.push(
                <MenuItem key={`var-${v.name}`} onClick={() => handleSelectVariable(v.name)}>
                  <Typography variant="body2">
                    {v.name}: <Box component="span" sx={{ color: 'text.secondary' }}>{v.type}</Box>
                    {v.value !== undefined && (
                      <Box component="span" sx={{ color: 'info.main' }}> = {JSON.stringify(v.value)}</Box>
                    )}
                  </Typography>
                </MenuItem>
              );
            });
          }
          
          // BLOCK OUTPUTS
          if (groups.blockOutputs.length > 0) {
            items.push(<ListSubheader key="block-outputs-header">BLOCK OUTPUTS</ListSubheader>);
            
            // Group by blockId
            const byBlock: Record<string, AvailableVariable[]> = {};
            groups.blockOutputs.forEach(v => {
              if (v.blockId) {
                if (!byBlock[v.blockId]) byBlock[v.blockId] = [];
                byBlock[v.blockId].push(v);
              }
            });
            
            Object.entries(byBlock).forEach(([blockId, outputs]) => {
              items.push(
                <MenuItem key={`block-${blockId}-header`} disabled sx={{ pl: 2 }}>
                  <Typography variant="caption" sx={{ fontWeight: 600 }}>
                    {blockId}
                  </Typography>
                </MenuItem>
              );
              
              outputs.forEach((v) => {
                items.push(
                  <MenuItem key={`block-${blockId}-${v.name}`} onClick={() => handleSelectVariable(v.name)} sx={{ pl: 4 }}>
                    <Typography variant="body2">
                      {v.name}: <Box component="span" sx={{ color: 'text.secondary' }}>{v.type}</Box>
                      {v.value !== undefined && (
                        <Box component="span" sx={{ color: 'info.main' }}> = {JSON.stringify(v.value)}</Box>
                      )}
                    </Typography>
                  </MenuItem>
                );
              });
            });
          }
          
          return items;
        })()}
      </Menu>
    </>
  );
};

