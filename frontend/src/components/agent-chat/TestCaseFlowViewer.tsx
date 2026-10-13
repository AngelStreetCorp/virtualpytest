/**
 * Test Case Flow Viewer - Embedded ReactFlow viewer for test cases
 * 
 * A simplified version of TestCaseBuilder for embedding in ContentViewer.
 * Shows the test case flow without headers, sidebars, or full-page layout.
 */

import React, { useEffect, useMemo, useCallback, useRef, useState } from 'react';
import { Box, Typography, CircularProgress } from '@mui/material';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  BackgroundVariant,
  MarkerType,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { AGENT_CHAT_PALETTE as PALETTE, useAgentChatPalette } from '../../constants/agentChatTheme';

// Import execution components
import { RunButton } from '../testcase/builder/RunButton';
import { ExecutionProgressOverlay } from '../common/ExecutionProgressOverlay';

// Import device control hook for automatic control management
import { useDeviceControlWithForceUnlock } from '../../hooks/useDeviceControlWithForceUnlock';

// Import test case contexts and hooks
import { TestCaseBuilderProvider } from '../../contexts/testcase/TestCaseBuilderContext';
import { NavigationEditorProvider } from '../../contexts/navigation/NavigationEditorProvider';
import { NavigationConfigProvider } from '../../contexts/navigation/NavigationConfigContext';
import { useTestCaseBuilderPage } from '../../hooks/pages/useTestCaseBuilderPage';

// Import block components from TestCaseBuilder
import { StartBlock } from '../testcase/blocks/StartBlock';
import { SuccessBlock } from '../testcase/blocks/SuccessBlock';
import { FailureBlock } from '../testcase/blocks/FailureBlock';
import { UniversalBlock } from '../testcase/blocks/UniversalBlock';
import { ApiCallBlock } from '../testcase/blocks/ApiCallBlock';
import { SuccessEdge } from '../testcase/edges/SuccessEdge';
import { FailureEdge } from '../testcase/edges/FailureEdge';
import { DataEdge } from '../testcase/edges/DataEdge';
import { DEFAULT_VIEWPORT, ZOOM_CONSTRAINTS, FIT_VIEW_OPTIONS } from '../../constants/builderDefaults';

// Node types for React Flow
const NODE_TYPES = {
  start: StartBlock,
  success: SuccessBlock,
  failure: FailureBlock,
  action: UniversalBlock,
  verification: UniversalBlock,
  navigation: UniversalBlock,
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
  custom_code: UniversalBlock,
  common_operation: UniversalBlock,
  evaluate_condition: UniversalBlock,
  api_call: ApiCallBlock,
};

// Edge types for React Flow
const EDGE_TYPES = {
  success: SuccessEdge,
  failure: FailureEdge,
  true: SuccessEdge,
  false: FailureEdge,
  complete: SuccessEdge,
  break: FailureEdge,
  data: DataEdge,
};

const defaultEdgeOptions = {
  type: 'success',
  animated: false,
  style: {
    stroke: PALETTE.borderColor,
    strokeWidth: 2,
  },
  markerEnd: {
    type: MarkerType.ArrowClosed,
    width: 20,
    height: 20,
    color: PALETTE.borderColor,
  },
};

// Hide attribution style
const hideAttributionStyle = `
  .react-flow__panel.react-flow__attribution {
    display: none !important;
  }
`;

interface TestCaseFlowViewerProps {
  testcaseId?: string;
  readOnly?: boolean;
}

// Inner content component that uses the hooks
const TestCaseFlowViewerContent: React.FC<TestCaseFlowViewerProps> = ({
  testcaseId,
  readOnly = true,
}) => {
  const P = useAgentChatPalette();
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [reactFlowInstance, setReactFlowInstance] = useState<any>(null);

  // Inject styles to hide React Flow attribution
  useEffect(() => {
    const styleTag = document.createElement('style');
    styleTag.innerHTML = hideAttributionStyle;
    document.head.appendChild(styleTag);
    return () => {
      document.head.removeChild(styleTag);
    };
  }, []);

  // Use the test case builder hook
  const hookData = useTestCaseBuilderPage();
  const {
    nodes,
    edges,
    handleLoad,
    // Execution state
    unifiedExecution,
    executionState,
    handleExecute,
    selectedHost,
    selectedDeviceId,
    isControlActive,
    userinterfaceName,
    isExecutable,
  } = hookData;

  // Device control hook for automatic take/release
  const { handleDeviceControl: deviceControlHandler, isControlLoading } = useDeviceControlWithForceUnlock({
    host: selectedHost,
    device_id: selectedDeviceId,
    sessionId: 'testcase-flow-viewer-session',
    autoCleanup: true,
  });

  // Custom execute handler that automatically manages device control
  const handleExecuteWithAutoControl = useCallback(async () => {
    if (!selectedDeviceId || !selectedHost?.host_name) {
      console.error('[TestCaseFlowViewer] Cannot execute: no device or host selected');
      return;
    }

    try {
      // Take control if not already active
      if (!isControlActive) {
        console.log('[TestCaseFlowViewer] Taking automatic control of device');
        await deviceControlHandler();
        // Wait a bit for control to be established
        await new Promise(resolve => setTimeout(resolve, 1000));
      }

      // Execute the test case
      console.log('[TestCaseFlowViewer] Starting test case execution');
      await handleExecute();

      // Wait for execution to complete
      const checkExecutionComplete = () => {
        return new Promise<void>((resolve) => {
          const checkComplete = () => {
            if (!executionState.isExecuting && !unifiedExecution?.state.isExecuting) {
              console.log('[TestCaseFlowViewer] Execution completed, releasing control');
              resolve();
            } else {
              setTimeout(checkComplete, 500);
            }
          };
          checkComplete();
        });
      };

      await checkExecutionComplete();

      // Release control after execution
      if (isControlActive) {
        console.log('[TestCaseFlowViewer] Releasing automatic control of device');
        await deviceControlHandler();
      }

    } catch (error) {
      console.error('[TestCaseFlowViewer] Error during auto-control execution:', error);
      // Release control on error too
      if (isControlActive) {
        try {
          await deviceControlHandler();
        } catch (releaseError) {
          console.error('[TestCaseFlowViewer] Error releasing control:', releaseError);
        }
      }
    }
  }, [selectedDeviceId, selectedHost, isControlActive, deviceControlHandler, handleExecute, executionState.isExecuting, unifiedExecution?.state.isExecuting]);

  // Load test case by ID
  useEffect(() => {
    const loadTestCase = async () => {
      if (!testcaseId) {
        setIsLoading(false);
        return;
      }

      try {
        console.log(`[TestCaseFlowViewer] Loading test case: ${testcaseId}`);
        setIsLoading(true);
        setError(null);
        await handleLoad(testcaseId);
        setIsLoading(false);
      } catch (err) {
        console.error('[TestCaseFlowViewer] Failed to load test case:', err);
        setError(err instanceof Error ? err.message : 'Failed to load test case');
        setIsLoading(false);
      }
    };

    loadTestCase();
  }, [testcaseId, handleLoad]);

  // Fit view when instance is ready and nodes change
  useEffect(() => {
    if (reactFlowInstance && nodes.length > 0) {
      setTimeout(() => {
        reactFlowInstance.fitView(FIT_VIEW_OPTIONS);
      }, 100);
    }
  }, [reactFlowInstance, nodes.length]);

  // MiniMap node color
  const miniMapNodeColor = useCallback((node: any) => {
    switch (node.type) {
      case 'start': return P.success;
      case 'success': return P.success;
      case 'failure': return P.error;
      case 'action': return P.accent;
      case 'verification': return P.series[1];
      case 'navigation': return P.series[2];
      case 'condition': return P.series[3];
      case 'loop': return P.series[4];
      default: return P.textMuted;
    }
  }, [P]);

  const miniMapStyle = useMemo(() => ({
    backgroundColor: P.surface,
    border: `1px solid ${P.borderColor}`,
    borderRadius: '4px',
  }), [P]);

  if (isLoading) {
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
          Loading test case...
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
          No test case loaded
        </Typography>
        {testcaseId && (
          <Typography variant="caption" color="text.disabled">
            ID: {testcaseId}
          </Typography>
        )}
      </Box>
    );
  }

  return (
    <Box
      ref={reactFlowWrapper}
      sx={{ flex: 1, width: '100%', height: '100%', position: 'relative' }}
    >
      {/* Run Button Overlay - Top Right Corner */}
      {testcaseId && nodes.length > 0 && (
        <Box
          sx={{
            position: 'absolute',
            top: 16,
            right: 16,
            zIndex: 10,
          }}
        >
          <RunButton
            onExecute={handleExecuteWithAutoControl}
            isExecuting={unifiedExecution?.state.isExecuting || isControlLoading}
            isExecutable={isExecutable}
            selectedDeviceId={selectedDeviceId}
            isControlActive={true} // Always show as active since we auto-manage control
            userinterfaceName={userinterfaceName}
            size="small"
            variant="contained"
          />
        </Box>
      )}

          <ReactFlow
            nodes={nodes.map(node => ({
              ...node,
              data: {
                ...node.data,
                readOnly: true, // Disable editing in viewer mode
              },
            }))}
            edges={edges}
            nodeTypes={NODE_TYPES}
            edgeTypes={EDGE_TYPES}
            defaultEdgeOptions={defaultEdgeOptions}
            defaultViewport={DEFAULT_VIEWPORT}
            minZoom={ZOOM_CONSTRAINTS.minZoom}
            maxZoom={ZOOM_CONSTRAINTS.maxZoom}
            onInit={setReactFlowInstance}
            nodesDraggable={!readOnly}
            nodesConnectable={!readOnly}
            elementsSelectable={true}
            panOnDrag={true}
            zoomOnScroll={true}
            zoomOnPinch={true}
            fitView
            fitViewOptions={FIT_VIEW_OPTIONS}
          >
        <Background variant={BackgroundVariant.Dots} gap={15} size={1} />
        <Controls position="top-left" showInteractive={!readOnly} />
        <MiniMap
          style={miniMapStyle}
          nodeColor={miniMapNodeColor}
          maskColor={`${P.textPrimary}33`}
          pannable
          zoomable
          position="bottom-right"
        />
      </ReactFlow>

      {/* Execution Overlay */}
      <ExecutionProgressOverlay
        variant="testcase"
        currentBlockId={unifiedExecution?.state.currentBlockId || null}
        blockStates={unifiedExecution?.state.blockStates || new Map()}
        isExecuting={unifiedExecution?.state.isExecuting || false}
        nodes={nodes}
        executionResult={unifiedExecution?.state.result || null}
        onStop={() => {
          // TODO: Implement stop execution
          console.log('Stop execution requested');
        }}
        onClose={() => {
          // User manually closes the progress bar
          unifiedExecution?.resetExecution();
        }}
      />
    </Box>
  );
};

// Main component with providers
export const TestCaseFlowViewer: React.FC<TestCaseFlowViewerProps> = (props) => {
  return (
    <ReactFlowProvider>
      <NavigationConfigProvider>
        <NavigationEditorProvider>
          <TestCaseBuilderProvider>
            <TestCaseFlowViewerContent {...props} />
          </TestCaseBuilderProvider>
        </NavigationEditorProvider>
      </NavigationConfigProvider>
    </ReactFlowProvider>
  );
};

export default TestCaseFlowViewer;

