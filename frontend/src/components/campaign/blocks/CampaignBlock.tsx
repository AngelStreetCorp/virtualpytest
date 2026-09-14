/**
 * Campaign Block Component
 * 
 * Universal block component for the campaign builder canvas.
 * Renders different types of blocks: testcase, script, terminal (start/success/failure).
 * Supports data linking via draggable output badges and input drop zones.
 * 
 * Clean, minimal design - color-coded left accent indicates block type.
 */

import React, { useState, memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import {
  Box,
  Typography,
  Chip,
  IconButton,
  Collapse,
  Tooltip,
  TextField,
} from '@mui/material';
import {
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  Delete as DeleteIcon,
  Link as LinkIcon,
  Edit as EditIcon,
  Close as CloseIcon,
  PlayArrow as PlayArrowIcon,
} from '@mui/icons-material';
import { CampaignNode, CampaignDragData } from '../../../types/pages/CampaignGraph_Types';
import { useCampaignBuilder } from '../../../contexts/campaign/CampaignBuilderContext';
import { useTheme } from '../../../contexts/ThemeContext';
import { useHostControl } from '../../../hooks/useHostManager';
import { BlockOutputHandles, OutputType } from '../../common/builder/BlockOutputHandles';

export const CampaignBlock = memo(({ data, id, selected }: NodeProps<CampaignNode['data']>) => {
  const { deleteNode, selectNode, linkOutputToInput, nodes, updateNode, executeBlock, state } = useCampaignBuilder();
  const { selectedHost, selectedDeviceId } = useHostControl();
  const { actualMode } = useTheme();
  const [inputsExpanded, setInputsExpanded] = useState(false);
  const [outputsExpanded, setOutputsExpanded] = useState(false);
  const [isEditingLabel, setIsEditingLabel] = useState(false);
  const [editedLabel, setEditedLabel] = useState(data.label || '');

  const isTerminal = ['start', 'success', 'failure'].includes(id);
  const isTestCase = data.executableType === 'testcase';
  const isScript = data.executableType === 'script';
  const isDark = actualMode === 'dark';
  const readOnly = data.readOnly || false; // Check if viewer mode is enabled
  const globalUserInterface = data.selectedUserInterface; // Global userinterface from viewer

  // Get colors based on node type - muted, professional palette
  const getColors = () => {
    if (id === 'start') return { accent: '#3b82f6', bg: isDark ? '#1e293b' : '#ffffff' };
    if (id === 'success') return { accent: '#10b981', bg: isDark ? '#1e293b' : '#ffffff' };
    if (id === 'failure') return { accent: '#ef4444', bg: isDark ? '#1e293b' : '#ffffff' };
    if (isTestCase) return { accent: '#9c27b0', bg: isDark ? '#1e293b' : '#ffffff' };
    if (isScript) return { accent: '#f97316', bg: isDark ? '#1e293b' : '#ffffff' };
    return { accent: '#64748b', bg: isDark ? '#1e293b' : '#ffffff' };
  };

  const colors = getColors();

  // Label editing handlers
  const handleLabelEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsEditingLabel(true);
  };

  const handleLabelSave = () => {
    if (editedLabel.trim() && editedLabel !== data.label) {
      updateNode(id, { label: editedLabel.trim() });
    }
    setIsEditingLabel(false);
  };

  const handleLabelCancel = () => {
    setEditedLabel(data.label || '');
    setIsEditingLabel(false);
  };

  const handleLabelKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleLabelSave();
    } else if (e.key === 'Escape') {
      handleLabelCancel();
    }
  };

  // Handle output badge drag start
  const handleOutputDragStart = (e: React.DragEvent, outputName: string, outputType?: string) => {
    if (readOnly) return; // Disable output dragging in read-only mode

    const dragData: CampaignDragData = {
      type: 'output-badge',
      blockId: id,
      outputName,
      outputType,
    };
    e.dataTransfer.setData('application/json', JSON.stringify(dragData));
    e.dataTransfer.effectAllowed = 'link';
  };

  // Handle input drop
  const handleInputDrop = (e: React.DragEvent, inputName: string) => {
    if (readOnly) return; // Disable input dropping in read-only mode

    e.preventDefault();
    e.stopPropagation();

    try {
      const dragData: CampaignDragData = JSON.parse(e.dataTransfer.getData('application/json'));

      if (dragData.type === 'output-badge' && dragData.blockId && dragData.outputName) {
        // Prevent linking to self
        if (dragData.blockId === id) {
          console.warn('[@CampaignBlock] Cannot link output to input on same block');
          return;
        }

        linkOutputToInput(dragData.blockId, dragData.outputName, id, inputName);
      }
    } catch (error) {
      console.error('[@CampaignBlock] Error handling input drop:', error);
    }
  };

  const handleInputDragOver = (e: React.DragEvent) => {
    if (readOnly) return; // Disable drag over in read-only mode

    e.preventDefault();
    e.dataTransfer.dropEffect = 'link';
  };

  // Find linked source info for an input
  const getLinkedSourceInfo = (inputName: string) => {
    const input = data.inputs?.find(i => i.name === inputName);
    if (!input?.linkedSource) return null;
    
    const sourceNode = nodes.find(n => n.id === input.linkedSource!.blockId);
    return {
      blockName: sourceNode?.data.label || input.linkedSource.blockId,
      outputName: input.linkedSource.outputName,
    };
  };

  // Handle link icon click (focus on source block)
  const handleLinkIconClick = (inputName: string) => {
    const input = data.inputs?.find(i => i.name === inputName);
    if (input?.linkedSource) {
      selectNode(input.linkedSource.blockId);
      // TODO: Scroll to source block
    }
  };

  // Per-row static value for a testcase input — stored in data.parameters,
  // which ships as script_configurations[].parameters and is stamped onto the
  // testcase's scriptConfig.inputs[].value at execution. Empty = use the
  // testcase's own default.
  const handleInputValueChange = (inputName: string, value: string) => {
    const nextParameters = { ...(data.parameters || {}) };
    if (value === '') {
      delete nextParameters[inputName];
    } else {
      nextParameters[inputName] = value;
    }
    updateNode(id, { parameters: nextParameters });
  };

  // Handle play button click (execute individual block)
  const handlePlayClick = async (e: React.MouseEvent) => {
    e.stopPropagation();

    // Check if required selections are made (same as TestCaseFlowViewer)
    if (!selectedDeviceId || !selectedHost?.host_name) {
      console.error(`[CampaignBlock] Cannot execute block: no host/device selected`);

      // Update block state to show error
      updateNode(id, {
        status: 'failed',
        error: 'No host/device selected. Please select a host and device first.',
      });
      return;
    }

    // Use global userinterface if available (viewer mode), otherwise use campaign's userinterface
    const userInterfaceToUse = globalUserInterface || state.userinterface_name;

    if (!userInterfaceToUse) {
      const errorMessage = globalUserInterface !== undefined
        ? 'Please select a userinterface first using the interface selector.'
        : 'This campaign has no userinterface configured. Please set the userinterface in Campaign Builder.';

      console.error(`[CampaignBlock] Cannot execute block: no userinterface available`);

      // Update block state to show error
      updateNode(id, {
        status: 'failed',
        error: errorMessage,
      });
      return;
    }

    try {
      console.log(`[CampaignBlock] Executing individual block: ${id}`);
      await executeBlock(id, selectedHost.host_name, selectedDeviceId, userInterfaceToUse);
    } catch (error) {
      console.error('[CampaignBlock] Error executing block:', error);

      // Update block state to show error
      updateNode(id, {
        status: 'failed',
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      });
    }
  };

  // Render terminal nodes (START, SUCCESS, FAILURE)
  // NOTE: Terminal nodes should use StartBlock, SuccessBlock, FailureBlock components
  // This is a fallback for campaign-specific terminal rendering
  if (isTerminal) {
    return (
      <Box
        sx={{
          minWidth: 120,
          minHeight: 60,
          background: colors.bg,
          border: `2px solid ${colors.accent}`,
          borderRadius: 2,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontWeight: 'bold',
          color: colors.accent,
          fontSize: '1.1rem',
        }}
      >
        {/* Handles */}
        {id === 'start' && (
          <Handle type="source" position={Position.Bottom} style={{ background: colors.accent }} />
        )}
        {(id === 'success' || id === 'failure') && (
          <Handle type="target" position={Position.Top} style={{ background: colors.accent }} />
        )}
        
        {data.label}
      </Box>
    );
  }

  // Render executable nodes (TestCase, Script)
  // Uses same styling as UniversalBlock for consistency
  return (
    <Box
      sx={{
        width: 280,
        minHeight: 100,
        background: colors.bg,
        border: selected ? '2px solid #fbbf24' : `1px solid ${isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)'}`,
        borderLeft: `3px solid ${colors.accent}`, // Left accent bar like UniversalBlock
        borderRadius: 1.5,
        boxShadow: isDark 
          ? '0 2px 8px rgba(0,0,0,0.3)' 
          : '0 2px 8px rgba(0,0,0,0.08)',
        cursor: 'pointer',
        overflow: 'hidden',
        transition: 'all 0.2s ease',
        '&:hover': {
          boxShadow: isDark 
            ? '0 4px 16px rgba(0,0,0,0.4)' 
            : '0 4px 16px rgba(0,0,0,0.12)',
        },
      }}
      onClick={() => selectNode(id)}
    >
      {/* Input Handle */}
      <Handle 
        type="target" 
        position={Position.Top} 
        style={{ 
          background: colors.accent, 
          width: 14,
          height: 14,
          borderRadius: '50%',
          border: 'none',
          top: -7,
          boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
        }} 
      />
      
      {/* Output Handles - using shared BlockOutputHandles component */}
      <BlockOutputHandles 
        outputs={['pass', 'fail'] as OutputType[]}
        executionState={data.status ? { 
          status: data.status === 'completed' ? 'success' : 
                  data.status === 'failed' ? 'failure' : 
                  data.status === 'running' ? 'executing' : 'pending' 
        } : null}
      />

      {/* Header - clean, minimal design matching UniversalBlock */}
      <Box
        sx={{
          p: 1,
          background: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.02)',
          borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)'}`,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          justifyContent: 'space-between',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: 1 }}>
          {isEditingLabel ? (
            <>
              <TextField
                value={editedLabel}
                onChange={(e) => setEditedLabel(e.target.value)}
                onKeyDown={handleLabelKeyDown}
                onBlur={handleLabelSave}
                autoFocus
                size="small"
                inputProps={{
                  maxLength: 30,
                  style: { color: colors.accent, fontSize: 14, fontWeight: 600, padding: '2px 4px' }
                }}
                sx={{
                  '& .MuiOutlinedInput-root': {
                    '& fieldset': { borderColor: colors.accent },
                    '&:hover fieldset': { borderColor: colors.accent },
                    '&.Mui-focused fieldset': { borderColor: colors.accent },
                  },
                  flex: 1,
                  maxWidth: '200px',
                }}
              />
              <IconButton
                size="small"
                onClick={(e) => { e.stopPropagation(); handleLabelCancel(); }}
                sx={{ color: 'text.secondary', padding: '2px', '&:hover': { backgroundColor: 'action.hover' } }}
              >
                <CloseIcon sx={{ fontSize: 14 }} />
              </IconButton>
            </>
          ) : (
            <>
              <Typography
                fontWeight={600}
                fontSize={14}
                sx={{
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  color: colors.accent,
                }}
              >
                {data.label || data.executableName}
              </Typography>
              {/* Play button for executable blocks - visible in viewer mode for execution */}
              {(isTestCase || isScript) && (
                <IconButton
                  size="small"
                  onClick={handlePlayClick}
                  disabled={!selectedHost?.host_name || !selectedDeviceId || !(globalUserInterface || state.userinterface_name)}
                  sx={{
                    color: !selectedHost?.host_name || !selectedDeviceId || !(globalUserInterface || state.userinterface_name) ? '#9ca3af' : '#22c55e',
                    padding: '2px',
                    '&:hover': {
                      backgroundColor: !selectedHost?.host_name || !selectedDeviceId || !(globalUserInterface || state.userinterface_name)
                        ? 'rgba(156, 163, 175, 0.1)'
                        : 'rgba(34, 197, 94, 0.1)',
                      color: !selectedHost?.host_name || !selectedDeviceId || !(globalUserInterface || state.userinterface_name) ? '#9ca3af' : '#16a34a'
                    },
                    '&.Mui-disabled': {
                      color: '#9ca3af',
                    }
                  }}
                  title={
                    !selectedHost?.host_name || !selectedDeviceId || !(globalUserInterface || state.userinterface_name)
                      ? (globalUserInterface !== undefined ? 'Select host/device and userinterface first' : 'Select host/device and configure campaign userinterface first')
                      : `Execute ${data.label || data.executableName}`
                  }
                >
                  <PlayArrowIcon sx={{ fontSize: 16 }} />
                </IconButton>
              )}
              {!readOnly && (
                <IconButton
                  size="small"
                  onClick={handleLabelEdit}
                  sx={{ color: 'text.secondary', padding: '2px', '&:hover': { backgroundColor: 'action.hover' } }}
                >
                  <EditIcon sx={{ fontSize: 14 }} />
                </IconButton>
              )}
            </>
          )}
        </Box>
        {!readOnly && (
          <IconButton
            size="small"
            onClick={(e) => { e.stopPropagation(); deleteNode(id); }}
            sx={{
              color: 'text.secondary',
              padding: '4px',
              '&:hover': { backgroundColor: 'action.hover', color: '#ef4444' }
            }}
          >
            <DeleteIcon sx={{ fontSize: 16 }} />
          </IconButton>
        )}
      </Box>

      {/* Body - matching UniversalBlock styling */}
      <Box sx={{ p: 1.5 }}>
        {data.description && (
          <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
            {data.description}
          </Typography>
        )}

        {/* INPUTS Section - dark mode aware */}
        {data.inputs && data.inputs.length > 0 && (
          <Box sx={{ mb: 1 }}>
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                p: 0.5,
                background: isDark ? 'rgba(6, 182, 212, 0.1)' : 'rgba(6, 182, 212, 0.05)',
                borderRadius: 1,
                cursor: 'pointer',
              }}
              onClick={() => setInputsExpanded(!inputsExpanded)}
            >
              <Typography 
                variant="caption" 
                sx={{ 
                  fontWeight: 600, 
                  color: '#06b6d4',
                  fontSize: '0.8rem',
                  letterSpacing: '0.5px'
                }}
              >
                INPUTS ({data.inputs.length})
              </Typography>
              {inputsExpanded ? <ExpandLessIcon fontSize="small" sx={{ color: 'text.secondary' }} /> : <ExpandMoreIcon fontSize="small" sx={{ color: 'text.secondary' }} />}
            </Box>
            
            <Collapse in={inputsExpanded}>
              <Box sx={{ mt: 0.5, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                {data.inputs.map((input) => {
                  const linkedSource = getLinkedSourceInfo(input.name);
                  
                  return (
                    <Box
                      key={input.name}
                      onDrop={(e) => handleInputDrop(e, input.name)}
                      onDragOver={handleInputDragOver}
                      sx={{
                        p: 0.5,
                        background: linkedSource 
                          ? (isDark ? 'rgba(16, 185, 129, 0.15)' : 'rgba(16, 185, 129, 0.1)') 
                          : (isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.02)'),
                        borderRadius: 1,
                        border: `1px dashed ${isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.15)'}`,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 0.5,
                        '&:hover': {
                          borderColor: '#06b6d4',
                          background: linkedSource 
                            ? (isDark ? 'rgba(16, 185, 129, 0.2)' : 'rgba(16, 185, 129, 0.15)') 
                            : (isDark ? 'rgba(6, 182, 212, 0.1)' : 'rgba(6, 182, 212, 0.05)'),
                        },
                      }}
                    >
                      <Typography variant="caption" sx={{ flex: 1, fontSize: '0.75rem' }}>
                        {input.name}
                        {input.required && <span style={{ color: '#ef4444' }}>*</span>}
                      </Typography>

                      {linkedSource ? (
                        <Tooltip title={`Source: ${linkedSource.blockName} → ${linkedSource.outputName}`}>
                          <IconButton
                            size="small"
                            onClick={(e) => { e.stopPropagation(); handleLinkIconClick(input.name); }}
                            sx={{ p: 0.25 }}
                          >
                            <LinkIcon fontSize="small" sx={{ color: '#10b981' }} />
                          </IconButton>
                        </Tooltip>
                      ) : (
                        // Static per-row value (empty = testcase default). The row
                        // stays a drop target for output→input linking.
                        <TextField
                          className="nodrag"
                          size="small"
                          variant="standard"
                          disabled={readOnly}
                          value={data.parameters?.[input.name] ?? ''}
                          placeholder={
                            input.default != null && String(input.default) !== ''
                              ? `default: ${input.default}`
                              : 'value'
                          }
                          onChange={(e) => handleInputValueChange(input.name, e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          inputProps={{ style: { fontSize: '0.7rem' } }}
                          sx={{ width: 110 }}
                        />
                      )}
                    </Box>
                  );
                })}
              </Box>
            </Collapse>
          </Box>
        )}

        {/* OUTPUTS Section - dark mode aware */}
        {data.outputs && data.outputs.length > 0 && (
          <Box>
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                p: 0.5,
                background: isDark ? 'rgba(249, 115, 22, 0.1)' : 'rgba(249, 115, 22, 0.05)',
                borderRadius: 1,
                cursor: 'pointer',
              }}
              onClick={() => setOutputsExpanded(!outputsExpanded)}
            >
              <Typography 
                variant="caption" 
                sx={{ 
                  fontWeight: 600, 
                  color: '#f97316',
                  fontSize: '0.8rem',
                  letterSpacing: '0.5px'
                }}
              >
                OUTPUTS ({data.outputs.length})
              </Typography>
              {outputsExpanded ? <ExpandLessIcon fontSize="small" sx={{ color: 'text.secondary' }} /> : <ExpandMoreIcon fontSize="small" sx={{ color: 'text.secondary' }} />}
            </Box>
            
            <Collapse in={outputsExpanded}>
              <Box sx={{ mt: 0.5, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                {data.outputs.map((output) => (
                  <Chip
                    key={output.name}
                    label={output.name}
                    size="small"
                    draggable={!readOnly}
                    onDragStart={(e) => handleOutputDragStart(e, output.name, output.type)}
                    sx={{
                      background: '#f97316',
                      color: 'white',
                      cursor: readOnly ? 'default' : 'grab',
                      '&:active': {
                        cursor: readOnly ? 'default' : 'grabbing',
                      },
                      '&:hover': {
                        background: readOnly ? '#f97316' : '#ea580c',
                      },
                    }}
                  />
                ))}
              </Box>
            </Collapse>
          </Box>
        )}

        {/* Execution State (during run) - dark mode aware */}
        {data.status && (
          <Box sx={{ mt: 1, pt: 1, borderTop: `1px solid ${isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)'}` }}>
            <Chip
              label={data.status.toUpperCase()}
              size="small"
              color={
                data.status === 'completed' ? 'success' :
                data.status === 'running' ? 'primary' :
                data.status === 'failed' ? 'error' : 'default'
              }
            />
            {data.executionTime && (
              <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                {(data.executionTime / 1000).toFixed(1)}s
              </Typography>
            )}
          </Box>
        )}
      </Box>
    </Box>
  );
});

CampaignBlock.displayName = 'CampaignBlock';

