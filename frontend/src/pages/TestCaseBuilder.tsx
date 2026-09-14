import React, { useCallback, useRef, DragEvent, useState } from 'react';
import {
  Box,
  Button,
  Typography,
  DialogTitle,
  DialogContent,
  DialogActions,
  Alert,
  Snackbar
} from '@mui/material';
import { StyledDialog } from '../components/common/StyledDialog';
import ReactFlow, {
  ReactFlowProvider,
  MarkerType,
  addEdge,
} from 'reactflow';
import 'reactflow/dist/style.css';

// Auto-layout utility
import { getLayoutedElements } from '../components/testcase/ai/autoLayout';

// Hide React Flow attribution
const styles = TESTCASE_BUILDER_ATTRIBUTION_CSS;

// Components
import { TestCaseBuilderHeader } from '../components/testcase/builder/TestCaseBuilderHeader';
import { TestCaseBuilderSidebar } from '../components/testcase/builder/TestCaseBuilderSidebar';
import { TestCaseBuilderCanvas } from '../components/testcase/builder/TestCaseBuilderCanvas';
import { DeviceControlPanels } from '../components/common/DeviceControlPanels';
import { StartBlock } from '../components/testcase/blocks/StartBlock';
import { SuccessBlock } from '../components/testcase/blocks/SuccessBlock';
import { FailureBlock } from '../components/testcase/blocks/FailureBlock';
import { UniversalBlock } from '../components/testcase/blocks/UniversalBlock';
import { ApiCallBlock } from '../components/testcase/blocks/ApiCallBlock';
import { SuccessEdge } from '../components/testcase/edges/SuccessEdge';
import { FailureEdge } from '../components/testcase/edges/FailureEdge';
import { DataEdge } from '../components/testcase/edges/DataEdge';
// 🆕 NEW: Execution components - using unified component
import { ExecutionProgressOverlay } from '../components/common/ExecutionProgressOverlay';
import { VersionHistoryDialog, VersionHistoryRow } from '../components/common/VersionHistoryDialog';

// Dialogs
import { ActionConfigDialog } from '../components/testcase/dialogs/ActionConfigDialog';
import { LoopConfigDialog } from '../components/testcase/dialogs/LoopConfigDialog';
import { StandardBlockConfigDialog } from '../components/testcase/dialogs/StandardBlockConfigDialog';
import { ApiCallConfigModal } from '../components/testcase/dialogs/ApiCallConfigModal';
import { TestCaseBuilderDialogs } from '../components/testcase/builder/TestCaseBuilderDialogs';
import { AIGenerationResultPanel } from '../components/testcase/builder/AIGenerationResultPanel';
import { PromptDisambiguation } from '../components/ai/PromptDisambiguation';

// Shared Container Components
import {
  BuilderPageLayout,
  BuilderSidebarContainer,
  BuilderMainContainer,
  BuilderStatsBarContainer,
} from '../components/common/builder';

// Context
import { TestCaseBuilderProvider } from '../contexts/testcase/TestCaseBuilderContext';
import { NavigationEditorProvider } from '../contexts/navigation/NavigationEditorProvider';
import { NavigationConfigProvider } from '../contexts/navigation/NavigationConfigContext';
import { useTheme } from '../contexts/ThemeContext';
import { api } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';

// Hook
import { useTestCaseBuilderPage } from '../hooks/pages/useTestCaseBuilderPage';
import { useTestCaseBuilder } from '../contexts/testcase/TestCaseBuilderContext';

// Constants
import { TOAST_POSITION } from '../constants/toastConfig';
import { DEFAULT_VIEWPORT, ZOOM_CONSTRAINTS, FIT_VIEW_OPTIONS } from '../constants/builderDefaults';
import {
  FIT_VIEW_INITIAL_DELAY_MS,
  FIT_VIEW_ON_LOAD_DELAY_MS,
  FIT_VIEW_ON_NEW_DELAY_MS,
  STANDARD_BLOCK_TYPES,
  TESTCASE_BUILDER_ATTRIBUTION_CSS,
  getExecutionFooterSummary,
} from '../utils/testcase/testCaseBuilderUi';

// Node types for React Flow - memoized to prevent recreation warnings
const NODE_TYPES = {
  start: StartBlock,
  success: SuccessBlock,
  failure: FailureBlock,
  // Generic container types from toolboxBuilder
  action: UniversalBlock,
  verification: UniversalBlock,
  navigation: UniversalBlock,
  standard: UniversalBlock,
  // Specific command types use UniversalBlock
  press_key: UniversalBlock,
  press_sequence: UniversalBlock,
  tap: UniversalBlock,
  swipe: UniversalBlock,
  type_text: UniversalBlock,
  verify_image: UniversalBlock,
  verify_ocr: UniversalBlock,
  verify_audio: UniversalBlock,
  verify_element: UniversalBlock,
  condition: UniversalBlock,
  container: UniversalBlock,
  set_variable: UniversalBlock,
  set_variable_io: UniversalBlock,
  set_metadata: UniversalBlock,
  getMenuInfo: UniversalBlock,
  sleep: UniversalBlock,
  get_current_time: UniversalBlock,
  generate_random: UniversalBlock,
  http_request: UniversalBlock,
  loop: UniversalBlock,
  // Standard blocks
  custom_code: UniversalBlock,
  common_operation: UniversalBlock,
  evaluate_condition: UniversalBlock,
  // API blocks
  api_call: ApiCallBlock,
};

// Edge types for React Flow - memoized to prevent recreation warnings
const EDGE_TYPES = {
  success: SuccessEdge,
  failure: FailureEdge,
  true: SuccessEdge,
  false: FailureEdge,
  complete: SuccessEdge,
  break: FailureEdge,
  data: DataEdge, // NEW: Data flow edges
};

// Default edge options
const defaultEdgeOptions = {
  type: 'success',
  animated: false,
  style: {
    stroke: '#94a3b8', // grey
    strokeWidth: 2,
  },
  markerEnd: {
    type: MarkerType.ArrowClosed,
    width: 20,
    height: 20,
    color: '#94a3b8', // grey to match edge
  },
};

// Exported for embedding in ContentViewer
export const TestCaseBuilderContent: React.FC = () => {
  // Inject styles to hide React Flow attribution
  React.useEffect(() => {
    const styleTag = document.createElement('style');
    styleTag.innerHTML = styles;
    document.head.appendChild(styleTag);
    return () => {
      document.head.removeChild(styleTag);
    };
  }, []);

  const { actualMode } = useTheme();
  
  // 🗑️ REMOVED: Local execution overlay state - now using unifiedExecution from context
  
  // 🆕 NEW: Data linking state for click-to-link I/O
  const [dataLinkingState, setDataLinkingState] = useState<{
    active: boolean;
    sourceBlockId: string;
    sourceHandle: string;
    sourceType: 'input' | 'output';
  } | null>(null);
  
  // Use the consolidated hook for all business logic
  const hookData = useTestCaseBuilderPage();

  // Get undo/redo/copy/paste from context
  const { undo, redo, canUndo, canRedo, resetBuilder, copyBlock, pasteBlock } = useTestCaseBuilder();

  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [reactFlowInstance, setReactFlowInstance] = React.useState<any>(null);
  const fitViewTimerRef = useRef<number | null>(null);
  const resizeTimerRef = useRef<number | null>(null);

  // ✅ Listen for block config requests from InputDisplay chips
  React.useEffect(() => {
    const handleOpenBlockConfig = (event: CustomEvent) => {
      const blockId = event.detail?.blockId;
      if (blockId) {
        const node = hookData.nodes.find(n => n.id === blockId);
        if (node) {
          hookData.setSelectedBlock(node);
          hookData.setIsConfigDialogOpen(true);
        }
      }
    };
    
    window.addEventListener('openBlockConfig' as any, handleOpenBlockConfig);
    return () => window.removeEventListener('openBlockConfig' as any, handleOpenBlockConfig);
  }, [hookData.nodes, hookData.setSelectedBlock, hookData.setIsConfigDialogOpen]);

  // ✅ API Block Config Modal State
  const [apiConfigModalOpen, setApiConfigModalOpen] = React.useState(false);
  const [selectedApiBlock, setSelectedApiBlock] = React.useState<any>(null);
  const [versionDialogOpen, setVersionDialogOpen] = React.useState(false);
  const [versionRows, setVersionRows] = React.useState<VersionHistoryRow[]>([]);
  const [loadingVersions, setLoadingVersions] = React.useState(false);
  const [restoringVersion, setRestoringVersion] = React.useState<number | null>(null);

  // ✅ Listen for API block config requests
  React.useEffect(() => {
    const handleOpenApiBlockConfig = (event: CustomEvent) => {
      const blockId = event.detail?.blockId;
      if (blockId) {
        const node = hookData.nodes.find(n => n.id === blockId);
        if (node) {
          setSelectedApiBlock(node);
          setApiConfigModalOpen(true);
        }
      }
    };
    
    window.addEventListener('openApiBlockConfig' as any, handleOpenApiBlockConfig);
    return () => window.removeEventListener('openApiBlockConfig' as any, handleOpenApiBlockConfig);
  }, [hookData.nodes]);

  // Handle drop from toolbox
  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault();

      const dragDataStr = event.dataTransfer.getData('application/reactflow');
      
      if (!dragDataStr) {
        return;
      }

      try {
        const dragData = JSON.parse(dragDataStr);
        const { type, defaultData } = dragData;

        if (typeof type === 'undefined' || !type) {
          return;
        }

        const position = reactFlowInstance.screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        });

        hookData.addBlock(type, position, defaultData);
      } catch (error) {
        console.error('Invalid drag data format:', error);
      }
    },
    [reactFlowInstance, hookData.addBlock]
  );

  const onDragOver = useCallback((event: DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  // 🆕 NEW: Handle I/O handle clicks for data linking
  const handleDataHandleClick = useCallback((blockId: string, handleId: string, handleType: 'input' | 'output') => {
    if (handleType === 'output') {
      // Start linking mode from OUTPUT
      setDataLinkingState({
        active: true,
        sourceBlockId: blockId,
        sourceHandle: handleId,
        sourceType: 'output',
      });
      console.log('[@TestCaseBuilder] Data linking started from OUTPUT:', { blockId, handleId });
    } else if (handleType === 'input') {
      if (dataLinkingState?.active) {
        // Completing link: OUTPUT → INPUT
        
        // Prevent self-linking (same block)
        if (dataLinkingState.sourceBlockId === blockId) {
          console.log('[@TestCaseBuilder] Cannot link block to itself');
          setDataLinkingState(null);
          return;
        }
        
        // Create DATA edge
        console.log('[@TestCaseBuilder] Creating data edge (OUT → IN):', {
          source: dataLinkingState.sourceBlockId,
          target: blockId,
        });
        
        const newEdge = {
          id: `data-${dataLinkingState.sourceBlockId}-${blockId}-${Date.now()}`,
          source: dataLinkingState.sourceBlockId,
          sourceHandle: dataLinkingState.sourceHandle,
          target: blockId,
          targetHandle: handleId,
          type: 'data',
        };
        
        hookData.setEdges((eds: any) => addEdge(newEdge, eds));
        setDataLinkingState(null);
      } else {
        // IN clicked when NOT in linking mode → Open dialog to set static value
        console.log('[@TestCaseBuilder] Opening dialog to set static value for block:', blockId);
        // TODO: Open dialog to set static input value
        // For now, just log - dialog implementation will come later
      }
    }
  }, [dataLinkingState, hookData.setEdges]);

  // Cancel linking on Escape key
  React.useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && dataLinkingState?.active) {
        setDataLinkingState(null);
        console.log('[@TestCaseBuilder] Data linking cancelled');
      }
    };
    
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [dataLinkingState]);

  // Handle block single click - just select
  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: any) => {
      hookData.setSelectedBlock(node);
    },
    [hookData.setSelectedBlock]
  );

  // Handle block double click - open configuration dialog
  const onNodeDoubleClick = useCallback(
    (_event: React.MouseEvent, node: any) => {
      // Standard blocks: Open StandardBlockConfigDialog
      if (STANDARD_BLOCK_TYPES.includes(node.type)) {
        hookData.setSelectedBlock(node);
        hookData.setIsConfigDialogOpen(true);
      }
      // Other blocks use inline InputDisplay/OutputDisplay
    },
    [hookData.setSelectedBlock, hookData.setIsConfigDialogOpen]
  );

  // Handle config save
  const handleConfigSave = useCallback(
    (data: any) => {
      if (hookData.selectedBlock) {
        hookData.updateBlock(hookData.selectedBlock.id, data);
      }
      hookData.setIsConfigDialogOpen(false);
    },
    [hookData.selectedBlock, hookData.updateBlock, hookData.setIsConfigDialogOpen]
  );
  
  // Sidebar state
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  const fitViewOptions = React.useMemo(() => {
    const nodeCount = hookData.nodes.length;
    const basePadding = isSidebarOpen ? 0.24 : 0.18;
    const densityPadding = nodeCount > 12 ? 0.04 : 0;

    return {
      ...FIT_VIEW_OPTIONS,
      padding: Math.min(0.3, basePadding + densityPadding),
      maxZoom: 1,
    };
  }, [hookData.nodes.length, isSidebarOpen]);

  // Auto-layout handler - ALWAYS vertical (top to bottom)
  const handleAutoLayout = useCallback(() => {
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
      hookData.nodes,
      hookData.edges,
      { direction: 'TB' } // Force vertical layout
    );
    hookData.setNodes(layoutedNodes);
    hookData.setEdges(layoutedEdges);

  }, [hookData.nodes, hookData.edges, hookData.setNodes, hookData.setEdges, reactFlowInstance]);

  const scheduleFitView = useCallback(
    (delayMs: number) => {
      if (!reactFlowInstance) {
        return;
      }
      if (fitViewTimerRef.current) {
        window.clearTimeout(fitViewTimerRef.current);
      }
      fitViewTimerRef.current = window.setTimeout(() => {
        reactFlowInstance.fitView(fitViewOptions);
      }, delayMs);
    },
    [reactFlowInstance, fitViewOptions]
  );

  // Fit view when ReactFlow instance is ready
  React.useEffect(() => {
    if (reactFlowInstance) {
      scheduleFitView(FIT_VIEW_INITIAL_DELAY_MS);
    }
  }, [reactFlowInstance, scheduleFitView]);

  // Fit view when test case is loaded (when currentTestcaseId changes)
  React.useEffect(() => {
    if (reactFlowInstance && hookData.currentTestcaseId) {
      scheduleFitView(FIT_VIEW_ON_LOAD_DELAY_MS);
    }
  }, [reactFlowInstance, hookData.currentTestcaseId, scheduleFitView]);

  React.useEffect(() => {
    if (!reactFlowInstance) {
      return;
    }
    scheduleFitView(FIT_VIEW_ON_LOAD_DELAY_MS);
  }, [reactFlowInstance, isSidebarOpen, scheduleFitView]);

  // Browser zoom changes trigger viewport resize events; refit keeps blocks stable/readable.
  React.useEffect(() => {
    if (!reactFlowInstance) {
      return;
    }

    const handleResize = () => {
      if (resizeTimerRef.current) {
        window.clearTimeout(resizeTimerRef.current);
      }
      resizeTimerRef.current = window.setTimeout(() => {
        scheduleFitView(FIT_VIEW_ON_LOAD_DELAY_MS);
      }, 150);
    };

    window.addEventListener('resize', handleResize);
    return () => {
      if (resizeTimerRef.current) {
        window.clearTimeout(resizeTimerRef.current);
      }
      window.removeEventListener('resize', handleResize);
    };
  }, [reactFlowInstance, scheduleFitView]);

  React.useEffect(() => {
    return () => {
      if (fitViewTimerRef.current) {
        window.clearTimeout(fitViewTimerRef.current);
      }
      if (resizeTimerRef.current) {
        window.clearTimeout(resizeTimerRef.current);
      }
    };
  }, []);

  // Wrap handleNew to trigger fitView after reset
  const wrappedHandleNew = useCallback(() => {
    hookData.handleNew();
    scheduleFitView(FIT_VIEW_ON_NEW_DELAY_MS);
  }, [hookData.handleNew, scheduleFitView]);

  const loadTestCaseVersions = useCallback(async () => {
    if (!hookData.currentTestcaseId) return;
    setLoadingVersions(true);
    try {
      const response = await api.get<{ success: boolean; versions: VersionHistoryRow[] }>(
        buildServerUrl(`/server/testcase/${hookData.currentTestcaseId}/versions`),
      );
      if (!response?.success) {
        throw new Error('Failed to load version history');
      }
      setVersionRows(response.versions || []);
      setVersionDialogOpen(true);
    } catch (error) {
      hookData.setSnackbar({
        open: true,
        message: error instanceof Error ? error.message : 'Failed to load version history',
        severity: 'error',
      });
    } finally {
      setLoadingVersions(false);
    }
  }, [hookData]);

  const handleRestoreVersion = useCallback(async (versionNumber: number) => {
    if (!hookData.currentTestcaseId) return;
    const confirmed = window.confirm(`Restore test case version ${versionNumber} as the new latest version?`);
    if (!confirmed) return;

    setRestoringVersion(versionNumber);
    try {
      const response = await api.post<any>(
        buildServerUrl(`/server/testcase/${hookData.currentTestcaseId}/restore/${versionNumber}`),
      );
      if (!response?.success) {
        throw new Error(response?.error || 'Failed to restore version');
      }
      await hookData.handleLoad(hookData.currentTestcaseId);
      const refreshed = await api.get<{ success: boolean; versions: VersionHistoryRow[] }>(
        buildServerUrl(`/server/testcase/${hookData.currentTestcaseId}/versions`),
      );
      setVersionRows(refreshed.versions || []);
      setVersionDialogOpen(true);
      hookData.setSnackbar({
        open: true,
        message: `Restored version ${versionNumber} as version ${response.new_version}`,
        severity: 'success',
      });
    } catch (error) {
      hookData.setSnackbar({
        open: true,
        message: error instanceof Error ? error.message : 'Failed to restore version',
        severity: 'error',
      });
    } finally {
      setRestoringVersion(null);
    }
  }, [hookData]);

  return (
    <BuilderPageLayout>
      {/* Header */}
      <TestCaseBuilderHeader
        actualMode={actualMode}
        builderType="TestCase"
        creationMode={hookData.creationMode}
        setCreationMode={hookData.setCreationMode}
        selectedHost={hookData.selectedHost}
        selectedDeviceId={hookData.selectedDeviceId}
        isControlActive={hookData.isControlActive}
        isControlLoading={hookData.isControlLoading}
        isRemotePanelOpen={hookData.isRemotePanelOpen}
        availableHosts={hookData.availableHosts}
        isDeviceLocked={hookData.isDeviceLocked}
        handleDeviceSelect={hookData.handleDeviceSelect}
        handleDeviceControl={hookData.handleDeviceControl}
        handleToggleRemotePanel={hookData.handleToggleRemotePanel}
        compatibleInterfaceNames={hookData.compatibleInterfaceNames}
        userinterfaceName={hookData.userinterfaceName}
        setUserinterfaceName={hookData.setUserinterfaceName}
        isLoadingTree={hookData.isLoadingTree}
        testcaseName={hookData.testcaseName}
        hasUnsavedChanges={hookData.hasUnsavedChanges}
        handleNew={wrappedHandleNew}
        handleLoadClick={hookData.handleLoadClick}
        isLoadingTestCases={hookData.isLoadingTestCases}
        setSaveDialogOpen={hookData.setSaveDialogOpen}
        handleOpenVersions={loadTestCaseVersions}
        isVersionsEnabled={Boolean(hookData.currentTestcaseId)}
        handleExecute={hookData.handleExecute}
        isExecuting={hookData.executionState.isExecuting}
        isExecutable={hookData.isExecutable}
        onCloseProgressBar={() => hookData.unifiedExecution.resetExecution()}
        undo={undo}
        redo={redo}
        canUndo={canUndo}
        canRedo={canRedo}
        resetBuilder={resetBuilder}
        copyBlock={copyBlock}
        pasteBlock={pasteBlock}
      />

      {/* Main Container - Using shared container */}
      <BuilderMainContainer>
        {/* Execution Overlay (floating, non-blocking) */}
        <ExecutionProgressOverlay
          variant="testcase"
          currentBlockId={hookData.unifiedExecution.state.currentBlockId}
          blockStates={hookData.unifiedExecution.state.blockStates}
          isExecuting={hookData.unifiedExecution.state.isExecuting}
          nodes={hookData.nodes}
          executionResult={hookData.unifiedExecution.state.result}
          onStop={() => {
            // TODO: Implement stop execution
            console.log('Stop execution requested');
          }}
          onClose={() => {
            // User manually closes the progress bar
            hookData.unifiedExecution.resetExecution();
          }}
        />
        
        {/* Sidebar - Using shared container */}
        <BuilderSidebarContainer
          actualMode={actualMode}
          isOpen={isSidebarOpen}
          onToggle={() => setIsSidebarOpen(!isSidebarOpen)}
        >
          <TestCaseBuilderSidebar
          actualMode={actualMode}
          creationMode={hookData.creationMode}
          isSidebarOpen={isSidebarOpen}
          toggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
          toolboxConfig={hookData.dynamicToolboxConfig}
          selectedHost={hookData.selectedHost}
          selectedDeviceId={hookData.selectedDeviceId}
          isControlActive={hookData.isControlActive}
          areActionsLoaded={hookData.areActionsLoaded}
          userinterfaceName={hookData.userinterfaceName}
          onCloseProgressBar={() => hookData.unifiedExecution.resetExecution()}
          aiPrompt={hookData.aiPrompt}
          setAiPrompt={hookData.setAiPrompt}
          isGenerating={hookData.isGenerating}
          handleGenerateWithAI={hookData.handleGenerateWithAI}
            hasLastGeneration={!!hookData.aiGenerationResult}
            handleShowLastGeneration={hookData.handleShowLastGeneration}
          />
        </BuilderSidebarContainer>

        {/* Canvas */}
        <Box 
          ref={reactFlowWrapper} 
          sx={{ 
            flex: 1, 
            height: '100%',
            minWidth: 0,
            overflow: 'hidden',
          }} 
          onDrop={onDrop} 
          onDragOver={onDragOver}
        >
          <ReactFlow
            nodes={hookData.nodes.map(node => ({
              ...node,
              // 🆕 ADD: Pass execution state to each node
              data: {
                ...node.data,
                executionState: hookData.unifiedExecution.state.blockStates.get(node.id),
                onDataHandleClick: handleDataHandleClick, // 🆕 NEW: Pass handler to blocks
                dataLinkingState: dataLinkingState, // 🆕 NEW: Pass linking state
              },
            }))}
            edges={hookData.edges.map(edge => {
              // 🆕 ADD: Calculate edge execution state based on source/target blocks
              const sourceNode = hookData.nodes.find(n => n.id === edge.source);
              const targetNode = hookData.nodes.find(n => n.id === edge.target);
              const sourceBlockState = hookData.unifiedExecution.state.blockStates.get(edge.source);
              const targetBlockState = hookData.unifiedExecution.state.blockStates.get(edge.target);
              const currentBlockId = hookData.unifiedExecution.state.currentBlockId;
              const previousBlockId = hookData.unifiedExecution.state.previousBlockId;
              const isExecuting = hookData.unifiedExecution.state.isExecuting;
              
              // Determine edge execution state
              let edgeExecutionState: 'idle' | 'active' | 'success' | 'failure' = 'idle';
              
              // 🆕 SPECIAL: START node - edge is active when execution begins or target is executing
              if (sourceNode?.type === 'start' && isExecuting) {
                if (currentBlockId === edge.target || previousBlockId === edge.source) {
                  edgeExecutionState = 'active';
                } else if (targetBlockState && targetBlockState.status !== 'pending') {
                  edgeExecutionState = 'success';
                }
              }
              // 🆕 SPECIAL: Terminal nodes (SUCCESS/FAILURE) - show result when reached
              else if (targetNode?.type === 'success' || targetNode?.type === 'failure') {
                if (targetBlockState && targetBlockState.status !== 'pending') {
                  // Edge to SUCCESS terminal = green, edge to FAILURE terminal = red
                  edgeExecutionState = targetNode.type === 'success' ? 'success' : 'failure';
                } else if (currentBlockId === edge.target) {
                  edgeExecutionState = 'active';
                }
              }
              // Active: Edge is currently being traversed (from previous to current block)
              else if (isExecuting && 
                       previousBlockId === edge.source && 
                       currentBlockId === edge.target) {
                edgeExecutionState = 'active';
              }
              // Success/Failure: Edge was traversed after source block completed
              else if (sourceBlockState && 
                       (sourceBlockState.status === 'success' || sourceBlockState.status === 'failure') &&
                       targetBlockState &&
                       targetBlockState.status !== 'pending') {
                // Check if this edge was actually taken based on the handle type
                const handleType = edge.sourceHandle || 'success';
                const blockSucceeded = sourceBlockState.status === 'success';
                
                if ((blockSucceeded && handleType === 'success') || 
                    (!blockSucceeded && handleType === 'failure')) {
                  edgeExecutionState = sourceBlockState.status;
                }
              }
              
              return {
                ...edge,
                data: {
                  ...edge.data,
                  executionState: edgeExecutionState,
                },
              };
            })}
            onNodesChange={hookData.onNodesChange}
            onEdgesChange={hookData.onEdgesChange}
            onConnect={hookData.onConnect}
            onNodeClick={onNodeClick}
            onNodeDoubleClick={onNodeDoubleClick}
            onInit={setReactFlowInstance}
            nodeTypes={NODE_TYPES}
            edgeTypes={EDGE_TYPES}
            defaultEdgeOptions={defaultEdgeOptions}
            defaultViewport={DEFAULT_VIEWPORT}
            minZoom={ZOOM_CONSTRAINTS.minZoom}
            maxZoom={ZOOM_CONSTRAINTS.maxZoom}
            nodesDraggable={true}
            nodesConnectable={true}
            elementsSelectable={true}
            panOnDrag={true}
            zoomOnScroll={true}
            zoomOnPinch={true}
            fitView
            fitViewOptions={fitViewOptions}
          >
            <TestCaseBuilderCanvas
              actualMode={actualMode}
              isSidebarOpen={isSidebarOpen}
              onAutoLayout={handleAutoLayout}
              // 🗑️ REMOVED: isExecuting, executionDetails - no longer needed
            />
          </ReactFlow>
        </Box>
      </BuilderMainContainer>

      {/* Stats Bar - Using shared container */}
      <BuilderStatsBarContainer actualMode={actualMode}>
        <Typography variant="caption" color="text.secondary">
          {hookData.nodes.filter(n => !['start', 'success', 'failure'].includes(n.type)).length} blocks • {hookData.edges.length} connections
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {getExecutionFooterSummary(hookData.executionState)}
        </Typography>
      </BuilderStatsBarContainer>

      {/* Configuration Dialogs */}
      {hookData.selectedBlock?.type === 'action' && (
        <ActionConfigDialog
          open={hookData.isConfigDialogOpen}
          initialData={hookData.selectedBlock.data}
          onSave={handleConfigSave}
          onCancel={() => hookData.setIsConfigDialogOpen(false)}
        />
      )}

      {/* Verification config is now inline on the block (InlineVerificationConfig);
          no modal here. */}

      {hookData.selectedBlock?.type === 'loop' && (
        <LoopConfigDialog
          open={hookData.isConfigDialogOpen}
          initialData={hookData.selectedBlock.data}
          onSave={handleConfigSave}
          onCancel={() => hookData.setIsConfigDialogOpen(false)}
        />
      )}

      {/* Standard Blocks Config Dialog */}
      {hookData.selectedBlock && STANDARD_BLOCK_TYPES.includes(hookData.selectedBlock.type) && (
        <StandardBlockConfigDialog
          open={hookData.isConfigDialogOpen}
          blockCommand={hookData.selectedBlock.data.command || hookData.selectedBlock.type}
          blockLabel={hookData.selectedBlock.data.label || hookData.selectedBlock.type}
          params={hookData.selectedBlock.data.paramSchema || {}}
          initialData={hookData.selectedBlock.data.params || {}}
          availableVariables={(() => {
            // Get script I/O from context
            const { scriptInputs, scriptOutputs, scriptVariables, executionOutputValues } = useTestCaseBuilder();
            
            const variables: any[] = [];
            
            // Add script inputs with their default values
            scriptInputs.forEach((input: any) => {
              variables.push({
                name: input.name,
                type: input.type,
                source: 'input',
                value: input.default, // Show default value
              });
            });
            
            // Add script outputs with execution values if available
            scriptOutputs.forEach((output: any) => {
              variables.push({
                name: output.name,
                type: output.type,
                source: 'output',
                value: executionOutputValues[output.name], // Show runtime value
              });
            });
            
            // Add script variables
            scriptVariables.forEach((variable: any) => {
              variables.push({
                name: variable.name,
                type: variable.type,
                source: 'variable',
                value: variable.value, // Show variable value
              });
            });
            
            // Add block outputs from nodes
            hookData.nodes.forEach((node: any) => {
              if (node.data?.outputSchema && node.id !== hookData.selectedBlock?.id) {
                Object.entries(node.data.outputSchema).forEach(([outputName, outputType]) => {
                  variables.push({
                    name: outputName,
                    type: outputType as string,
                    source: 'block_output',
                    blockId: node.data.label || node.id,
                    // Could add execution values here if available
                  });
                });
              }
            });
            
            return variables;
          })()}
          onSave={(newParams) => {
            if (hookData.selectedBlock) {
              hookData.updateBlock(hookData.selectedBlock.id, { params: newParams });
            }
            hookData.setIsConfigDialogOpen(false);
          }}
          onCancel={() => hookData.setIsConfigDialogOpen(false)}
        />
      )}

      {/* API Call Config Modal */}
      <ApiCallConfigModal
        open={apiConfigModalOpen}
        onClose={() => {
          setApiConfigModalOpen(false);
          setSelectedApiBlock(null);
        }}
        initialConfig={selectedApiBlock?.data?.params}
        onSave={(config) => {
          if (selectedApiBlock) {
            // Update block with API configuration
            hookData.updateBlock(selectedApiBlock.id, {
              params: config,
              label: config.request_name,
              // Define block outputs for API calls
              blockOutputs: [
                { name: 'response', type: 'object', value: null },
                { name: 'status_code', type: 'number', value: null },
                { name: 'headers', type: 'object', value: null },
              ],
            });
          }
          setApiConfigModalOpen(false);
          setSelectedApiBlock(null);
        }}
      />
      
      {/* All Dialogs - using TestCaseBuilderDialogs component */}
      <TestCaseBuilderDialogs
        saveDialogOpen={hookData.saveDialogOpen}
        setSaveDialogOpen={hookData.setSaveDialogOpen}
        testcaseName={hookData.testcaseName}
        setTestcaseName={hookData.setTestcaseName}
        testcaseDescription={hookData.description}
        setTestcaseDescription={hookData.setDescription}
        testcaseEnvironment="dev"
        setTestcaseEnvironment={() => {}}
        currentTestcaseId={hookData.currentTestcaseId}
        currentVersion={
          hookData.currentTestcaseId 
            ? hookData.testcaseList.find(tc => tc.testcase_id === hookData.currentTestcaseId)?.current_version 
            : null
        }
        handleSave={hookData.handleSave}
        testcaseFolder={hookData.testcaseFolder}
        setTestcaseFolder={hookData.setTestcaseFolder}
        testcaseTags={hookData.testcaseTags}
        setTestcaseTags={hookData.setTestcaseTags}
        loadDialogOpen={hookData.loadDialogOpen}
        setLoadDialogOpen={hookData.setLoadDialogOpen}
        availableTestcases={hookData.testcaseList}
        handleLoad={hookData.handleLoad}
        handleDelete={hookData.handleDelete}
        editDialogOpen={false}
        setEditDialogOpen={() => {}}
        editingNode={null}
        editFormData={{}}
        setEditFormData={() => {}}
        handleSaveEdit={() => {}}
        aiGenerateConfirmOpen={hookData.aiGenerateConfirmOpen}
        setAiGenerateConfirmOpen={hookData.setAiGenerateConfirmOpen}
        handleConfirmAIGenerate={hookData.handleConfirmAIGenerate}
      />

      <VersionHistoryDialog
        open={versionDialogOpen}
        onClose={() => setVersionDialogOpen(false)}
        title="Test Case Versions"
        rows={versionRows}
        loading={loadingVersions}
        currentVersion={versionRows[0]?.version_number ?? null}
        restoringVersion={restoringVersion}
        emptyMessage="Save the test case to create the first version."
        onRestore={handleRestoreVersion}
      />
      
      {/* Delete Confirmation Dialog */}
      <StyledDialog
        open={hookData.deleteConfirmOpen}
        onClose={() => hookData.setDeleteConfirmOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle sx={{ borderBottom: 1, borderColor: 'divider', pb: 2 }}>
          Delete Test Case
        </DialogTitle>
        <DialogContent sx={{ pt: 3, pb: 3 }}>
          <Typography sx={{ mt: 1 }}>
            Are you sure you want to delete "{hookData.deleteTargetTestCase?.name}"?
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            This action cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions sx={{ borderTop: 1, borderColor: 'divider', pt: 2, pb: 2, px: 3 }}>
          <Button
            onClick={hookData.handleCancelDelete}
            variant="outlined"
          >
            Cancel
          </Button>
          <Button
            onClick={hookData.handleConfirmDelete}
            color="error"
            variant="contained"
          >
            Delete
          </Button>
        </DialogActions>
      </StyledDialog>

      {/* New Test Case Confirmation Dialog */}
      <StyledDialog
        open={hookData.newConfirmOpen}
        onClose={() => hookData.setNewConfirmOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle sx={{ borderBottom: 1, borderColor: 'divider', pb: 2 }}>
          Create New Test Case
        </DialogTitle>
        <DialogContent sx={{ pt: 3, pb: 3 }}>
          <Typography sx={{ mt: 1 }}>
            Create new test case? {hookData.hasUnsavedChanges ? 'Unsaved changes will be lost.' : 'Current test case will be cleared.'}
          </Typography>
        </DialogContent>
        <DialogActions sx={{ borderTop: 1, borderColor: 'divider', pt: 2, pb: 2, px: 3 }}>
          <Button
            onClick={() => hookData.setNewConfirmOpen(false)}
            variant="outlined"
          >
            Cancel
          </Button>
          <Button
            onClick={hookData.handleConfirmNew}
            variant="contained"
          >
            OK
          </Button>
        </DialogActions>
      </StyledDialog>
      
      {/* Snackbar for notifications - using centralized positioning */}
      <Snackbar
        open={hookData.snackbar.open}
        autoHideDuration={4000}
        onClose={() => hookData.setSnackbar({ ...hookData.snackbar, open: false })}
        anchorOrigin={TOAST_POSITION.anchorOrigin}
        sx={TOAST_POSITION.sx}
      >
        <Alert
          onClose={() => hookData.setSnackbar({ ...hookData.snackbar, open: false })}
          severity={hookData.snackbar.severity}
          sx={{ width: '100%' }}
        >
          {hookData.snackbar.message}
        </Alert>
      </Snackbar>
      
      {/* Remote/Desktop/AV Panels */}
      <DeviceControlPanels
        showRemotePanel={hookData.showRemotePanel}
        showAVPanel={hookData.showAVPanel}
        selectedHost={hookData.selectedHost}
        selectedDeviceId={hookData.selectedDeviceId}
        isControlActive={hookData.isControlActive}
        userinterfaceName={hookData.userinterfaceName}
        isAVPanelCollapsed={hookData.isAVPanelCollapsed}
        isAVPanelMinimized={hookData.isAVPanelMinimized}
        captureMode={hookData.captureMode}
        isVerificationVisible={hookData.isVerificationVisible}
        isSidebarOpen={isSidebarOpen}
        footerHeight={40}
        handleDisconnectComplete={hookData.handleDisconnectComplete}
        handleAVPanelCollapsedChange={hookData.handleAVPanelCollapsedChange}
        handleAVPanelMinimizedChange={hookData.handleAVPanelMinimizedChange}
        handleCaptureModeChange={hookData.handleCaptureModeChange}
        isMobileOrientationLandscape={hookData.isMobileOrientationLandscape}
        handleMobileOrientationChange={hookData.handleMobileOrientationChange}
      />
      
      {/* AI Generation Result Panel */}
      {hookData.showAIResultPanel && hookData.aiGenerationResult && (
        <AIGenerationResultPanel
          result={hookData.aiGenerationResult}
          onClose={hookData.handleCloseAIResultPanel}
          onRegenerate={hookData.handleRegenerateAI}
          originalPrompt={hookData.aiPrompt}
        />
      )}
      
      {/* AI Disambiguation Modal - Rendered at top level with proper z-index */}
      {hookData.disambiguationData && (
        <PromptDisambiguation
          ambiguities={hookData.disambiguationData.ambiguities}
          autoCorrections={hookData.disambiguationData.auto_corrections}
          availableNodes={hookData.disambiguationData.available_nodes}
          onResolve={hookData.handleDisambiguationResolve}
          onCancel={hookData.handleDisambiguationCancel}
          onEditPrompt={hookData.handleDisambiguationEditPrompt}
        />
      )}
      
      {/* 🗑️ REMOVED: ExecutionOverlay - replaced by ExecutionProgressBar + ExecutionLog */}
    </BuilderPageLayout>
  );
};

const TestCaseBuilder: React.FC = () => {
  return (
    <ReactFlowProvider>
      <NavigationConfigProvider>
        <NavigationEditorProvider>
          <TestCaseBuilderProvider>
            <TestCaseBuilderContent />
          </TestCaseBuilderProvider>
        </NavigationEditorProvider>
      </NavigationConfigProvider>
    </ReactFlowProvider>
  );
};

export default TestCaseBuilder;
