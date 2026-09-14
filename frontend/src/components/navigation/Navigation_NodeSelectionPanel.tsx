import {
  Close as CloseIcon,
  Camera as CameraIcon,
  Route as RouteIcon,
  CheckCircle as CheckCircleIcon,
} from '@mui/icons-material';
import {
  Box,
  Typography,
  Button,
  IconButton,
  Paper,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material';

import { StyledDialog } from '../common/StyledDialog';
import React, { useState, useMemo, useCallback } from 'react';

import { useNode } from '../../hooks/navigation/useNode';
import { useValidationColors } from '../../hooks/validation/useValidationColors';
import { Host } from '../../types/common/Host_Types';
import { UINavigationNode, NodeForm } from '../../types/pages/Navigation_Types';
import { NodeMetricData } from '../../types/navigation/Metrics_Types';
import { getZIndex } from '../../utils/zIndexUtils';

interface NodeSelectionPanelProps {
  selectedNode: UINavigationNode;
  nodes: UINavigationNode[];
  onClose: () => void;
  onDelete: () => void;
  setNodeForm: React.Dispatch<React.SetStateAction<NodeForm>>;
  setIsNodeDialogOpen: (open: boolean) => void;
  onReset?: (id: string) => void;
  onUpdateNode?: (nodeId: string, updatedData: any) => void;
  // Device control props
  isControlActive?: boolean;
  selectedHost?: Host; // Full host object for API calls
  selectedDeviceId?: string; // Required for device-specific operations
  // Navigation props
  treeId?: string;
  currentNodeId?: string;
  // Goto panel callback
  onOpenGotoPanel?: (node: UINavigationNode) => void;
  // Metrics props - passed from NavigationEditor
  nodeMetrics?: NodeMetricData | null;
  // Active canvas viewing scope (variant). A capture made here lands on this
  // variant's override (separate R2 object + node_overrides entry), not base.
  variant?: string | null;
}

// No custom comparison function - use React's default shallow comparison
// This matches how EdgeSelectionPanel works

export const NodeSelectionPanel: React.FC<NodeSelectionPanelProps> = React.memo(
  ({
    selectedNode,
    nodes,
    onClose,
    onDelete,
    setNodeForm,
    setIsNodeDialogOpen,
    onReset,
    onUpdateNode,
    isControlActive = false,
    selectedHost,
    selectedDeviceId,
    treeId = '',
    currentNodeId,
    onOpenGotoPanel,
    nodeMetrics,
    variant,
  }) => {
    // Don't render the panel for entry nodes - MUST be before any hooks
    if ((selectedNode.type as string) === 'entry') {
      return null;
    }

    // Memoize hook props to prevent unnecessary hook re-executions
    const nodeHookProps = useMemo(
      () => ({
        selectedHost,
        selectedDeviceId,
        isControlActive,
        treeId,
        currentNodeId,
        variant,
      }),
      [selectedHost, selectedDeviceId, isControlActive, treeId, currentNodeId, variant],
    );

    // Use the consolidated node hook
    const nodeHook = useNode(nodeHookProps);
    
    // Get validation colors for confidence-based styling
    const { getNodeColors } = useValidationColors([]);

    // Add states for confirmation dialogs
    const [showResetConfirm, setShowResetConfirm] = useState(false);
    const [showScreenshotConfirm, setShowScreenshotConfirm] = useState(false);

    // Memoize handlers to prevent unnecessary re-renders of child components
    const handleEdit = useCallback(() => {
      // Don't open dialog if no valid host is selected
      if (!isControlActive || !selectedHost) {
        return;
      }
      const nodeForm = nodeHook.getNodeFormWithVerifications(selectedNode);
      console.log('[NodeSelectionPanel] Opening edit dialog with nodeForm verifications:', nodeForm.verifications);
      console.log('[NodeSelectionPanel] Selected node verifications:', selectedNode.data.verifications);
      setNodeForm(nodeForm);
      setIsNodeDialogOpen(true);
    }, [nodeHook, selectedNode, setNodeForm, setIsNodeDialogOpen, isControlActive, selectedHost]);

          // Confirmation handlers
      const handleResetConfirm = useCallback(() => {
      if (onReset) {
        onReset(selectedNode.id);
      }
      setShowResetConfirm(false);
    }, [onReset, selectedNode.id]);

    const handleScreenshotConfirm = useCallback(async () => {
      await nodeHook.handleScreenshotConfirm(selectedNode, onUpdateNode);
      setShowScreenshotConfirm(false);
    }, [nodeHook, selectedNode, onUpdateNode]);

    // Get memoized button visibility from hook
    const { showSaveScreenshotButton, showGoToButton } = nodeHook.getNodeButtonVisibility(selectedNode);

    const isProtected = useMemo(
      () => nodeHook.isProtectedNode(selectedNode),
      [nodeHook, selectedNode],
    );

    // Memoize parent names calculation
    const parentNames = useMemo(
      () => nodeHook.getParentNames(selectedNode.data.parent || [], nodes),
      [nodeHook, selectedNode.data.parent, nodes],
    );

    // Get confidence-based colors for the node
    const nodeColors = useMemo(() => {
      return getNodeColors(selectedNode.type as any, nodeMetrics);
    }, [getNodeColors, selectedNode.type, nodeMetrics]);

    // Format metrics display
    const metricsDisplay = useMemo(() => {
      if (!nodeMetrics) {
        return {
          successRateText: 'No data',
          successRateColor: '#666',
          confidenceScore: 0,
          confidenceColor: '#666',
          volumeText: '0',
          timeText: '0s'
        };
      }

      // Success rate should be 0% or 100% for single executions, or actual percentage for multiple
      const successRatePercent = Math.round(nodeMetrics.success_rate * 100);
      
      // Confidence is 0-1, convert to 0-10 scale for display
      const confidenceScore = Math.round(nodeMetrics.confidence * 10); // Round to whole number
      
      return {
        successRateText: `${successRatePercent}%`,
        successRateColor: nodeMetrics.volume === 0 ? '#666' : (successRatePercent >= 90 ? '#22c55e' : successRatePercent >= 70 ? '#f59e0b' : '#ef4444'),
        confidenceScore: confidenceScore,
        confidenceColor: nodeColors.border,
        volumeText: `${nodeMetrics.volume}`,
        // Verify chip: average wall-clock duration of verify_node() on this node.
        timeText: nodeMetrics.avg_verification_time > 0
          ? `${(nodeMetrics.avg_verification_time / 1000).toFixed(2)}s`
          : '0s'
      };
    }, [nodeMetrics, nodeColors]);

    // Memoize event handlers to prevent unnecessary re-renders
    const handleCloseClick = useCallback(
      (e: React.MouseEvent) => {
        e.stopPropagation(); // Prevent event from bubbling to ReactFlow pane
        onClose();
      },
      [onClose],
    );

    const handlePaperClick = useCallback((e: React.MouseEvent) => {
      e.stopPropagation();
    }, []);

    const handleScreenshotButtonClick = useCallback((e: React.MouseEvent) => {
      (e.currentTarget as HTMLElement).blur(); // Remove focus from the button before opening dialog
      setShowScreenshotConfirm(true);
    }, []);

    const handleGoToButtonClick = useCallback(() => {
      if (onOpenGotoPanel) {
        onOpenGotoPanel(selectedNode);
        onClose(); // Close the node selection panel when goto panel opens
      }
    }, [onOpenGotoPanel, selectedNode, onClose]);

    const handleResetConfirmClose = useCallback(() => {
      setShowResetConfirm(false);
    }, []);

    const handleResetButtonClick = useCallback((e: React.MouseEvent) => {
      (e.currentTarget as HTMLElement).blur(); // Remove focus from the button before opening dialog
      setShowResetConfirm(true);
    }, []);

    const handleScreenshotConfirmClose = useCallback(() => {
      setShowScreenshotConfirm(false);
    }, []);

    // Is the selected node a variant node (carries a per-variant override, or is
    // variant-only) in the current viewing scope? useResolvedTree stamps
    // `_show_variant_chip` on exactly those nodes when the canvas is on a
    // variant; base view never sets it. Drives the panel's blue border + "v"
    // badge so a variant node's panel is visually distinct from a base one.
    const isVariantNode = (selectedNode.data as any)?._show_variant_chip === true;

    return (
      <>
        <Paper
          sx={{
            position: 'absolute',
            top: 16,
            right: 16,
            width: 340,
            p: 1.5,
            zIndex: getZIndex('NAVIGATION_SELECTION_PANEL'),
            // Variant node → blue outline so the panel is unmistakably a
            // variant's (matches the canvas "v" badge colour). Base → white.
            border: isVariantNode ? '2px solid #1976d2' : '1px solid white',
            borderLeft: `4px solid ${nodeColors.border}`, // Show confidence color as left border
          }}
          onClick={handlePaperClick}
        >
          <Box>
            <Box
              sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}
            >
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: 1 }}>
                {/* Variant "v" badge — only on a variant node, matching the
                    canvas node chip so the panel's scope is obvious. */}
                {isVariantNode && (
                  <Typography
                    variant="caption"
                    sx={{
                      fontSize: '0.75rem',
                      fontWeight: 'bold',
                      color: '#fff',
                      backgroundColor: '#1976d2',
                      padding: '2px 7px',
                      borderRadius: '4px',
                      lineHeight: 1.2,
                    }}
                  >
                    v
                  </Typography>
                )}
                {/* Success Rate */}
                <Typography
                  variant="caption"
                  sx={{
                    fontSize: '0.75rem',
                    fontWeight: 'bold',
                    color: metricsDisplay.successRateColor,
                    padding: '2px 6px',
                    borderRadius: '4px',
                    backgroundColor: 'rgba(255,255,255,0.1)',
                  }}
                >
                  {metricsDisplay.successRateText}
                </Typography>

                {/* Verify duration */}
                <Typography
                  variant="caption"
                  sx={{
                    fontSize: '0.75rem',
                    fontWeight: 'bold',
                    color: '#666',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    backgroundColor: 'rgba(255,255,255,0.1)',
                  }}
                  title="Average verify_node() duration on this node"
                >
                  {metricsDisplay.timeText}
                </Typography>

                {/* Volume */}
                <Typography
                  variant="caption"
                  sx={{
                    fontSize: '0.75rem',
                    fontWeight: 'bold',
                    color: '#666',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    backgroundColor: 'rgba(255,255,255,0.1)',
                  }}
                >
                  #{metricsDisplay.volumeText}
                </Typography>

                {/* Confidence score — same size as the rest, aligned left
                    so this panel mirrors the Edge panel layout. Nodes don't
                    carry KPI, so the right side stays empty (just close X). */}
                <Typography
                  variant="caption"
                  sx={{
                    fontSize: '0.75rem',
                    fontWeight: 'bold',
                    color: metricsDisplay.confidenceColor,
                    padding: '2px 6px',
                    borderRadius: '4px',
                    backgroundColor: 'rgba(255,255,255,0.1)',
                    border: `1px solid ${metricsDisplay.confidenceColor}`,
                    minWidth: '28px',
                    textAlign: 'center',
                  }}
                  title="Confidence score (0–10)"
                >
                  {metricsDisplay.confidenceScore}
                </Typography>
              </Box>

              <IconButton size="small" onClick={handleCloseClick} sx={{ p: 0.25 }}>
                <CloseIcon fontSize="small" />
              </IconButton>
            </Box>

            {/* Node name + Parent/Depth — mirrors EdgeSelectionPanel's
                "from → to … Final wait" row so the two panels read the same. */}
            <Box sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography
                variant="body2"
                title={selectedNode.data.label}
                sx={{
                  fontSize: '0.8rem',
                  fontWeight: 'bold',
                  color: '#4caf50',
                  minWidth: 0,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {selectedNode.data.label}
              </Typography>
              <Typography
                variant="caption"
                title={`Parent: ${parentNames} - Depth: ${selectedNode.data.depth || 0}`}
                sx={{
                  ml: 'auto',
                  fontSize: '0.7rem',
                  color: 'text.secondary',
                  minWidth: 0,
                  maxWidth: '60%',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                <strong>Parent:</strong> {parentNames} - <strong>Depth:</strong>{' '}
                {selectedNode.data.depth || 0}
              </Typography>
            </Box>

            <Box sx={{ mt: 0.5, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
              {/* Edit and Delete buttons */}
              <Box sx={{ display: 'flex', gap: 0.5 }}>
                <Button
                  size="small"
                  variant="outlined"
                  sx={{ fontSize: '0.75rem', px: 1, flex: 1 }}
                  onClick={handleEdit}
                  disabled={!isControlActive || !selectedHost}
                  title={
                    !isControlActive || !selectedHost ? 'Device control required to edit nodes' : ''
                  }
                >
                  Edit
                </Button>
                {/* Only show delete button if not a protected node */}
                {!isProtected && (
                  <Button
                    size="small"
                    variant="outlined"
                    color="error"
                    sx={{ fontSize: '0.75rem', px: 1, flex: 1 }}
                    onClick={onDelete}
                  >
                    Delete
                  </Button>
                )}
              </Box>

              {/* Reset button */}
              {onReset && (
                <Button
                  size="small"
                  variant="outlined"
                  color="warning"
                  sx={{ fontSize: '0.75rem', px: 1 }}
                  onClick={handleResetButtonClick}
                >
                  Reset Node
                </Button>
              )}

              {/* Save Screenshot button - only shown when device is under control */}
              {showSaveScreenshotButton && (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Button
                    size="small"
                    variant="outlined"
                    color="primary"
                    sx={{ fontSize: '0.75rem', px: 1, flex: 1 }}
                    onClick={handleScreenshotButtonClick}
                    startIcon={<CameraIcon fontSize="small" />}
                  >
                    Screenshot
                  </Button>
                  {/* Success indicator */}
                  {nodeHook.screenshotSaveStatus === 'success' && (
                    <CheckCircleIcon
                      fontSize="small"
                      sx={{
                        color: 'success.main',
                        animation: 'fadeIn 0.3s ease-in',
                      }}
                    />
                  )}
                </Box>
              )}

              {/* Go To button - only shown for non-root nodes when device is under control */}
              {showGoToButton && (
                <Button
                  size="small"
                  variant="outlined"
                  color="primary"
                  sx={{ fontSize: '0.75rem', px: 1 }}
                  onClick={handleGoToButtonClick}
                  startIcon={<RouteIcon fontSize="small" />}
                >
                  Go To
                </Button>
              )}
            </Box>
          </Box>
        </Paper>

        {/* Reset Node Confirmation Dialog */}
        <StyledDialog
          open={showResetConfirm}
          onClose={handleResetConfirmClose}
          disableRestoreFocus
          sx={{ zIndex: getZIndex('NAVIGATION_CONFIRMATION') }}
        >
          <DialogTitle>Reset Node</DialogTitle>
          <DialogContent>
            <Typography>Are you sure you want to reset this node ?</Typography>
          </DialogContent>
          <DialogActions>
            <Button onClick={handleResetConfirmClose}>Cancel</Button>
            <Button onClick={handleResetConfirm} color="warning" variant="contained">
              Confirm
            </Button>
          </DialogActions>
        </StyledDialog>

        {/* Screenshot Confirmation Dialog */}
        <StyledDialog
          open={showScreenshotConfirm}
          onClose={handleScreenshotConfirmClose}
          disableRestoreFocus
          sx={{ zIndex: getZIndex('NAVIGATION_CONFIRMATION') }}
        >
          <DialogTitle>Take Screenshot</DialogTitle>
          <DialogContent>
            <Typography>
              Are you sure you want to take a screenshot ?<br />
              This will overwrite the current screenshot.
            </Typography>
          </DialogContent>
          <DialogActions>
            <Button onClick={handleScreenshotConfirmClose}>Cancel</Button>
            <Button onClick={handleScreenshotConfirm} color="primary" variant="contained">
              Confirm
            </Button>
          </DialogActions>
        </StyledDialog>
      </>
    );
  }
);
