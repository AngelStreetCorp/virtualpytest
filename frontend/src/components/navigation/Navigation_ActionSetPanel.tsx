import { Close as CloseIcon } from '@mui/icons-material';
import { Box, Typography, Button, IconButton, Paper, Chip } from '@mui/material';
import React, { useMemo } from 'react';

import { useEdge } from '../../hooks/navigation/useEdge';
import { Host } from '../../types/common/Host_Types';
import { UINavigationEdge } from '../../types/pages/Navigation_Types';
import { ActionSet } from '../../types/pages/Navigation_Types';
import { getZIndex } from '../../utils/zIndexUtils';

interface ActionSetPanelProps {
  selectedEdge: UINavigationEdge;
  actionSet: ActionSet;
  isDefault: boolean;
  panelIndex: number;
  onClose: () => void;
  onEdit: () => void;
  fromLabel: string;
  toLabel: string;

  // Device control props
  isControlActive?: boolean;
  selectedHost?: Host;
  selectedDeviceId?: string;
}

export const ActionSetPanel: React.FC<ActionSetPanelProps> = React.memo(({
  selectedEdge,
  actionSet,
  isDefault,
  panelIndex,
  onClose,
  onEdit,
  fromLabel,
  toLabel,
  isControlActive = false,
  selectedHost,
  selectedDeviceId,
}) => {
  // Use the edge hook for action execution
  const edgeHook = useEdge({
    selectedHost: selectedHost || null,
    selectedDeviceId: selectedDeviceId || null,
    isControlActive,
  });

  const actions = actionSet.actions || [];
  const retryActions = actionSet.retry_actions || [];
  const failureActions = actionSet.failure_actions || [];
  const hasActions = actions.length > 0;
  const hasRetryActions = retryActions.length > 0;
  const hasFailureActions = failureActions.length > 0;

  // Check if this action set can be executed
  const canExecute = useMemo(() => {
    return (
      isControlActive &&
      selectedHost !== null &&
      hasActions &&
      !edgeHook.actionHook.loading
    );
  }, [isControlActive, selectedHost, hasActions, edgeHook.actionHook.loading]);

  // Execute this specific action set
  const handleExecuteActionSet = async () => {
    if (!canExecute) return;
    
    try {
      await edgeHook.executeEdgeActions(selectedEdge, actionSet.actions, actionSet.retry_actions, actionSet.failure_actions, actionSet.id);
    } catch (error) {
      console.error('Failed to execute action set:', error);
    }
  };

  // Panel positioning
  const panelStyle = {
    position: 'fixed' as const,
    top: `${120 + panelIndex * 280}px`, // Stack panels vertically
    right: '20px',
    width: '400px',
    maxHeight: '250px',
    zIndex: getZIndex('UI_ELEMENTS'),
    backgroundColor: 'white',
    border: '1px solid #e0e0e0',
    borderRadius: '8px',
    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
  };

  return (
    <Paper sx={panelStyle}>
      <Box sx={{ p: 2 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="h6" sx={{ fontSize: '1rem', fontWeight: 600 }}>
              {actionSet.label}
            </Typography>
            {isDefault && (
              <Chip 
                label="DEFAULT" 
                size="small" 
                color="primary" 
                sx={{ fontSize: '0.7rem', height: '20px' }}
              />
            )}
            {actionSet.timer && actionSet.timer > 0 && (
              <Chip 
                label={`${actionSet.timer}ms`} 
                size="small" 
                color="secondary" 
                sx={{ fontSize: '0.7rem', height: '20px' }}
              />
            )}
          </Box>
          <IconButton onClick={onClose} size="small">
            <CloseIcon fontSize="small" />
          </IconButton>
        </Box>

        {/* Edge Info */}
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {fromLabel} → {toLabel}
        </Typography>

        {/* Actions Summary */}
        <Box sx={{ mb: 2 }}>
          <Typography variant="body2" sx={{ mb: 1 }}>
            <strong>Actions:</strong> {actions.length}
            {hasRetryActions && ` | Retry Actions: ${retryActions.length}`}
            {hasFailureActions && ` | Failure Actions: ${failureActions.length}`}
          </Typography>
          
          {/* Priority and Conditions */}
          <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
            <Chip 
              label={`Priority: ${actionSet.priority}`} 
              size="small" 
              variant="outlined"
              sx={{ fontSize: '0.7rem', height: '20px' }}
            />
            {actionSet.conditions && Object.keys(actionSet.conditions).length > 0 && (
              <Chip 
                label="Has Conditions" 
                size="small" 
                variant="outlined"
                sx={{ fontSize: '0.7rem', height: '20px' }}
              />
            )}
          </Box>

          {/* Action List Preview */}
          {actions.length > 0 && (
            <Box sx={{ maxHeight: '80px', overflow: 'auto', bgcolor: '#f5f5f5', p: 1, borderRadius: 1 }}>
              {actions.slice(0, 3).map((action, index) => (
                <Typography key={index} variant="caption" sx={{ display: 'block', fontSize: '0.7rem' }}>
                  {index + 1}. {action.command}
                  {action.params && Object.keys(action.params).length > 0 && 
                    ` (${Object.entries(action.params).map(([k, v]) => `${k}=${v}`).join(', ')})`
                  }
                </Typography>
              ))}
              {actions.length > 3 && (
                <Typography variant="caption" sx={{ fontSize: '0.7rem', fontStyle: 'italic' }}>
                  ... and {actions.length - 3} more actions
                </Typography>
              )}
            </Box>
          )}
        </Box>

        {/* Action Buttons */}
        <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
          <Button
            variant="outlined"
            size="small"
            onClick={onEdit}
            sx={{ fontSize: '0.8rem' }}
          >
            Edit
          </Button>
          <Button
            variant="contained"
            size="small"
            onClick={handleExecuteActionSet}
            disabled={!canExecute}
            sx={{ fontSize: '0.8rem' }}
          >
            {edgeHook.actionHook.loading ? 'Running...' : 'Execute'}
          </Button>
        </Box>

        {/* Execution Result */}
        {edgeHook.runResult && (
          <Box sx={{ mt: 2, p: 1, bgcolor: '#f0f0f0', borderRadius: 1, maxHeight: '60px', overflow: 'auto' }}>
            <Typography variant="caption" sx={{ fontSize: '0.7rem', whiteSpace: 'pre-wrap' }}>
              {edgeHook.formatRunResult(edgeHook.runResult)}
            </Typography>
          </Box>
        )}
      </Box>
    </Paper>
  );
});

ActionSetPanel.displayName = 'ActionSetPanel';