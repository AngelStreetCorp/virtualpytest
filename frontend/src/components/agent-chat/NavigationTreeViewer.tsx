/**
 * Navigation Tree Viewer - Embedded ReactFlow viewer for navigation trees
 * 
 * A simplified version of NavigationEditor for embedding in ContentViewer.
 * Shows the navigation tree without headers, panels, or full-page layout.
 */

import React, { useEffect, useMemo, useCallback, useState } from 'react';
import { Box, Typography, CircularProgress, Button } from '@mui/material';
import { Tv as TvIcon } from '@mui/icons-material';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  BackgroundVariant,
  MarkerType,
  ConnectionLineType,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { useTheme } from '@mui/material/styles';
import { AGENT_CHAT_PALETTE as PALETTE } from '../../constants/agentChatTheme';
import { useDeviceData } from '../../contexts/device/DeviceDataContext';

// Import navigation components and contexts
import { NavigationConfigProvider, useNavigationConfig } from '../../contexts/navigation/NavigationConfigContext';
import { NavigationEditorProvider } from '../../contexts/navigation/NavigationEditorProvider';
import { NavigationStackProvider } from '../../contexts/navigation/NavigationStackContext';
import { NavigationPreviewCacheProvider } from '../../contexts/navigation/NavigationPreviewCacheContext';
import { NavigationScreenshotProvider } from '../../contexts/navigation/NavigationScreenshotContext';
import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { useNavigationEditor } from '../../hooks/navigation/useNavigationEditor';
import { useNavigationBreadcrumb } from '../../hooks/navigation/useNavigationBreadcrumb';
import { useNestedNavigation } from '../../hooks/navigation/useNestedNavigation';
import { useUserInterface } from '../../hooks/pages/useUserInterface';
import { useNavigationStack } from '../../contexts/navigation/NavigationStackContext';
import { useEdge } from '../../hooks/navigation/useEdge';
import { useNode } from '../../hooks/navigation/useNode';
import { useHostControl } from '../../hooks/useHostManager';

// Import node/edge components from NavigationEditor
import { UINavigationNode } from '../navigation/Navigation_NavigationNode';
import { UIActionNode } from '../navigation/Navigation_ActionNode';
import { NavigationEdgeComponent } from '../navigation/Navigation_NavigationEdge';

// Import unified interactive components
import { EdgeSelectionPanel } from '../navigation/Navigation_EdgeSelectionPanel';
import { NodeSelectionPanel } from '../navigation/Navigation_NodeSelectionPanel';
import { NodeGotoPanel } from '../navigation/Navigation_NodeGotoPanel';
import { NavigationBreadcrumbCompact } from '../navigation/NavigationBreadcrumbCompact';

// Import edit dialogs
import { NodeEditDialog } from '../navigation/Navigation_NodeEditDialog';
import { EdgeEditDialog } from '../navigation/Navigation_EdgeEditDialog';

// Import types
import {
  UINavigationNode as UINavigationNodeType,
  NodeForm,
  EdgeForm,
} from '../../types/pages/Navigation_Types';

// Import utilities
import { getZIndex } from '../../utils/zIndexUtils';

// Node types for React Flow
const nodeTypes = {
  screen: UINavigationNode,
  menu: UINavigationNode,
  action: UIActionNode,
  entry: UINavigationNode,
};

const edgeTypes = {
  navigation: NavigationEdgeComponent,
  smoothstep: NavigationEdgeComponent,
};


const defaultEdgeOptions = {
  type: 'navigation',
  animated: false,
  style: { strokeWidth: 2, stroke: '#b1b1b7' },
  markerEnd: {
    type: MarkerType.ArrowClosed,
    width: 20,
    height: 20,
    color: '#b1b1b7',
  },
};

const proOptions = { hideAttribution: true };

interface NavigationTreeViewerProps {
  userInterfaceName: string;
  readOnly?: boolean;
  // Interactive mode props (only used when readOnly = false)
  selectedHost?: any;
  selectedDeviceId?: string;
  isControlActive?: boolean;
  currentNodeId?: string;
}

// Inner content component that uses the hooks
const NavigationTreeViewerContent: React.FC<NavigationTreeViewerProps> = ({
  userInterfaceName,
  readOnly = true,
  selectedHost: propSelectedHost,
  selectedDeviceId: propSelectedDeviceId,
  isControlActive: propIsControlActive,
  currentNodeId,
}) => {
  const theme = useTheme();
  const isDarkMode = theme.palette.mode === 'dark';

  // Get control state from context (authoritative source)
  const { isControlActive: contextIsControlActive, selectedHost: contextSelectedHost, selectedDeviceId: contextSelectedDeviceId } = useHostControl();


  // Control Button Component - positioned in top right of React Flow
  const ControlButton: React.FC = () => {
    const {
      selectedHost,
      selectedDeviceId,
      isControlActive,
      takeControl,
      releaseControl,
      handleControlStateChange,
    } = useHostControl();

    // Local loading state for button
    const [isLoading, setIsLoading] = useState(false);

    const handleControlToggle = useCallback(async () => {
      if (!selectedHost || !selectedDeviceId) {
        console.log('[@NavigationTreeViewer:ControlButton] No host/device selected');
        return;
      }

      // Prevent multiple clicks while operation is in progress
      if (isLoading) {
        console.log('[@NavigationTreeViewer:ControlButton] Operation already in progress');
        return;
      }

      setIsLoading(true);
      try {
        if (isControlActive) {
          console.log('[@NavigationTreeViewer:ControlButton] Releasing control');
          const result = await releaseControl(selectedHost, selectedDeviceId);
          if (result.success) {
            handleControlStateChange(false);
          }
        } else {
          console.log('[@NavigationTreeViewer:ControlButton] Taking control');
          const result = await takeControl(selectedHost, selectedDeviceId, undefined, actualTreeId || undefined);
          if (result.success) {
            handleControlStateChange(true);
          }
        }
      } catch (error) {
        console.error('[@NavigationTreeViewer:ControlButton] Control operation failed:', error);
      } finally {
        setIsLoading(false);
      }
    }, [selectedHost, selectedDeviceId, isControlActive, takeControl, releaseControl, actualTreeId, isLoading]);

    return (
      <Button
        variant={isControlActive ? 'contained' : 'outlined'}
        size="small"
        onClick={handleControlToggle}
        disabled={!selectedHost || !selectedDeviceId || isLoading}
        startIcon={isLoading ? <CircularProgress size={16} /> : <TvIcon />}
        color={isControlActive ? 'success' : 'primary'}
        sx={{
          position: 'absolute',
          top: 16,
          right: 16,
          height: 32,
          fontSize: '0.7rem',
          minWidth: 100,
          whiteSpace: 'nowrap',
          px: 1.5,
          zIndex: 10,
          boxShadow: 2,
        }}
        title={
          isLoading
            ? 'Processing...'
            : !selectedHost || !selectedDeviceId
              ? 'Select a device first'
              : isControlActive
                ? 'Release Control'
                : 'Take Control'
        }
      >
        {isLoading ? 'Processing...' : isControlActive ? 'Release' : 'Control'}
      </Button>
    );
  };

  // Navigation contexts and hooks
  const { setActualTreeId, actualTreeId } = useNavigationConfig();
  const { getUserInterfaceByName } = useUserInterface();
  const navigation = useNavigation();
  // Get navigation stack for nested navigation
  const { isNested } = useNavigationStack();

  // Shared navigation breadcrumb functionality (no code duplication)
  const { handleNavigateBack, handleNavigateToLevel, handleNavigateToRoot } = useNavigationBreadcrumb();

  // Sync device selection with DeviceDataContext so available actions/verifications load
  const { setControlState } = useDeviceData();

  // Use context values as primary, fall back to props for backward compatibility
  const isControlActive = contextIsControlActive !== undefined ? contextIsControlActive : (propIsControlActive ?? false);
  const selectedHost = contextSelectedHost || propSelectedHost;
  const selectedDeviceId = contextSelectedDeviceId || propSelectedDeviceId;

  // Sync device selection with DeviceDataContext to enable action/verification loading
  useEffect(() => {
    setControlState(selectedHost, selectedDeviceId || null, isControlActive);
  }, [selectedHost, selectedDeviceId, isControlActive, setControlState]);

  // Store userInterface locally for model access
  const [userInterface, setUserInterface] = useState<any>(null);

  // Interactive state (only used when not readOnly)
  const [showGotoPanel, setShowGotoPanel] = useState(false);
  const [selectedNodeForGoto, setSelectedNodeForGoto] = useState<UINavigationNodeType | null>(null);

  // Edge labels state for dialog
  const [edgeLabels] = useState<{ fromLabel: string; toLabel: string }>({
    fromLabel: '',
    toLabel: '',
  });

  // Unified navigation editor hook
  const {
    nodes,
    edges,
    selectedNode,
    selectedEdge,
    isLoadingInterface,
    error,
    loadTreeByUserInterface,
    setUserInterfaceFromProps,
    setReactFlowInstance,
    onNodesChange,
    onEdgesChange,
    onConnect,
    onNodeClick,
    onEdgeClick,
    onPaneClick,
    closeSelectionPanel,
    deleteSelected,
    saveNodeWithStateUpdate,
    saveEdgeWithStateUpdate,
    resetNode,
    cancelNodeChanges,
    setNodes,
    setEdges,
    setSelectedNode,
    setHasUnsavedChanges,
    // Form and dialog state
    nodeForm,
    setNodeForm,
    edgeForm,
    setEdgeForm,
    isNodeDialogOpen,
    setIsNodeDialogOpen,
    isEdgeDialogOpen,
    setIsEdgeDialogOpen,
  } = useNavigationEditor();

  // Initialize nested navigation hook for unified double-click handling
  const nestedNavigation = useNestedNavigation({
    setNodes,
    setEdges,
    openNodeDialog: navigation.openNodeDialog,
  });

  // Edge hook for verification (only when interactive)
  const edgeHook = useEdge({
    selectedHost: !readOnly && selectedEdge ? (selectedHost || null) : null,
    selectedDeviceId: !readOnly && selectedEdge ? (selectedDeviceId || null) : null,
    isControlActive: !readOnly && selectedEdge ? isControlActive : false,
    treeId: actualTreeId,
  });

  // Node hook for interactive operations (only when not readOnly)
  const nodeHook = useNode(!readOnly ? {
    selectedHost,
    selectedDeviceId,
    isControlActive,
    treeId: actualTreeId || undefined,
    currentNodeId,
  } : undefined);


  // Goto panel handlers
  const handleOpenGotoPanel = useCallback((node: UINavigationNodeType) => {
    setSelectedNodeForGoto(node);
    setShowGotoPanel(true);
  }, []);

  const handleCloseGotoPanel = useCallback(() => {
    setShowGotoPanel(false);
    setSelectedNodeForGoto(null);
  }, []);

  // Helper functions using new normalized API (same as NavigationEditor.tsx)
  const handleUpdateNode = useCallback(
    (nodeId: string, updatedData: any) => {
      const updatedNodes = nodes.map((node) =>
        node.id === nodeId ? { ...node, data: { ...node.data, ...updatedData } } : node,
      );
      setNodes(updatedNodes);
      if (selectedNode?.id === nodeId) {
        setSelectedNode({ ...selectedNode, data: { ...selectedNode.data, ...updatedData } });
      }
      setHasUnsavedChanges(true);
    },
    [nodes, setNodes, setSelectedNode, setHasUnsavedChanges, selectedNode],
  );

  // Wrapper for node form submission to handle the form data (same as NavigationEditor.tsx)
  const handleNodeFormSubmitWrapper = useCallback(() => {
    if (nodeForm) {
      console.log(
        '[@component:NavigationEditor] Submitting node form with verifications:',
        nodeForm.verifications?.length || 0,
        nodeForm.verifications,
      );
      saveNodeWithStateUpdate(nodeForm);
      console.log('[@component:NavigationEditor] Node form submitted successfully');
    }
  }, [nodeForm, saveNodeWithStateUpdate]);


  // Wrapped event handlers for goto panel management
  const wrappedOnNodeClick = useCallback(
    (event: React.MouseEvent, node: any) => {
      console.log('[@NavigationTreeViewer:wrappedOnNodeClick] Click detected!', {
        readOnly,
        nodeId: node?.id,
        nodeType: node?.type,
        eventType: event.type,
        eventTarget: event.target,
        showGotoPanel
      });

      // Close goto panel if it's open
      if (showGotoPanel) {
        console.log('[@NavigationTreeViewer:wrappedOnNodeClick] Closing goto panel');
        setShowGotoPanel(false);
        setSelectedNodeForGoto(null);
      }

      // Call the original handler
      if (!readOnly) {
        console.log('[@NavigationTreeViewer:wrappedOnNodeClick] Calling onNodeClick handler');
        onNodeClick(event, node);
      } else {
        console.log('[@NavigationTreeViewer:wrappedOnNodeClick] Skipping onNodeClick - readOnly mode');
      }
    },
    [onNodeClick, showGotoPanel, readOnly],
  );

  const wrappedOnEdgeClick = useCallback(
    (event: React.MouseEvent, edge: any) => {
      console.log('[@NavigationTreeViewer:wrappedOnEdgeClick] Click detected!', {
        readOnly,
        edgeId: edge?.id,
        source: edge?.source,
        target: edge?.target,
        eventType: event.type,
        eventTarget: event.target,
        showGotoPanel
      });

      // Close goto panel if it's open
      if (showGotoPanel) {
        console.log('[@NavigationTreeViewer:wrappedOnEdgeClick] Closing goto panel');
        setShowGotoPanel(false);
        setSelectedNodeForGoto(null);
      }

      // Call the original handler
      if (!readOnly) {
        console.log('[@NavigationTreeViewer:wrappedOnEdgeClick] Calling onEdgeClick handler');
        onEdgeClick(event, edge);
      } else {
        console.log('[@NavigationTreeViewer:wrappedOnEdgeClick] Skipping onEdgeClick - readOnly mode');
      }
    },
    [onEdgeClick, showGotoPanel, readOnly],
  );

  const wrappedOnPaneClick = useCallback(() => {
    // Close goto panel if it's open
    if (showGotoPanel) {
      setShowGotoPanel(false);
      setSelectedNodeForGoto(null);
    }
    // Call the original handler
    if (!readOnly) {
      onPaneClick();
    }
  }, [onPaneClick, showGotoPanel, readOnly]);

  // Load tree by userinterface name
  useEffect(() => {
    const loadTree = async () => {
      if (!userInterfaceName) return;

      try {
        console.log(`[NavigationTreeViewer] Loading tree for: ${userInterfaceName}`);
        const resolvedInterface = await getUserInterfaceByName(userInterfaceName);
        setUserInterface(resolvedInterface); // Store locally for model access
        setUserInterfaceFromProps(resolvedInterface);

        const result = await loadTreeByUserInterface(resolvedInterface.id);
        if (result?.tree?.id) {
          setActualTreeId(result.tree.id);
        }
      } catch (err) {
        console.error('[NavigationTreeViewer] Failed to load tree:', err);
      }
    };

    loadTree();
  }, [userInterfaceName]);

  // Debug logging for state changes
  useEffect(() => {
    console.log('[@NavigationTreeViewer] State changed:', {
      readOnly,
      nodesCount: nodes.length,
      edgesCount: edges.length,
      selectedNode: selectedNode?.id,
      selectedEdge: selectedEdge?.id,
      userInterfaceName,
      actualTreeId
    });
  }, [readOnly, nodes.length, edges.length, selectedNode?.id, selectedEdge?.id, userInterfaceName, actualTreeId]);

  // MiniMap node color
  const miniMapNodeColor = useCallback((node: any) => {
    switch (node.data?.type) {
      case 'screen': return '#3b82f6';
      case 'dialog': return '#8b5cf6';
      case 'popup': return '#f59e0b';
      case 'overlay': return '#10b981';
      case 'menu': return '#ffc107';
      case 'entry': return '#ef4444';
      default: return '#6b7280';
    }
  }, []);

  const miniMapStyle = useMemo(() => ({
    backgroundColor: isDarkMode ? '#1f2937' : '#ffffff',
    border: `1px solid ${isDarkMode ? '#374151' : '#e5e7eb'}`,
    borderRadius: '4px',
  }), [isDarkMode]);

  if (isLoadingInterface) {
    return (
      <Box sx={{ 
        flex: 1, 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center',
        flexDirection: 'column',
        gap: 2,
      }}>
        <CircularProgress size={40} sx={{ color: PALETTE.accent }} />
        <Typography variant="body2" color="text.secondary">
          Loading navigation tree...
        </Typography>
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ 
        flex: 1, 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center',
        p: 4,
      }}>
        <Typography color="error">{error}</Typography>
      </Box>
    );
  }

  if (nodes.length === 0) {
    return (
      <Box sx={{ 
        flex: 1, 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center',
        flexDirection: 'column',
        gap: 1,
        p: 4,
      }}>
        <Typography variant="body1" color="text.secondary">
          No navigation tree found
        </Typography>
        <Typography variant="caption" color="text.disabled">
          {userInterfaceName}
        </Typography>
      </Box>
    );
  }

  return (
    <NavigationScreenshotProvider nodes={nodes}>
      <Box sx={{ flex: 1, width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
        {/* Breadcrumb navigation (when nested, same as NavigationEditor) */}
        {isNested && (
          <NavigationBreadcrumbCompact
            onNavigateBack={handleNavigateBack}
            onNavigateToLevel={handleNavigateToLevel}
            onNavigateToRoot={handleNavigateToRoot}
          />
        )}

        {/* ReactFlow container */}
        <Box sx={{ flex: 1, position: 'relative' }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            defaultEdgeOptions={defaultEdgeOptions}
            connectionLineType={ConnectionLineType.SmoothStep}
            onInit={(instance) => {
              console.log('[@NavigationTreeViewer] ReactFlow onInit called');
              setReactFlowInstance(instance);
              // Fit view on init
              setTimeout(() => instance.fitView({ padding: 0.2 }), 100);
            }}
            // Interactive features (conditional)
            onNodesChange={!readOnly ? onNodesChange : undefined}
            onEdgesChange={!readOnly ? onEdgesChange : undefined}
            onConnect={!readOnly ? onConnect : undefined}
            onNodeClick={wrappedOnNodeClick}
            onNodeDoubleClick={nestedNavigation.handleNodeDoubleClick}
            onEdgeClick={wrappedOnEdgeClick}
            onPaneClick={wrappedOnPaneClick}
            // Disable React Flow's built-in selection to prevent conflicts
            elementsSelectable={false}
            nodesDraggable={!readOnly}
            nodesConnectable={!readOnly}
            panOnDrag={true}
            zoomOnScroll={true}
            zoomOnPinch={true}
            proOptions={proOptions}
            fitView
          >
            <Background variant={BackgroundVariant.Dots} gap={15} size={1} />
            <Controls position="top-left" showInteractive={!readOnly} />
            <MiniMap
              style={miniMapStyle}
              nodeColor={miniMapNodeColor}
              maskColor="rgba(255, 255, 255, 0.2)"
              pannable
              zoomable
              position="bottom-right"
            />
          </ReactFlow>

          {/* Control Button (only when not readOnly) */}
          {!readOnly && <ControlButton />}

          {/* Interactive panels (only when not readOnly) */}
          {!readOnly && (
            <>
              {/* Node Selection Panel */}
              {selectedNode && (
                <Box
                  sx={{
                    position: 'absolute',
                    top: 16,
                    right: 16,
                    zIndex: getZIndex('NAVIGATION_SELECTION_PANEL'),
                    transform: 'scale(0.85)',
                    transformOrigin: 'top right',
                  }}
                >
                  <NodeSelectionPanel
                    selectedNode={selectedNode}
                    nodes={nodes}
                    onClose={closeSelectionPanel}
                    onDelete={deleteSelected}
                    setNodeForm={setNodeForm as React.Dispatch<React.SetStateAction<NodeForm>>} // Real form handler from useNavigationEditor
                    setIsNodeDialogOpen={setIsNodeDialogOpen} // Real dialog handler from useNavigationEditor
                    onReset={() => {}} // Keep stub - not implemented in useNode
                    onUpdateNode={nodeHook?.takeAndSaveScreenshot} // Real screenshot handler from useNode
                    isControlActive={isControlActive}
                    selectedHost={selectedHost || undefined}
                    selectedDeviceId={selectedDeviceId || undefined}
                    treeId={actualTreeId || ''}
                    currentNodeId={currentNodeId || undefined}
                    onOpenGotoPanel={handleOpenGotoPanel}
                  />
                </Box>
              )}

              {/* Edge Selection Panels */}
              {selectedEdge && (() => {
                // Same edge panel rendering logic as NavigationEditor
                const edgesToShow = [selectedEdge];
                let panelIndexOffset = 0;

                return edgesToShow.map((edge) => {
                  const displayActionSets = edgeHook?.getDisplayActionSets(edge) || [];
                  const panels = [];

                  if (displayActionSets.length > 0) {
                      displayActionSets.forEach((actionSet: any, actionSetIndex: number) => {
                        panels.push(
                          <Box
                            key={`${edge.id}-${actionSet.id}-${panelIndexOffset + actionSetIndex}`}
                            sx={{
                              position: 'absolute',
                              top: 16,
                              right: 16 + (panelIndexOffset + actionSetIndex) * 20,
                              zIndex: getZIndex('NAVIGATION_EDGE_PANEL') + (panelIndexOffset + actionSetIndex),
                              transform: 'scale(0.85)',
                              transformOrigin: 'top right',
                            }}
                          >
                            <EdgeSelectionPanel
                              selectedEdge={edge}
                              actionSet={actionSet}
                              panelIndex={panelIndexOffset + actionSetIndex}
                              onClose={closeSelectionPanel}
                              onEdit={() => setIsEdgeDialogOpen(true)} // Real edit handler from useNavigationEditor
                              onDelete={() => navigation.deleteEdgeDirection(edge.id, actionSet.id)}
                              setEdgeForm={setEdgeForm as React.Dispatch<React.SetStateAction<EdgeForm>>} // Real form handler from useNavigationEditor
                              setIsEdgeDialogOpen={setIsEdgeDialogOpen} // Real dialog handler from useNavigationEditor
                              isControlActive={isControlActive}
                              selectedHost={selectedHost || undefined}
                              selectedDeviceId={selectedDeviceId || undefined}
                              onEditWithLabels={() => {}} // Keep stub - not implemented
                              currentEdgeForm={null}
                              edgeMetrics={null}
                              treeId={actualTreeId}
                            />
                          </Box>
                        );
                      });

                    const isActionEdge = edgeHook?.isActionEdge(edge) || false;
                    if (!isActionEdge && edge.data.action_sets.length < 2) {
                      panels.push(
                        <Box
                          key={`${edge.id}-fallback`}
                          sx={{
                            position: 'absolute',
                            top: 16,
                            right: 16 + (panelIndexOffset + displayActionSets.length) * 20,
                            zIndex: getZIndex('NAVIGATION_EDGE_PANEL') + (panelIndexOffset + displayActionSets.length),
                            transform: 'scale(0.85)',
                            transformOrigin: 'top right',
                          }}
                        >
                          <EdgeSelectionPanel
                            selectedEdge={edge}
                            actionSet={null}
                            panelIndex={panelIndexOffset + displayActionSets.length}
                            onClose={closeSelectionPanel}
                            onEdit={() => setIsEdgeDialogOpen(true)} // Real edit handler from useNavigationEditor
                            onDelete={() => deleteSelected}
                            setEdgeForm={setEdgeForm as React.Dispatch<React.SetStateAction<EdgeForm>>} // Real form handler from useNavigationEditor
                            setIsEdgeDialogOpen={setIsEdgeDialogOpen} // Real dialog handler from useNavigationEditor
                            isControlActive={isControlActive}
                            selectedHost={selectedHost || undefined}
                            selectedDeviceId={selectedDeviceId || undefined}
                            onEditWithLabels={() => {}} // Keep stub - not implemented
                            currentEdgeForm={null}
                            edgeMetrics={null}
                            treeId={actualTreeId}
                          />
                        </Box>
                      );
                      panelIndexOffset += 2;
                    } else {
                      panelIndexOffset += displayActionSets.length;
                    }
                  } else {
                    panels.push(
                      <Box
                        key={`${edge.id}-fallback`}
                        sx={{
                          position: 'absolute',
                          top: 16,
                          right: 16 + panelIndexOffset * 20,
                          zIndex: getZIndex('NAVIGATION_EDGE_PANEL') + panelIndexOffset,
                          transform: 'scale(0.85)',
                          transformOrigin: 'top right',
                        }}
                      >
                        <EdgeSelectionPanel
                          selectedEdge={edge}
                          actionSet={null}
                          panelIndex={panelIndexOffset}
                          onClose={closeSelectionPanel}
                          onEdit={() => setIsEdgeDialogOpen(true)} // Real edit handler from useNavigationEditor
                          onDelete={deleteSelected}
                          setEdgeForm={setEdgeForm as React.Dispatch<React.SetStateAction<EdgeForm>>} // Real form handler from useNavigationEditor
                          setIsEdgeDialogOpen={setIsEdgeDialogOpen} // Real dialog handler from useNavigationEditor
                          isControlActive={isControlActive}
                          selectedHost={selectedHost || undefined}
                          selectedDeviceId={selectedDeviceId || undefined}
                          onEditWithLabels={() => {}} // Keep stub - not implemented
                          currentEdgeForm={null}
                          edgeMetrics={null}
                          treeId={actualTreeId}
                        />
                      </Box>
                    );
                    panelIndexOffset += 1;
                  }

                  return panels;
                }).flat();
              })()}

              {/* Node Goto Panel */}
              {showGotoPanel && selectedNodeForGoto && actualTreeId && (
                <Box
                  sx={{
                    position: 'absolute',
                    top: 16,
                    right: 16,
                    zIndex: getZIndex('NAVIGATION_GOTO_PANEL'),
                    transform: 'scale(0.7)',
                    transformOrigin: 'top right',
                  }}
                >
                  <NodeGotoPanel
                    selectedNode={selectedNodeForGoto}
                    nodes={nodes}
                    treeId={actualTreeId}
                    onClose={handleCloseGotoPanel}
                    currentNodeId={currentNodeId || undefined}
                    selectedHost={selectedHost || undefined}
                    selectedDeviceId={selectedDeviceId || undefined}
                    isControlActive={isControlActive}
                  />
                </Box>
              )}
            </>
          )}
        </Box>
      </Box>

      {/* Edit Dialogs - exactly like NavigationEditor.tsx */}
      {isNodeDialogOpen && (
        <NodeEditDialog
          isOpen={isNodeDialogOpen}
          nodeForm={nodeForm}
          nodes={nodes}
          setNodeForm={setNodeForm as (form: NodeForm | null) => void}
          onSubmit={handleNodeFormSubmitWrapper}
          onClose={cancelNodeChanges}
          onResetNode={() => selectedNode && resetNode(selectedNode.id)}
          onUpdateNode={handleUpdateNode}
          model={userInterface?.models?.[0] || 'android_mobile'}
          isControlActive={isControlActive}
          selectedHost={selectedHost}
          selectedDeviceId={selectedDeviceId || undefined}
        />
      )}

      {/* Edge Edit Dialog */}
      {isEdgeDialogOpen && selectedHost && (
        <EdgeEditDialog
          isOpen={isEdgeDialogOpen}
          edgeForm={edgeForm}
          setEdgeForm={setEdgeForm as any}
          onSubmit={saveEdgeWithStateUpdate}
          onClose={() => setIsEdgeDialogOpen(false)}
          selectedEdge={selectedEdge}
          isControlActive={isControlActive}
          selectedHost={selectedHost}
          selectedDeviceId={selectedDeviceId}
          fromLabel={edgeLabels.fromLabel}
          toLabel={edgeLabels.toLabel}
          model={userInterface?.models?.[0] || 'android_mobile'}
        />
      )}
    </NavigationScreenshotProvider>
  );
};

// Main component with providers
export const NavigationTreeViewer: React.FC<NavigationTreeViewerProps> = (props) => {
  if (!props.userInterfaceName) {
    return (
      <Box sx={{ 
        flex: 1, 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center',
        p: 4,
      }}>
        <Typography color="text.secondary">
          No user interface specified
        </Typography>
      </Box>
    );
  }

  return (
    <ReactFlowProvider>
      <NavigationConfigProvider>
        <NavigationPreviewCacheProvider>
          <NavigationEditorProvider>
            <NavigationStackProvider>
              <NavigationTreeViewerContent {...props} />
            </NavigationStackProvider>
          </NavigationEditorProvider>
        </NavigationPreviewCacheProvider>
      </NavigationConfigProvider>
    </ReactFlowProvider>
  );
};

export default NavigationTreeViewer;

