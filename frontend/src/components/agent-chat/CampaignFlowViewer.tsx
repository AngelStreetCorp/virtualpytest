/**
 * Campaign Flow Viewer - Embedded ReactFlow viewer for campaigns
 *
 * A simplified version of CampaignBuilder for embedding in ContentViewer.
 * Shows the campaign flow without headers, sidebars, or full-page layout.
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
  ConnectionMode,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { useTheme } from '@mui/material/styles';
import { AGENT_CHAT_PALETTE as PALETTE } from '../../constants/agentChatTheme';

// Import campaign contexts and hooks
import { CampaignBuilderProvider, useCampaignBuilder } from '../../contexts/campaign/CampaignBuilderContext';
import { NavigationEditorProvider } from '../../contexts/navigation/NavigationEditorProvider';
import { NavigationConfigProvider } from '../../contexts/navigation/NavigationConfigContext';

// Import execution components
import { RunButton } from '../testcase/builder/RunButton';
import { ExecutionProgressOverlay } from '../common/ExecutionProgressOverlay';

// Device control is not needed for campaigns - they execute on the server

// Import host control for device/host selection
import { useHostControl } from '../../hooks/useHostManager';

// Import campaign block components
import { StartBlock } from '../testcase/blocks/StartBlock';
import { SuccessBlock } from '../testcase/blocks/SuccessBlock';
import { FailureBlock } from '../testcase/blocks/FailureBlock';
import { CampaignBlock } from '../campaign/blocks/CampaignBlock';
import { SuccessEdge } from '../testcase/edges/SuccessEdge';
import { FailureEdge } from '../testcase/edges/FailureEdge';

// Node types for React Flow
const nodeTypes = {
  start: StartBlock,
  success: SuccessBlock,
  failure: FailureBlock,
  testcase: CampaignBlock,
  script: CampaignBlock,
};

// Edge types for React Flow
const edgeTypes = {
  success: SuccessEdge,
  failure: FailureEdge,
  control: SuccessEdge, // Campaign uses 'control' type for flow edges
};

// Default edge options - matching CampaignBuilder
const defaultEdgeOptions = {
  type: 'success',
  animated: false,
  style: {
    stroke: '#94a3b8',
    strokeWidth: 2,
  },
  markerEnd: {
    type: MarkerType.ArrowClosed,
    width: 20,
    height: 20,
    color: '#94a3b8',
  },
};

// Hide attribution style
const hideAttributionStyle = `
  .react-flow__panel.react-flow__attribution {
    display: none !important;
  }
`;

interface CampaignFlowViewerProps {
  campaignId?: string;
  readOnly?: boolean;
  selectedUserInterface?: string;
}

// Inner content component that uses the hooks
const CampaignFlowViewerContent: React.FC<CampaignFlowViewerProps> = ({
  campaignId,
  readOnly = true,
  selectedUserInterface,
}) => {
  const theme = useTheme();
  const isDarkMode = theme.palette.mode === 'dark';
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

  // Use the campaign builder hook
  const {
    nodes,
    edges,
    state,
    loadCampaign,
    executeCurrentCampaign,
    unifiedExecution,
    isExecutable,
  } = useCampaignBuilder();

  // Get device and host info from HostManager
  const {
    selectedHost,
    selectedDeviceId,
  } = useHostControl();

  // Use global userinterface selection (same as TestCaseFlowViewer)
  const userinterfaceName = selectedUserInterface;

  // Simple execute handler - campaigns don't need device control like test cases do
  const handleExecuteCampaign = useCallback(async () => {
    // Check if campaign has required execution configuration
    if (!selectedDeviceId || !selectedHost?.host_name || !userinterfaceName) {
      console.error('[CampaignFlowViewer] Cannot execute campaign: missing required configuration');

      // Set error in unified execution state
      unifiedExecution.completeExecution({
        success: false,
        result_type: 'error',
        execution_time_ms: 0,
        error: 'Missing execution configuration. Please select host, device, and userinterface.',
        step_count: 0,
      });
      return;
    }

    try {
      console.log('[CampaignFlowViewer] Starting campaign execution');
      await executeCurrentCampaign(selectedHost.host_name, selectedDeviceId, userinterfaceName);
    } catch (error) {
      console.error('[CampaignFlowViewer] Error executing campaign:', error);

      // Set error in unified execution state
      unifiedExecution.completeExecution({
        success: false,
        result_type: 'error',
        execution_time_ms: 0,
        error: error instanceof Error ? error.message : 'Unknown error occurred during campaign execution',
        step_count: 0,
      });
    }
  }, [selectedDeviceId, selectedHost, userinterfaceName, executeCurrentCampaign, unifiedExecution]);

  // Load campaign by ID
  useEffect(() => {
    const loadCampaignData = async () => {
      if (!campaignId) {
        setIsLoading(false);
        return;
      }

      try {
        console.log(`[CampaignFlowViewer] Loading campaign: ${campaignId}`);
        setIsLoading(true);
        setError(null);
        await loadCampaign(campaignId);
        setIsLoading(false);
      } catch (err) {
        console.error('[CampaignFlowViewer] Failed to load campaign:', err);
        setError(err instanceof Error ? err.message : 'Failed to load campaign');
        setIsLoading(false);
      }
    };

    loadCampaignData();
  }, [campaignId, loadCampaign]);

  // Fit view when instance is ready and nodes change
  useEffect(() => {
    if (reactFlowInstance && nodes.length > 0) {
      setTimeout(() => {
        reactFlowInstance.fitView({ padding: 0.2, duration: 300 });
      }, 100);
    }
  }, [reactFlowInstance, nodes.length]);

  // MiniMap node color
  const miniMapNodeColor = useCallback((node: any) => {
    switch (node.type) {
      case 'start': return '#22c55e';
      case 'success': return '#22c55e';
      case 'failure': return '#ef4444';
      case 'testcase': return '#3b82f6';
      case 'script': return '#8b5cf6';
      default: return '#6b7280';
    }
  }, []);

  const miniMapStyle = useMemo(() => ({
    backgroundColor: isDarkMode ? '#1f2937' : '#ffffff',
    border: `1px solid ${isDarkMode ? '#374151' : '#e5e7eb'}`,
    borderRadius: '4px',
  }), [isDarkMode]);

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
          Loading campaign...
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
          No campaign loaded
        </Typography>
        {campaignId && (
          <Typography variant="caption" color="text.disabled">
            ID: {campaignId}
          </Typography>
        )}
        {state.campaign_name && (
          <Typography variant="caption" color="text.disabled">
            Name: {state.campaign_name}
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
      {campaignId && nodes.length > 0 && (
        <Box
          sx={{
            position: 'absolute',
            top: 16,
            right: 16,
            zIndex: 10,
          }}
        >
          <RunButton
            onExecute={handleExecuteCampaign}
            isExecuting={unifiedExecution?.state.isExecuting || false}
            isExecutable={isExecutable && !!selectedDeviceId && !!selectedHost?.host_name && !!userinterfaceName}
            selectedDeviceId={selectedDeviceId}
            isControlActive={true} // Campaigns don't require device control
            userinterfaceName={userinterfaceName || ''}
            size="small"
            variant="contained"
            disabled={!selectedDeviceId || !selectedHost?.host_name || !userinterfaceName}
          />
        </Box>
      )}

      <ReactFlow
        nodes={nodes.map(node => ({
          ...node,
          data: {
            ...node.data,
            readOnly: true, // Disable editing in viewer mode
            selectedUserInterface: selectedUserInterface || '', // Pass global userinterface for execution
          },
        }))}
        edges={edges as any}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        onInit={setReactFlowInstance}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        elementsSelectable={true}
        panOnDrag={true}
        zoomOnScroll={true}
        zoomOnPinch={true}
        connectionMode={ConnectionMode.Loose}
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

      {/* Execution Overlay */}
      <ExecutionProgressOverlay
        variant="campaign"
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
export const CampaignFlowViewer: React.FC<CampaignFlowViewerProps> = (props) => {
  return (
    <ReactFlowProvider>
      <NavigationConfigProvider>
        <NavigationEditorProvider>
          <CampaignBuilderProvider>
            <CampaignFlowViewerContent {...props} />
          </CampaignBuilderProvider>
        </NavigationEditorProvider>
      </NavigationConfigProvider>
    </ReactFlowProvider>
  );
};

export default CampaignFlowViewer;

