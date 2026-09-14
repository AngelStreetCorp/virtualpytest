import React, { useState } from 'react';
import { Box, Typography, Chip, IconButton, Collapse, TextField, Tooltip, Menu, MenuItem, Badge } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import AddIcon from '@mui/icons-material/Add';
import LinkIcon from '@mui/icons-material/Link';
import CloseIcon from '@mui/icons-material/Close';
import EditIcon from '@mui/icons-material/Edit';
import { VerificationConfigDialog } from '../dialogs/VerificationConfigDialog';
import { useTestCaseBuilder as useTestCaseBuilderContext } from '../../../contexts/testcase/TestCaseBuilderContext';

interface ScriptInput {
  name: string;
  type: string;
  required: boolean;
  default?: any;
  protected?: boolean; // Protected inputs cannot be deleted
}

interface ScriptOutput {
  name: string;
  type: string;
  sourceBlockId?: string;
  sourceOutputName?: string;
  sourceOutputPath?: string;
}

// ✅ NEW: Support for multiple source links
interface SourceLink {
  sourceBlockId: string;
  sourceOutputName: string;
  sourceOutputType: string;
  blockLabel?: string;
}

interface Variable {
  name: string;
  type: string;
  value?: any; // Direct static value (if not linked)
  
  // ❌ OLD: Single link (kept for backward compatibility)
  sourceBlockId?: string;
  sourceOutputName?: string;
  sourceOutputType?: string;
  
  // ✅ NEW: Multiple links
  sourceLinks?: SourceLink[];
}

interface MetadataField {
  name: string;
  value?: any; // Direct value (if not linked)
  sourceBlockId?: string; // OR linked to block output/variable
  sourceOutputName?: string;
  sourceOutputType?: string;
}

interface ScriptIOSectionsProps {
  inputs: ScriptInput[];
  outputs: ScriptOutput[];
  variables: Variable[];
  metadata: MetadataField[];
  onAddInput: () => void;
  onAddOutput: () => void;
  onAddVariable: () => void;
  onAddMetadataField: () => void;
  onRemoveInput: (name: string) => void;
  onRemoveOutput: (name: string) => void;
  onRemoveVariable: (name: string) => void;
  onRemoveMetadataField: (name: string) => void;
  onFocusSourceBlock: (blockId: string) => void;
  onUpdateOutputs: (outputs: ScriptOutput[]) => void;
  onUpdateVariables: (variables: Variable[]) => void;
  onUpdateMetadata: (metadata: MetadataField[]) => void;
}

export const ScriptIOSections: React.FC<ScriptIOSectionsProps> = ({
  inputs,
  outputs,
  variables,
  metadata,
  onAddInput,
  onAddOutput,
  onAddVariable,
  onAddMetadataField,
  onRemoveInput,
  onRemoveOutput,
  onRemoveVariable,
  onRemoveMetadataField,
  onFocusSourceBlock,
  onUpdateOutputs,
  onUpdateVariables,
  onUpdateMetadata,
}) => {
  // Try to get execution values from context (if available)
  // This allows the component to work both in TestCase and Campaign builders
  let contextData: any = null;
  try {
    contextData = useTestCaseBuilderContext();
  } catch (error) {
    // Context not available (e.g., used in Campaign builder)
    // Continue with null values
  }
  
  const executionVariableValues = contextData?.executionVariableValues || {};
  const executionMetadataValues = contextData?.executionMetadataValues || {};
  
  // All sections expanded by default (no overlap issue with tabbed interface)
  const [inputsExpanded, setInputsExpanded] = useState(true);
  const [outputsExpanded, setOutputsExpanded] = useState(true);
  const [variablesExpanded, setVariablesExpanded] = useState(true);
  const [metadataExpanded, setMetadataExpanded] = useState(true);
  
  // Editing state
  const [editingMetadataField, setEditingMetadataField] = useState<string | null>(null);
  const [editingVariableName, setEditingVariableName] = useState<string | null>(null);
  const [editingOutputName, setEditingOutputName] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  
  // Dialog state for showing output values
  const [valueDialogOpen, setValueDialogOpen] = useState(false);
  const [selectedOutput, setSelectedOutput] = useState<ScriptOutput | null>(null);
  
  // ✅ NEW: Menu state for multi-source variables
  const [sourcesMenuAnchor, setSourcesMenuAnchor] = useState<null | HTMLElement>(null);
  const [sourcesMenuVariable, setSourcesMenuVariable] = useState<Variable | null>(null);
  
  // Get execution values and blocks from context (if available)
  const executionOutputValues = contextData?.executionOutputValues || {};
  const nodes = contextData?.nodes || [];
  
  // ✅ NEW: Helper function to get block label from block ID
  const getBlockLabel = (blockId: string): string => {
    if (blockId === 'script_inputs') return 'INPUTS';
    if (blockId === 'script_outputs') return 'OUTPUTS';
    if (blockId === 'script_variables') return 'VARIABLES';
    
    const block = nodes.find((n: any) => n.id === blockId);
    if (!block) return blockId;
    
    const label = block.data?.label || blockId;
    // Extract short name: "action_1:getMenuInfoADB" -> "getMenuInfoADB"
    const parts = label.split(':');
    return parts.length > 1 ? parts[1] : parts[0];
  };
  
  // ✅ NEW: Helper to migrate old format to new format
  const normalizeSourceLinks = (variable: Variable): SourceLink[] => {
    // If new format exists, use it
    if (variable.sourceLinks && variable.sourceLinks.length > 0) {
      return variable.sourceLinks;
    }
    
    // If old format exists, convert it
    if (variable.sourceBlockId && variable.sourceOutputName) {
      return [{
        sourceBlockId: variable.sourceBlockId,
        sourceOutputName: variable.sourceOutputName,
        sourceOutputType: variable.sourceOutputType || 'unknown',
        blockLabel: getBlockLabel(variable.sourceBlockId)
      }];
    }
    
    return [];
  };
  
  // ✅ NEW: Helper to generate display label for multi-source variable
  const getVariableDisplayLabel = (variable: Variable): string => {
    const sources = normalizeSourceLinks(variable);
    
    if (sources.length === 0) {
      // No links, show static value or just name
      if (variable.value !== undefined) {
        return `${variable.name} = ${variable.value}`;
      }
      return variable.name;
    }
    
    if (sources.length === 1) {
      // Single source: "info ← ADB"
      const source = sources[0];
      const blockLabel = source.blockLabel || getBlockLabel(source.sourceBlockId);
      return `${variable.name} ← ${blockLabel}`;
    }
    
    // ✅ Multiple sources: Just show count badge, not all names
    // "info (3)" - compact!
    return variable.name;
  };
  
  // ✅ NEW: Helper to get tooltip text for multi-source variable
  const getVariableTooltip = (variable: Variable): string => {
    const sources = normalizeSourceLinks(variable);
    
    if (sources.length === 0) {
      return '';
    }
    
    if (sources.length === 1) {
      const source = sources[0];
      const blockLabel = source.blockLabel || getBlockLabel(source.sourceBlockId);
      return `${blockLabel}.${source.sourceOutputName}`;
    }
    
    // Multiple sources - simple list, one per line
    const lines = sources.map((source) => {
      const blockLabel = source.blockLabel || getBlockLabel(source.sourceBlockId);
      return `${blockLabel}.${source.sourceOutputName}`;
    });
    
    return lines.join('\n');
  };
  
  const handleOutputClick = (output: ScriptOutput) => {
    setSelectedOutput(output);
    setValueDialogOpen(true);
  };

  const handleStartEditMetadata = (fieldName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingMetadataField(fieldName);
    setEditValue(fieldName);
  };

  const handleSaveMetadataEdit = (oldName: string) => {
    if (editValue && editValue !== oldName) {
      const updatedMetadata = metadata.map(f => 
        f.name === oldName ? { ...f, name: editValue } : f
      );
      onUpdateMetadata(updatedMetadata);
    }
    setEditingMetadataField(null);
    setEditValue('');
  };

  const handleStartEditVariable = (variableName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingVariableName(variableName);
    setEditValue(variableName);
  };

  const handleSaveVariableEdit = (oldName: string) => {
    if (editValue && editValue !== oldName) {
      const updatedVariables = variables.map(v => 
        v.name === oldName ? { ...v, name: editValue } : v
      );
      onUpdateVariables(updatedVariables);
    }
    setEditingVariableName(null);
    setEditValue('');
  };

  const handleStartEditOutput = (outputName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingOutputName(outputName);
    setEditValue(outputName);
  };

  const handleSaveOutputEdit = (oldName: string) => {
    if (editValue && editValue !== oldName) {
      const updatedOutputs = outputs.map(o => 
        o.name === oldName ? { ...o, name: editValue } : o
      );
      onUpdateOutputs(updatedOutputs);
    }
    setEditingOutputName(null);
    setEditValue('');
  };

  // Section colors (muted, professional)
  const sectionColors = {
    inputs: '#0891b2',    // cyan
    outputs: '#ea580c',   // orange
    variables: '#16a34a', // green
    metadata: '#7c3aed',  // violet
  };

  return (
    <Box sx={{ mt: 0 }}>
      {/* Output Value Dialog - Reusing VerificationConfigDialog */}
      <VerificationConfigDialog
        open={valueDialogOpen}
        onCancel={() => setValueDialogOpen(false)}
        onSave={() => {}}
        mode="viewValue"
        outputName={selectedOutput?.name}
        outputValue={selectedOutput ? executionOutputValues[selectedOutput.name] : undefined}
      />
      
      {/* INPUTS Section */}
      <Box
        sx={{
          borderLeft: inputsExpanded ? `3px solid ${sectionColors.inputs}` : '3px solid transparent',
          backgroundColor: inputsExpanded ? 'action.hover' : 'transparent',
          transition: 'all 0.15s ease',
        }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            px: 1.5,
            py: 0.75,
            cursor: 'pointer',
            '&:hover': {
              backgroundColor: 'action.hover',
            },
          }}
          onClick={() => setInputsExpanded(!inputsExpanded)}
        >
          <Typography
            fontSize={13}
            fontWeight={500}
            sx={{ color: 'text.primary' }}
          >
            Inputs
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography fontSize={11} sx={{ color: 'text.disabled' }}>
              {inputs.length}
            </Typography>
            <IconButton size="small" sx={{ p: 0 }}>
              {inputsExpanded ? <ExpandLessIcon sx={{ fontSize: 16 }} /> : <ExpandMoreIcon sx={{ fontSize: 16 }} />}
            </IconButton>
          </Box>
        </Box>
        
        <Collapse in={inputsExpanded}>
          <Box sx={{ px: 1.5, pb: 1, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
            {inputs.map((input) => {
              // Display label: remove "_name" suffix if present
              let displayName = input.name.endsWith('_name') 
                ? input.name.slice(0, -5) 
                : input.name;
              
              // Special case: rename userinterface to interface
              if (displayName === 'userinterface') {
                displayName = 'interface';
              }
              
              // Special case: rename device_model to model
              if (displayName === 'device_model') {
                displayName = 'model';
              }
              
              // Display value: show default value if available, otherwise show type
              const displayValue = input.default !== undefined && input.default !== '' 
                ? `${input.default}` 
                : input.type;
              
              return (
                <Chip
                  key={input.name}
                  label={`${displayName}: ${displayValue}`}
                  size="small"
                  draggable
                  onDragStart={(e) => {
                    e.stopPropagation();
                    const dragData = {
                      blockId: 'script_inputs',
                      outputName: input.name,
                      outputType: input.type
                    };
                    e.dataTransfer.setData('application/json', JSON.stringify(dragData));
                    e.dataTransfer.effectAllowed = 'link';
                  }}
                  onDelete={input.protected ? undefined : () => onRemoveInput(input.name)}
                  sx={{
                    backgroundColor: 'transparent',
                    border: `1px solid ${sectionColors.inputs}`,
                    color: 'text.primary', // White text for readability
                    fontSize: '0.7rem',
                    height: '24px',
                    justifyContent: 'space-between',
                    cursor: input.protected ? 'default' : 'grab',
                    '&:hover': {
                      backgroundColor: `${sectionColors.inputs}15`,
                    },
                    '&:active': {
                      cursor: 'grabbing',
                    },
                    '& .MuiChip-deleteIcon': { color: 'text.secondary' }
                  }}
                />
              );
            })}
            <Chip
              icon={<AddIcon />}
              label="Add Input"
              size="small"
              onClick={onAddInput}
              sx={{
                backgroundColor: `${sectionColors.inputs}15`,
                border: `1px dashed ${sectionColors.inputs}`,
                color: sectionColors.inputs,
                fontSize: '0.7rem',
                height: '24px',
              }}
            />
          </Box>
        </Collapse>
      </Box>

      {/* OUTPUTS Section */}
      <Box
        sx={{
          borderLeft: outputsExpanded ? `3px solid ${sectionColors.outputs}` : '3px solid transparent',
          backgroundColor: outputsExpanded ? 'action.hover' : 'transparent',
          transition: 'all 0.15s ease',
        }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            px: 1.5,
            py: 0.75,
            cursor: 'pointer',
            '&:hover': {
              backgroundColor: 'action.hover',
            },
          }}
          onClick={() => setOutputsExpanded(!outputsExpanded)}
        >
          <Typography
            fontSize={13}
            fontWeight={500}
            sx={{ color: 'text.primary' }}
          >
            Outputs
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography fontSize={11} sx={{ color: 'text.disabled' }}>
              {outputs.length}
            </Typography>
            <IconButton size="small" sx={{ p: 0 }}>
              {outputsExpanded ? <ExpandLessIcon sx={{ fontSize: 16 }} /> : <ExpandMoreIcon sx={{ fontSize: 16 }} />}
            </IconButton>
          </Box>
        </Box>
        
        <Collapse in={outputsExpanded}>
          <Box sx={{ px: 1.5, pb: 1, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
            {outputs.map((output) => (
              <Box
                key={output.name}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 0.5,
                }}
              >
                {editingOutputName === output.name ? (
                  <TextField
                    autoFocus
                    size="small"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onBlur={() => handleSaveOutputEdit(output.name)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        handleSaveOutputEdit(output.name);
                      } else if (e.key === 'Escape') {
                        setEditingOutputName(null);
                        setEditValue('');
                      }
                    }}
                    sx={{
                      flex: 1,
                      '& .MuiInputBase-root': {
                        height: '24px',
                        fontSize: '0.7rem',
                        backgroundColor: 'transparent',
                      },
                      '& .MuiInputBase-input': {
                        color: 'text.primary',
                        padding: '0 8px',
                      },
                      '& .MuiOutlinedInput-notchedOutline': {
                        border: `1px solid ${sectionColors.outputs}`,
                      },
                    }}
                  />
                ) : (
                  <Box
                    sx={{ flex: 1 }}
                    onDragOver={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      
                      // Get drag data from event
                      const dragData = e.dataTransfer.getData('application/json');
                      if (dragData) {
                        try {
                          const { blockId, outputName, outputType } = JSON.parse(dragData);
                          
                          // Update output with link info
                          const updatedOutputs = outputs.map(o => 
                            o.name === output.name 
                              ? { 
                                  ...o, 
                                  sourceBlockId: blockId, 
                                  sourceOutputName: outputName,
                                  sourceOutputType: outputType 
                                }
                              : o
                          );
                          
                          // Trigger parent update
                          onUpdateOutputs(updatedOutputs);
                        } catch (err) {
                          console.error('Failed to parse drag data:', err);
                        }
                      }
                    }}
                  >
                    <Chip
                      icon={output.sourceBlockId ? <LinkIcon /> : undefined}
                      label={
                        output.sourceBlockId
                          ? `${output.name} ← ${output.sourceOutputName}`
                          : output.name
                      }
                      size="small"
                      draggable
                      onDragStart={(e) => {
                        e.stopPropagation();
                        const dragData = {
                          blockId: output.sourceBlockId || 'script_outputs',
                          outputName: output.name,
                          outputType: output.type
                        };
                        e.dataTransfer.setData('application/json', JSON.stringify(dragData));
                        e.dataTransfer.effectAllowed = 'link';
                      }}
                      onClick={(e) => {
                        // If linked and clicking on chip body (not icon), show value dialog
                        const target = e.target as HTMLElement;
                        if (!target.closest('.MuiChip-icon')) {
                          handleOutputClick(output);
                        } else if (output.sourceBlockId) {
                          // If clicking icon and linked, focus source block
                          onFocusSourceBlock(output.sourceBlockId);
                        }
                      }}
                      sx={{
                        width: '100%',
                        backgroundColor: 'transparent',
                        border: `1px solid ${output.sourceBlockId ? sectionColors.variables : sectionColors.outputs}`,
                        color: 'text.primary', // White text for readability
                        fontSize: '0.7rem',
                        height: '24px',
                        justifyContent: 'space-between',
                        cursor: 'pointer',
                        '& .MuiChip-icon': { color: output.sourceBlockId ? sectionColors.variables : sectionColors.outputs },
                        '&:hover': {
                          backgroundColor: output.sourceBlockId ? `${sectionColors.variables}15` : `${sectionColors.outputs}15`,
                        },
                        '&:active': {
                          cursor: 'grabbing',
                        }
                      }}
                    />
                  </Box>
                )}
                {editingOutputName !== output.name && (
                  <IconButton
                    size="small"
                    onClick={(e) => handleStartEditOutput(output.name, e)}
                    sx={{ padding: 0, color: sectionColors.outputs, mr: 0.5 }}
                  >
                    <EditIcon sx={{ fontSize: 14 }} />
                  </IconButton>
                )}
                <IconButton
                  size="small"
                  onClick={() => onRemoveOutput(output.name)}
                  sx={{ padding: 0, color: '#ef4444' }}
                >
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Box>
            ))}
            <Chip
              icon={<AddIcon />}
              label="Add Output"
              size="small"
              onClick={onAddOutput}
              sx={{
                backgroundColor: `${sectionColors.outputs}15`,
                border: `1px dashed ${sectionColors.outputs}`,
                color: sectionColors.outputs,
                fontSize: '0.7rem',
                height: '24px',
              }}
            />
          </Box>
        </Collapse>
      </Box>

      {/* VARIABLES Section */}
      <Box
        sx={{
          borderLeft: variablesExpanded ? `3px solid ${sectionColors.variables}` : '3px solid transparent',
          backgroundColor: variablesExpanded ? 'action.hover' : 'transparent',
          transition: 'all 0.15s ease',
        }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            px: 1.5,
            py: 0.75,
            cursor: 'pointer',
            '&:hover': {
              backgroundColor: 'action.hover',
            },
          }}
          onClick={() => setVariablesExpanded(!variablesExpanded)}
        >
          <Typography
            fontSize={13}
            fontWeight={500}
            sx={{ color: 'text.primary' }}
          >
            Variables
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography fontSize={11} sx={{ color: 'text.disabled' }}>
              {variables.length}
            </Typography>
            <IconButton size="small" sx={{ p: 0 }}>
              {variablesExpanded ? <ExpandLessIcon sx={{ fontSize: 16 }} /> : <ExpandMoreIcon sx={{ fontSize: 16 }} />}
            </IconButton>
          </Box>
        </Box>
        
        <Collapse in={variablesExpanded}>
          <Box sx={{ px: 1.5, pb: 1, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
            {variables.map((variable) => (
              <Box
                key={variable.name}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 0.5,
                }}
              >
                {editingVariableName === variable.name ? (
                  <TextField
                    autoFocus
                    size="small"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onBlur={() => handleSaveVariableEdit(variable.name)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        handleSaveVariableEdit(variable.name);
                      } else if (e.key === 'Escape') {
                        setEditingVariableName(null);
                        setEditValue('');
                      }
                    }}
                    sx={{
                      flex: 1,
                      '& .MuiInputBase-root': {
                        height: '24px',
                        fontSize: '0.7rem',
                        backgroundColor: 'transparent',
                      },
                      '& .MuiInputBase-input': {
                        color: 'text.primary',
                        padding: '0 8px',
                      },
                      '& .MuiOutlinedInput-notchedOutline': {
                        border: `1px solid ${sectionColors.variables}`,
                      },
                    }}
                  />
                ) : (
                  <Box
                    sx={{ flex: 1 }}
                    onDragOver={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      
                      // Get drag data from event
                      const dragData = e.dataTransfer.getData('application/json');
                      if (dragData) {
                        try {
                          const { blockId, outputName, outputType } = JSON.parse(dragData);
                          
                          // ✅ NEW: Append to sourceLinks array instead of replacing
                          const updatedVariables = variables.map(v => {
                            if (v.name === variable.name) {
                              // Normalize existing links
                              const existingLinks = normalizeSourceLinks(v);
                              
                              // Check if already linked (prevent duplicates)
                              const alreadyLinked = existingLinks.some(
                                link => link.sourceBlockId === blockId && 
                                        link.sourceOutputName === outputName
                              );
                              
                              if (alreadyLinked) {
                                console.log(`Already linked: ${blockId}.${outputName}`);
                                return v;
                              }
                              
                              // Add new link
                              const newLink: SourceLink = {
                                sourceBlockId: blockId,
                                sourceOutputName: outputName,
                                sourceOutputType: outputType,
                                blockLabel: getBlockLabel(blockId)
                              };
                              
                              return {
                                ...v,
                                sourceLinks: [...existingLinks, newLink],
                                // Clear old single-link format
                                sourceBlockId: undefined,
                                sourceOutputName: undefined,
                                sourceOutputType: undefined,
                                // Clear static value when linked
                                value: undefined
                              };
                            }
                            return v;
                          });
                          
                          // Trigger parent update
                          onUpdateVariables(updatedVariables);
                        } catch (err) {
                          console.error('Failed to parse drag data:', err);
                        }
                      }
                    }}
                  >
                    <Tooltip 
                      title={
                        executionVariableValues[variable.name] !== undefined 
                          ? <pre style={{ margin: 0, fontSize: '0.75rem' }}>{JSON.stringify(executionVariableValues[variable.name], null, 2)}</pre>
                          : getVariableTooltip(variable)
                      } 
                      placement="left"
                    >
                      <Badge
                        badgeContent={normalizeSourceLinks(variable).length > 1 ? normalizeSourceLinks(variable).length : 0}
                        color="success"
                        overlap="circular"
                        anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
                        sx={{
                          width: '100%',
                          '& .MuiBadge-badge': {
                            fontSize: '0.6rem',
                            height: '16px',
                            minWidth: '16px',
                            backgroundColor: sectionColors.variables,
                            color: 'white',
                            fontWeight: 'bold',
                          }
                        }}
                      >
                        <Chip
                          icon={normalizeSourceLinks(variable).length > 0 ? <LinkIcon /> : undefined}
                          label={
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, width: '100%' }}>
                              <span style={{ flex: 1 }}>{getVariableDisplayLabel(variable)}</span>
                              {executionVariableValues[variable.name] !== undefined && (
                                <span style={{ 
                                  width: '6px', 
                                  height: '6px', 
                                  borderRadius: '50%', 
                                  backgroundColor: sectionColors.variables,
                                  flexShrink: 0
                                }} />
                              )}
                            </Box>
                          }
                          size="small"
                          draggable
                          onDragStart={(e) => {
                            e.stopPropagation();
                            const sources = normalizeSourceLinks(variable);
                            const dragData = {
                              blockId: sources.length > 0 ? sources[0].sourceBlockId : 'script_variables',
                              outputName: variable.name,
                              outputType: variable.type
                            };
                            e.dataTransfer.setData('application/json', JSON.stringify(dragData));
                            e.dataTransfer.effectAllowed = 'link';
                          }}
                          onClick={(e) => {
                            const sources = normalizeSourceLinks(variable);
                            if (sources.length === 1) {
                              // Single source: focus that block
                              onFocusSourceBlock(sources[0].sourceBlockId);
                            } else if (sources.length > 1) {
                              // Multiple sources: show menu
                              setSourcesMenuVariable(variable);
                              setSourcesMenuAnchor(e.currentTarget);
                            }
                          }}
                          sx={{
                            width: '100%',
                            backgroundColor: 'transparent',
                            border: `1px solid ${sectionColors.variables}`,
                            color: 'text.primary', // White text for readability
                            fontSize: '0.7rem',
                            height: '24px',
                            justifyContent: 'space-between',
                            cursor: normalizeSourceLinks(variable).length > 0 ? 'pointer' : 'grab',
                            '& .MuiChip-icon': { color: sectionColors.variables },
                            '&:hover': {
                              backgroundColor: `${sectionColors.variables}15`,
                            },
                            '&:active': {
                              cursor: 'grabbing',
                            }
                          }}
                        />
                      </Badge>
                    </Tooltip>
                  </Box>
                )}
                {editingVariableName !== variable.name && (
                  <IconButton
                    size="small"
                    onClick={(e) => handleStartEditVariable(variable.name, e)}
                    sx={{ padding: 0, color: sectionColors.variables, mr: 0.5 }}
                  >
                    <EditIcon sx={{ fontSize: 14 }} />
                  </IconButton>
                )}
                <IconButton
                  size="small"
                  onClick={() => onRemoveVariable(variable.name)}
                  sx={{ padding: 0, color: '#ef4444' }}
                >
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Box>
            ))}
            <Chip
              icon={<AddIcon />}
              label="Add Variable"
              size="small"
              onClick={onAddVariable}
              sx={{
                backgroundColor: `${sectionColors.variables}15`,
                border: `1px dashed ${sectionColors.variables}`,
                color: sectionColors.variables,
                fontSize: '0.7rem',
                height: '24px',
              }}
            />
          </Box>
        </Collapse>
      </Box>

      {/* METADATA Section */}
      <Box
        sx={{
          borderLeft: metadataExpanded ? `3px solid ${sectionColors.metadata}` : '3px solid transparent',
          backgroundColor: metadataExpanded ? 'action.hover' : 'transparent',
          transition: 'all 0.15s ease',
        }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            px: 1.5,
            py: 0.75,
            cursor: 'pointer',
            '&:hover': {
              backgroundColor: 'action.hover',
            },
          }}
          onClick={() => setMetadataExpanded(!metadataExpanded)}
        >
          <Typography
            fontSize={13}
            fontWeight={500}
            sx={{ color: 'text.primary' }}
          >
            Metadata
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography fontSize={11} sx={{ color: 'text.disabled' }}>
              {metadata.length}
            </Typography>
            <IconButton size="small" sx={{ p: 0 }}>
              {metadataExpanded ? <ExpandLessIcon sx={{ fontSize: 16 }} /> : <ExpandMoreIcon sx={{ fontSize: 16 }} />}
            </IconButton>
          </Box>
        </Box>
        
        <Collapse in={metadataExpanded}>
          <Box sx={{ px: 1.5, pb: 1, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
            {metadata.map((field) => (
              <Box
                key={field.name}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 0.5,
                }}
              >
                {editingMetadataField === field.name ? (
                  <TextField
                    autoFocus
                    size="small"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onBlur={() => handleSaveMetadataEdit(field.name)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        handleSaveMetadataEdit(field.name);
                      } else if (e.key === 'Escape') {
                        setEditingMetadataField(null);
                        setEditValue('');
                      }
                    }}
                    sx={{
                      flex: 1,
                      '& .MuiInputBase-root': {
                        height: '24px',
                        fontSize: '0.7rem',
                        backgroundColor: 'transparent',
                      },
                      '& .MuiInputBase-input': {
                        color: 'text.primary',
                        padding: '0 8px',
                      },
                      '& .MuiOutlinedInput-notchedOutline': {
                        border: `1px solid ${sectionColors.metadata}`,
                      },
                    }}
                  />
                ) : (
                  <Box
                    sx={{ flex: 1 }}
                    onDragOver={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      
                      // Get drag data from event
                      const dragData = e.dataTransfer.getData('application/json');
                      if (dragData) {
                        try {
                          const { blockId, outputName, outputType } = JSON.parse(dragData);
                          
                          // Update metadata field with link info
                          const updatedMetadata = metadata.map(f => 
                            f.name === field.name 
                              ? { 
                                  ...f, 
                                  sourceBlockId: blockId, 
                                  sourceOutputName: outputName,
                                  sourceOutputType: outputType 
                                }
                              : f
                          );
                          
                          // Trigger parent update
                          onUpdateMetadata(updatedMetadata);
                        } catch (err) {
                          console.error('Failed to parse drag data:', err);
                        }
                      }
                    }}
                  >
                    <Tooltip
                      title={
                        executionMetadataValues[field.name] !== undefined
                          ? <pre style={{ margin: 0, fontSize: '0.75rem' }}>{JSON.stringify(executionMetadataValues[field.name], null, 2)}</pre>
                          : ''
                      }
                      placement="left"
                    >
                      <Chip
                        icon={field.sourceBlockId ? <LinkIcon /> : undefined}
                        label={
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, width: '100%' }}>
                            <span style={{ flex: 1 }}>
                              {field.sourceBlockId
                                ? `${field.name} ← ${field.sourceOutputName}`
                                : field.name}
                            </span>
                            {executionMetadataValues[field.name] !== undefined && (
                              <span style={{ 
                                width: '6px', 
                                height: '6px', 
                                borderRadius: '50%', 
                                backgroundColor: sectionColors.variables,
                                flexShrink: 0
                              }} />
                            )}
                          </Box>
                        }
                      size="small"
                      onClick={() => {
                        if (field.sourceBlockId) {
                          onFocusSourceBlock(field.sourceBlockId);
                        }
                      }}
                      sx={{
                        width: '100%',
                        backgroundColor: 'transparent',
                        border: `1px solid ${field.sourceBlockId ? sectionColors.variables : sectionColors.metadata}`,
                        color: 'text.primary', // White text for readability
                        fontSize: '0.7rem',
                        height: '24px',
                        justifyContent: 'space-between',
                        cursor: field.sourceBlockId ? 'pointer' : 'default',
                        '& .MuiChip-icon': { 
                          color: field.sourceBlockId ? sectionColors.variables : sectionColors.metadata,
                          marginLeft: '4px',
                          marginRight: '0px',
                        },
                        '& .MuiChip-label': {
                          paddingLeft: field.sourceBlockId ? '4px' : '12px',
                        },
                        '&:hover': {
                          backgroundColor: field.sourceBlockId ? `${sectionColors.variables}15` : `${sectionColors.metadata}15`,
                        }
                      }}
                    />
                    </Tooltip>
                  </Box>
                )}
                {editingMetadataField !== field.name && (
                  <IconButton
                    size="small"
                    onClick={(e) => handleStartEditMetadata(field.name, e)}
                    sx={{ padding: 0, color: sectionColors.metadata, mr: 0.5 }}
                  >
                    <EditIcon sx={{ fontSize: 14 }} />
                  </IconButton>
                )}
                <IconButton
                  size="small"
                  onClick={() => onRemoveMetadataField(field.name)}
                  sx={{ padding: 0, color: '#ef4444' }}
                >
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Box>
            ))}
            <Chip
              icon={<AddIcon />}
              label="Add Metadata"
              size="small"
              onClick={onAddMetadataField}
              sx={{
                backgroundColor: `${sectionColors.metadata}15`,
                border: `1px dashed ${sectionColors.metadata}`,
                color: sectionColors.metadata,
                fontSize: '0.7rem',
                height: '24px',
              }}
            />
          </Box>
        </Collapse>
      </Box>
      
      {/* Multi-source menu for variables */}
      <Menu
        anchorEl={sourcesMenuAnchor}
        open={Boolean(sourcesMenuAnchor)}
        onClose={() => {
          setSourcesMenuAnchor(null);
          setSourcesMenuVariable(null);
        }}
      >
        <MenuItem disabled sx={{ fontSize: '0.75rem', fontWeight: 'bold', color: sectionColors.variables }}>
          Jump to source:
        </MenuItem>
        {sourcesMenuVariable && normalizeSourceLinks(sourcesMenuVariable).map((source, idx) => (
          <MenuItem
            key={idx}
            onClick={() => {
              onFocusSourceBlock(source.sourceBlockId);
              setSourcesMenuAnchor(null);
              setSourcesMenuVariable(null);
            }}
            sx={{ fontSize: '0.75rem' }}
          >
            {source.blockLabel || getBlockLabel(source.sourceBlockId)} → {source.sourceOutputName}
          </MenuItem>
        ))}
        <MenuItem divider disabled />
        <MenuItem
          onClick={() => {
            if (sourcesMenuVariable) {
              // Unlink all sources
              const updatedVariables = variables.map(v =>
                v.name === sourcesMenuVariable.name
                  ? { ...v, sourceLinks: [], sourceBlockId: undefined, sourceOutputName: undefined, sourceOutputType: undefined }
                  : v
              );
              onUpdateVariables(updatedVariables);
            }
            setSourcesMenuAnchor(null);
            setSourcesMenuVariable(null);
          }}
          sx={{ fontSize: '0.75rem', color: '#ef4444' }}
        >
          ✖ Unlink All
        </MenuItem>
      </Menu>
    </Box>
  );
};

