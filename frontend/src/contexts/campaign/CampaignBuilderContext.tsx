/**
 * Campaign Builder Context
 * 
 * Manages state for the visual campaign builder including:
 * - Campaign graph (nodes, edges)
 * - Campaign configuration
 * - Node selection and editing
 * - Save/Load operations
 */

import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import {
  CampaignGraph,
  CampaignNode,
  CampaignEdge,
  CampaignBuilderState,
  CampaignInput,
  CampaignOutput,
  CampaignReportField,
} from '../../types/pages/CampaignGraph_Types';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { waitForExecutionSocketEvent } from '../../utils/executionSocketWait';
import { getScriptIdentity } from '../../utils/executionUtils';
import { testcaseScriptConfigToBlockIO } from '../../utils/testcase/scriptInputUtils';
import { addEdge, Connection, applyNodeChanges, applyEdgeChanges, NodeChange, EdgeChange } from 'reactflow';
import { useExecutionState } from '../../hooks/testcase/useExecutionState';
import { DEFAULT_TERMINAL_POSITIONS } from '../../constants/builderDefaults';

interface CampaignBuilderContextValue {
  // State
  state: CampaignBuilderState;

  // Execution State
  unifiedExecution: ReturnType<typeof useExecutionState>;

  // Campaign Config
  updateCampaignConfig: (updates: Partial<CampaignBuilderState>) => void;

  // Graph Operations
  nodes: CampaignNode[];
  edges: CampaignEdge[];
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;

  // Node Operations
  addNode: (node: CampaignNode) => void;
  updateNode: (nodeId: string, updates: Partial<CampaignNode['data']>) => void;
  deleteNode: (nodeId: string) => void;
  selectedNode: CampaignNode | null;
  selectNode: (nodeId: string | null) => void;

  // Data Linking
  linkOutputToInput: (sourceBlockId: string, sourceOutputName: string, targetBlockId: string, targetInputName: string) => void;
  unlinkInput: (blockId: string, inputName: string) => void;

  // Campaign I/O
  campaignInputs: CampaignInput[];
  campaignOutputs: CampaignOutput[];
  campaignReports: { mode: 'set' | 'aggregate'; fields: CampaignReportField[] };

  // Campaign Execution
  executeCurrentCampaign: (hostName: string, deviceId: string, userinterfaceName: string) => Promise<void>;
  executeBlock: (blockId: string, hostName: string, deviceId: string, userinterfaceName: string) => Promise<void>;
  isExecuting: boolean;
  isExecutable: boolean;
  addCampaignInput: (input: CampaignInput) => void;
  addCampaignOutput: (output: CampaignOutput) => void;
  addCampaignReportField: (field: CampaignReportField) => void;
  removeCampaignInput: (name: string) => void;
  removeCampaignOutput: (name: string) => void;
  removeCampaignReportField: (name: string) => void;
  setCampaignReportsMode: (mode: 'set' | 'aggregate') => void;

  // Save/Load
  saveCampaign: () => Promise<boolean>;
  loadCampaign: (campaignId: string) => Promise<boolean>;
  fetchCampaignList: () => Promise<void>;
  campaignList: any[];
  isLoadingCampaignList: boolean;
  hasUnsavedChanges: boolean;
  resetBuilder: () => void;
}

const CampaignBuilderContext = createContext<CampaignBuilderContextValue | null>(null);

export const useCampaignBuilder = () => {
  const context = useContext(CampaignBuilderContext);
  if (!context) {
    throw new Error('useCampaignBuilder must be used within CampaignBuilderProvider');
  }
  return context;
};

interface CampaignBuilderProviderProps {
  children: ReactNode;
}


// Initial graph with START, SUCCESS, FAILURE terminal nodes (using shared positions)
const createInitialGraph = (): CampaignGraph => ({
  nodes: [
    {
      id: 'start',
      type: 'start',
      position: { ...DEFAULT_TERMINAL_POSITIONS.start },
      data: { label: 'START' },
    },
    {
      id: 'success',
      type: 'success',
      position: { ...DEFAULT_TERMINAL_POSITIONS.success },
      data: { label: 'SUCCESS' },
    },
    {
      id: 'failure',
      type: 'failure',
      position: { ...DEFAULT_TERMINAL_POSITIONS.failure },
      data: { label: 'FAILURE' },
    },
  ],
  edges: [],
  campaignConfig: {
    inputs: [],
    outputs: [],
    reports: {
      mode: 'aggregate',
      fields: [],
    },
  },
});

export const CampaignBuilderProvider: React.FC<CampaignBuilderProviderProps> = ({ children }) => {
  const [state, setState] = useState<CampaignBuilderState>({
    graph: createInitialGraph(),
  });

  // Execution state
  const unifiedExecution = useExecutionState();

  // Campaign list state
  const [campaignList, setCampaignList] = useState<any[]>([]);
  const [isLoadingCampaignList, setIsLoadingCampaignList] = useState(false);

  // Unsaved changes tracking
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);

  // Campaign Config
  const updateCampaignConfig = useCallback((updates: Partial<CampaignBuilderState>) => {
    setState(prev => ({ ...prev, ...updates }));
  }, []);

  // Graph state (React Flow)
  const nodes = state.graph.nodes;
  const edges = state.graph.edges;

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setState(prev => ({
      ...prev,
      graph: {
        ...prev.graph,
        nodes: applyNodeChanges(changes, prev.graph.nodes) as CampaignNode[],
      },
    }));

    // Track position changes as unsaved changes (when drag completes)
    const hasPositionChange = changes.some((change: any) =>
      change.type === 'position' && change.dragging === false
    );
    if (hasPositionChange) {
      setHasUnsavedChanges(true);
    }
  }, []);

  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    setState(prev => ({
      ...prev,
      graph: {
        ...prev.graph,
        edges: applyEdgeChanges(changes, prev.graph.edges as any) as CampaignEdge[],
      },
    }));

    // Track edge removal as unsaved changes
    const hasRemoval = changes.some((change: any) => change.type === 'remove');
    if (hasRemoval) {
      setHasUnsavedChanges(true);
    }
  }, []);

  const onConnect = useCallback((connection: Connection) => {
    // RULE 1: Each source handle can only have ONE outgoing connection
    // RULE 2: Success and failure handles from same source cannot go to same target
    const sourceNodeId = connection.source;
    const targetNodeId = connection.target;
    const sourceHandleId = connection.sourceHandle || 'success';

    setState(prev => {
      const currentEdges = prev.graph.edges;

      // RULE 2: Check if another handle from same source already goes to this target
      const conflictingEdge = currentEdges.find(edge =>
        edge.source === sourceNodeId &&
        edge.target === targetNodeId &&
        edge.sourceHandle !== sourceHandleId
      );

      if (conflictingEdge) {
        console.warn(`[@CampaignBuilder] ⚠️ BLOCKED: Cannot connect both '${conflictingEdge.sourceHandle}' and '${sourceHandleId}' to same target`);
        return prev; // Don't add the edge
      }

      // RULE 1: Remove any existing edge from same source handle
      const filteredEdges = currentEdges.filter(edge =>
        !(edge.source === sourceNodeId && edge.sourceHandle === sourceHandleId)
      );

      return {
        ...prev,
        graph: {
          ...prev.graph,
          edges: addEdge({ ...connection, type: 'control' } as any, filteredEdges as any) as CampaignEdge[],
        },
      };
    });
    setHasUnsavedChanges(true);
  }, []);

  // Node Operations
  const addNode = useCallback((node: CampaignNode) => {
    setState(prev => ({
      ...prev,
      graph: {
        ...prev.graph,
        nodes: [...prev.graph.nodes, node],
      },
    }));
    setHasUnsavedChanges(true);
  }, []);

  const updateNode = useCallback((nodeId: string, updates: Partial<CampaignNode['data']>) => {
    setState(prev => ({
      ...prev,
      graph: {
        ...prev.graph,
        nodes: prev.graph.nodes.map(node =>
          node.id === nodeId
            ? { ...node, data: { ...node.data, ...updates } }
            : node
        ),
      },
    }));
    setHasUnsavedChanges(true);
  }, []);

  const deleteNode = useCallback((nodeId: string) => {
    // Don't allow deleting terminal nodes
    if (['start', 'success', 'failure'].includes(nodeId)) {
      return;
    }

    setState(prev => ({
      ...prev,
      graph: {
        ...prev.graph,
        nodes: prev.graph.nodes.filter(node => node.id !== nodeId),
        edges: prev.graph.edges.filter(edge => edge.source !== nodeId && edge.target !== nodeId),
      },
      selectedNode: prev.selectedNode === nodeId ? undefined : prev.selectedNode,
    }));
    setHasUnsavedChanges(true);
  }, []);

  const selectedNode = state.selectedNode 
    ? nodes.find(n => n.id === state.selectedNode) || null
    : null;

  const selectNode = useCallback((nodeId: string | null) => {
    setState(prev => ({ ...prev, selectedNode: nodeId || undefined }));
  }, []);

  // Data Linking
  const linkOutputToInput = useCallback((
    sourceBlockId: string,
    sourceOutputName: string,
    targetBlockId: string,
    targetInputName: string
  ) => {
    setState(prev => ({
      ...prev,
      graph: {
        ...prev.graph,
        nodes: prev.graph.nodes.map(node => {
          if (node.id === targetBlockId && node.data.inputs) {
            return {
              ...node,
              data: {
                ...node.data,
                inputs: node.data.inputs.map(input =>
                  input.name === targetInputName
                    ? {
                        ...input,
                        linkedSource: {
                          blockId: sourceBlockId,
                          outputName: sourceOutputName,
                        },
                      }
                    : input
                ),
              },
            };
          }
          return node;
        }),
      },
    }));
  }, []);

  const unlinkInput = useCallback((blockId: string, inputName: string) => {
    setState(prev => ({
      ...prev,
      graph: {
        ...prev.graph,
        nodes: prev.graph.nodes.map(node => {
          if (node.id === blockId && node.data.inputs) {
            return {
              ...node,
              data: {
                ...node.data,
                inputs: node.data.inputs.map(input =>
                  input.name === inputName
                    ? { ...input, linkedSource: undefined }
                    : input
                ),
              },
            };
          }
          return node;
        }),
      },
    }));
  }, []);

  // Campaign I/O
  const campaignInputs = state.graph.campaignConfig?.inputs || [];
  const campaignOutputs = state.graph.campaignConfig?.outputs || [];
  const campaignReports = state.graph.campaignConfig?.reports || { mode: 'aggregate', fields: [] };

  const addCampaignInput = useCallback((input: CampaignInput) => {
    setState(prev => ({
      ...prev,
      graph: {
        ...prev.graph,
        campaignConfig: {
          ...prev.graph.campaignConfig,
          inputs: [...(prev.graph.campaignConfig?.inputs || []), input],
        },
      },
    }));
  }, []);

  const addCampaignOutput = useCallback((output: CampaignOutput) => {
    setState(prev => ({
      ...prev,
      graph: {
        ...prev.graph,
        campaignConfig: {
          ...prev.graph.campaignConfig,
          outputs: [...(prev.graph.campaignConfig?.outputs || []), output],
        },
      },
    }));
  }, []);

  const addCampaignReportField = useCallback((field: CampaignReportField) => {
    setState(prev => ({
      ...prev,
      graph: {
        ...prev.graph,
        campaignConfig: {
          ...prev.graph.campaignConfig,
          reports: {
            mode: prev.graph.campaignConfig?.reports?.mode || 'aggregate',
            fields: [...(prev.graph.campaignConfig?.reports?.fields || []), field],
          },
        },
      },
    }));
  }, []);

  const removeCampaignInput = useCallback((name: string) => {
    setState(prev => ({
      ...prev,
      graph: {
        ...prev.graph,
        campaignConfig: {
          ...prev.graph.campaignConfig,
          inputs: (prev.graph.campaignConfig?.inputs || []).filter(i => i.name !== name),
        },
      },
    }));
  }, []);

  const removeCampaignOutput = useCallback((name: string) => {
    setState(prev => ({
      ...prev,
      graph: {
        ...prev.graph,
        campaignConfig: {
          ...prev.graph.campaignConfig,
          outputs: (prev.graph.campaignConfig?.outputs || []).filter(o => o.name !== name),
        },
      },
    }));
  }, []);

  const removeCampaignReportField = useCallback((name: string) => {
    setState(prev => ({
      ...prev,
      graph: {
        ...prev.graph,
        campaignConfig: {
          ...prev.graph.campaignConfig,
          reports: {
            mode: prev.graph.campaignConfig?.reports?.mode || 'aggregate',
            fields: (prev.graph.campaignConfig?.reports?.fields || []).filter(f => f.name !== name),
          },
        },
      },
    }));
  }, []);

  const setCampaignReportsMode = useCallback((mode: 'set' | 'aggregate') => {
    setState(prev => ({
      ...prev,
      graph: {
        ...prev.graph,
        campaignConfig: {
          ...prev.graph.campaignConfig,
          reports: {
            mode,
            fields: prev.graph.campaignConfig?.reports?.fields || [],
          },
        },
      },
    }));
  }, []);

  // Campaign list fetching
  const fetchCampaignList = useCallback(async () => {
    setIsLoadingCampaignList(true);
    try {
      console.log('[@CampaignBuilder] Fetching campaign list...');
      const response = await fetch(buildServerUrl('/server/campaigns/getAllCampaigns'));

      if (!response.ok) {
        console.error('[@CampaignBuilder] Failed to fetch campaigns:', response.status);
        setCampaignList([]);
        return;
      }

      const data = await response.json();

      if (data.success && data.campaigns) {
        console.log(`[@CampaignBuilder] Loaded ${data.campaigns.length} campaigns`);
        setCampaignList(data.campaigns);
      } else {
        console.log('[@CampaignBuilder] No campaigns found');
        setCampaignList([]);
      }
    } catch (error) {
      console.error('[@CampaignBuilder] Failed to fetch campaign list:', error);
      setCampaignList([]);
    } finally {
      setIsLoadingCampaignList(false);
    }
  }, []);

  // Save campaign
  const saveCampaign = useCallback(async () => {
    console.log('[@CampaignBuilder] Saving campaign:', state);

    try {
      // Convert campaign state to API format
      const campaignData = {
        campaign_name: state.campaign_name || 'Untitled Campaign',
        description: state.description,
        userinterface_name: state.userinterface_name,
        host_name: state.host,
        device_name: state.device,
        execution_config: {}, // TODO: Add execution config from UI
        script_configurations: [], // TODO: Convert nodes/edges to script_configurations
        tags: [], // TODO: Add tags support
      };

      // Determine if this is a create or update operation
      const isUpdate = !!state.campaign_id;
      const endpoint = isUpdate ? 'updateCampaign' : 'createCampaign';
      const url = isUpdate
        ? buildServerUrl(`/server/campaigns/${endpoint}/${state.campaign_id}`)
        : buildServerUrl(`/server/campaigns/${endpoint}`);

      const requestData = campaignData;

      console.log(`[@CampaignBuilder] ${isUpdate ? 'Updating' : 'Creating'} campaign via ${url}`);

      const response = await fetch(url, {
        method: isUpdate ? 'PUT' : 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestData),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        console.error('[@CampaignBuilder] Save failed:', response.status, errorData);
        return false;
      }

      const result = await response.json();

      if (result.success) {
        // Update local state with the saved campaign ID if it was a create
        if (!isUpdate && result.campaign?.campaign_id) {
          setState(prevState => ({
            ...prevState,
            campaign_id: result.campaign.campaign_id,
          }));
        }

        console.log('[@CampaignBuilder] Campaign saved successfully:', result.campaign);
        setHasUnsavedChanges(false); // Reset unsaved changes after successful save
        return true;
      } else {
        console.error('[@CampaignBuilder] Save failed:', result.error);
        return false;
      }

    } catch (error) {
      console.error('[@CampaignBuilder] Error saving campaign:', error);
      return false;
    }
  }, [state]);

  const loadCampaign = useCallback(async (campaignId: string) => {
    console.log('[@CampaignBuilder] Loading campaign:', campaignId);

    try {
      // Fetch campaign data from API
      const response = await fetch(buildServerUrl(`/server/campaigns/getCampaign/${campaignId}`));

      if (!response.ok) {
        console.error('[@CampaignBuilder] Failed to fetch campaign:', response.status);
        return false;
      }

      const data = await response.json();

      if (!data.success || !data.campaign) {
        console.error('[@CampaignBuilder] Campaign not found or invalid response:', data);
        return false;
      }

      const campaign = data.campaign;

      // Convert API format to internal state format
      const campaignConfig = {
        campaign_id: campaign.campaign_id,
        campaign_name: campaign.campaign_name,
        description: campaign.description,
        userinterface_name: campaign.userinterface_name,
        host_name: campaign.host_name,
        device_name: campaign.device_name,
        execution_config: campaign.execution_config || {},
        script_configurations: campaign.script_configurations || [],
      };

      // Convert script_configurations to visual nodes and edges
      const scriptConfigurations = campaign.script_configurations || [];
      const nodes: CampaignNode[] = [];
      const edges: CampaignEdge[] = [];

      // Fetch each testcase's scriptConfig so its input variables render as
      // editable per-row parameter fields (same seeding as a fresh drop).
      const testcaseIO = new Map<string, { inputs: any[]; outputs: any[] }>();
      const testcaseIds: string[] = [
        ...new Set<string>(
          scriptConfigurations
            .filter((s: any) => s.testcase_id)
            .map((s: any) => String(s.testcase_id)),
        ),
      ];
      await Promise.all(
        testcaseIds.map(async (testcaseId) => {
          try {
            const tcResponse = await fetch(buildServerUrl(`/server/testcase/${testcaseId}`));
            const tcData = await tcResponse.json();
            const scriptConfig = tcData?.testcase?.graph_json?.scriptConfig;
            if (tcData?.success && scriptConfig) {
              testcaseIO.set(testcaseId, testcaseScriptConfigToBlockIO(scriptConfig));
            }
          } catch (e) {
            console.warn(`[@CampaignBuilder] Failed to load testcase ${testcaseId} I/O:`, e);
          }
        }),
      );

      // Always include terminal nodes (using shared positions)
      nodes.push(
        {
          id: 'start',
          type: 'start',
          position: { ...DEFAULT_TERMINAL_POSITIONS.start },
          data: { label: 'START' },
        },
        {
          id: 'success',
          type: 'success',
          position: { ...DEFAULT_TERMINAL_POSITIONS.success },
          data: { label: 'SUCCESS' },
        },
        {
          id: 'failure',
          type: 'failure',
          position: { ...DEFAULT_TERMINAL_POSITIONS.failure },
          data: { label: 'FAILURE' },
        }
      );

      // Create nodes for each script configuration
      scriptConfigurations.forEach((script: any, index: number) => {
        const scriptNodeId = `script-${index}`;
        const yPosition = 150 + (index * 100); // Space nodes vertically

        const io = script.testcase_id ? testcaseIO.get(String(script.testcase_id)) : undefined;
        nodes.push({
          id: scriptNodeId,
          type: 'testcase',
          position: { x: 250, y: yPosition },
          data: {
            label: script.script_name,
            executableName: script.script_name,
            executableId: script.testcase_id, // Store the testcase ID for execution
            executableType: 'testcase',
            parameters: script.parameters || {},
            inputs: io?.inputs,
            outputs: io?.outputs,
          },
        });

        // Connect to previous node (or start for first script)
        const sourceNodeId = index === 0 ? 'start' : `script-${index - 1}`;
        edges.push({
          id: `edge-${sourceNodeId}-${scriptNodeId}`,
          source: sourceNodeId,
          target: scriptNodeId,
          type: 'control',
        });

        // Connect last script to both success and failure
        if (index === scriptConfigurations.length - 1) {
          edges.push(
            {
              id: `edge-${scriptNodeId}-success`,
              source: scriptNodeId,
              target: 'success',
              type: 'control',
            },
            {
              id: `edge-${scriptNodeId}-failure`,
              source: scriptNodeId,
              target: 'failure',
              type: 'control',
            }
          );
        }
      });

      const campaignGraph = {
        nodes,
        edges,
        campaignConfig: {
          inputs: [],
          outputs: [],
          reports: {
            mode: 'aggregate' as const,
            fields: [],
          },
        },
      };

      // Update state with loaded campaign
      setState({
        campaign_id: campaignConfig.campaign_id,
        campaign_name: campaignConfig.campaign_name,
        description: campaignConfig.description,
        userinterface_name: campaignConfig.userinterface_name,
        host: campaignConfig.host_name,
        device: campaignConfig.device_name,
        graph: campaignGraph,
      });

      console.log('[@CampaignBuilder] Campaign loaded successfully:', {
        config: campaignConfig,
        graph: campaignGraph,
      });
      setHasUnsavedChanges(false); // Reset unsaved changes after successful load
      return true;

    } catch (error) {
      console.error('[@CampaignBuilder] Error loading campaign:', error);
      return false;
    }
  }, []);

  const resetBuilder = useCallback(() => {
    setState({
      graph: createInitialGraph(),
    });
    setHasUnsavedChanges(false); // Reset unsaved changes when creating new campaign
  }, []);

  // Execute current campaign
  const executeCurrentCampaign = useCallback(async (hostName: string, deviceId: string, userinterfaceName: string) => {
    console.log('[@CampaignBuilder:executeCurrentCampaign] Starting campaign execution');

    // Build campaign config from current state
    const campaignConfig = {
      campaign_id: state.campaign_id || `temp_${Date.now()}`,
      name: state.campaign_name || 'Untitled Campaign',
      description: state.description,
      userinterface_name: userinterfaceName,
      host_name: hostName,
      device: deviceId,
      execution_config: {
        continue_on_failure: true, // TODO: Make configurable
        timeout_minutes: 30, // TODO: Make configurable
        parallel: false, // Sequential execution for visual campaigns
      },
      script_configurations: nodes
        .filter(node => node.type !== 'start' && node.type !== 'success' && node.type !== 'failure')
        .map((node, index) => ({
          script_name: node.data.executableName || node.data.label || `script_${index}`,
          script_type: node.type, // 'testcase' or 'script'
          testcase_id: node.data.executableId, // For testcase nodes
          description: node.data.description,
          parameters: node.data.parameters || {},
          order: index,
        })),
    };

    console.log('[@CampaignBuilder:executeCurrentCampaign] Campaign config:', campaignConfig);

    // Start unified execution tracking
    unifiedExecution.startExecution('test_case', campaignConfig.script_configurations.map(s => s.script_name));

    try {
      // Execute campaign using the same API as useCampaign hook
      const response = await fetch(buildServerUrl('/server/campaigns/execute'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(campaignConfig),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }

      const result = await response.json();

      if (!result.success) {
        throw new Error(result.error || 'Failed to start campaign execution');
      }

      const executionId = result.execution_id;

      if (!executionId) {
        throw new Error('No execution_id returned');
      }

      console.log('[@CampaignBuilder:executeCurrentCampaign] Campaign started with execution ID:', executionId);

      const socketEvent = await waitForExecutionSocketEvent(executionId, ['campaign'], 7200000);
      const finalResult = socketEvent.result;
      if (!finalResult) {
        unifiedExecution.completeExecution({
          success: false,
          result_type: 'error',
          execution_time_ms: 0,
          error: socketEvent.error || 'Campaign failed',
          step_count: 0,
        });
        return;
      }

      if (finalResult.script_executions) {
        finalResult.script_executions.forEach((script: any, index: number) => {
          const blockId = script.script_name || `script_${index}`;
          unifiedExecution.updateBlockState(blockId, {
            status: script.success ? 'success' : 'failure',
            duration: script.execution_time_ms || 0,
            error: script.error,
            result: {
              report_url: script.report_url,
              logs_url: script.logs_url,
              script_name: script.script_name,
              script_type: script.script_type,
              execution_order: script.execution_order,
            }
          });
        });
      }

      const overallSuccess = finalResult.overall_success || false;
      const resultType = overallSuccess ? 'success' : 'failure';
      const firstFailedScript = finalResult.script_executions?.find((s: any) => !s.success);
      unifiedExecution.completeExecution({
        success: overallSuccess,
        result_type: resultType,
        execution_time_ms: finalResult.execution_time_ms || 0,
        error: socketEvent.error || firstFailedScript?.error,
        step_count: finalResult.total_scripts || 0,
      });

    } catch (error) {
      console.error('[@CampaignBuilder:executeCurrentCampaign] Error executing campaign:', error);
      unifiedExecution.completeExecution({
        success: false,
        result_type: 'error',
        execution_time_ms: 0,
        error: error instanceof Error ? error.message : 'Failed to start campaign execution',
      });
    }
  }, [state, nodes, unifiedExecution]);

  // Execute individual block
  const executeBlock = useCallback(async (blockId: string, hostName: string, deviceId: string, userinterfaceName: string) => {
    console.log('[@CampaignBuilder:executeBlock] Starting individual block execution:', blockId);

    // Find the block to execute
    const blockToExecute = nodes.find(node => node.id === blockId);
    if (!blockToExecute) {
      throw new Error(`Block ${blockId} not found`);
    }

    if (blockToExecute.type === 'start' || blockToExecute.type === 'success' || blockToExecute.type === 'failure') {
      throw new Error(`Cannot execute terminal block: ${blockId}`);
    }

    // Start unified execution tracking for single block
    unifiedExecution.startExecution('single_block', [blockId]);
    unifiedExecution.startBlockExecution(blockId);

    try {
      if (blockToExecute.data.executableType === 'testcase') {
        // Execute as test case using testcase API
        console.log('[@CampaignBuilder:executeBlock] Executing as testcase');

        // Get the testcase ID from stored data
        const testcaseId = blockToExecute.data.executableId;
        if (!testcaseId) {
          throw new Error(`Testcase block ${blockId} does not have a valid testcase ID`);
        }

        console.log('[@CampaignBuilder:executeBlock] Loading testcase data for ID:', testcaseId);
        const testcaseResponse = await fetch(buildServerUrl(`/server/testcase/${testcaseId}`));
        if (!testcaseResponse.ok) {
          const errorData = await testcaseResponse.json();
          throw new Error(`Failed to load testcase ${testcaseId}: ${errorData.error || `HTTP ${testcaseResponse.status}`}`);
        }

        const testcaseData = await testcaseResponse.json();
        if (!testcaseData.success || !testcaseData.testcase) {
          throw new Error(`Testcase ${testcaseId} not found or invalid response`);
        }

        const testcase = testcaseData.testcase;
        console.log('[@CampaignBuilder:executeBlock] Loaded testcase:', testcase.testcase_name);

        // Use the actual testcase graph data
        const testCaseGraph = testcase.graph_json;

        const response = await fetch(buildServerUrl('/server/testcase/execute'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            graph_json: testCaseGraph,
            device_id: deviceId,
            host_name: hostName,
            userinterface_name: userinterfaceName,
            testcase_name: blockToExecute.data.executableName || blockToExecute.data.label || 'single_block',
            async_execution: true
          }),
        });

        if (!response.ok) {
          const errorData = await response.json();
          throw new Error(errorData.error || `HTTP ${response.status}`);
        }

        const startData = await response.json();
        if (!startData.success) {
          throw new Error(startData.error || 'Failed to start testcase execution');
        }

        const executionId = startData.execution_id;
        console.log('[@CampaignBuilder:executeBlock] Testcase started with execution ID:', executionId);

        const testcaseEvent = await waitForExecutionSocketEvent(executionId, ['testcase'], 600000);
        const testcaseResult = testcaseEvent.result;
        unifiedExecution.completeExecution({
          success: testcaseResult?.success || false,
          result_type: testcaseResult?.success ? 'success' : 'failure',
          execution_time_ms: testcaseResult?.execution_time_ms || 0,
          error: testcaseEvent.error || testcaseResult?.error,
          step_count: 1,
        });

      } else if (blockToExecute.data.executableType === 'script') {
        // Execute as script using script API
        console.log('[@CampaignBuilder:executeBlock] Executing as script');

        const scriptParams: Record<string, string> = {
          host: hostName,
          device: deviceId,
          ...blockToExecute.data.parameters
        };

        const scriptNameForRequest = blockToExecute.data.executableName || blockToExecute.data.label;
        const scriptIdentity = getScriptIdentity(scriptNameForRequest);
        const response = await fetch(buildServerUrl('/server/script/execute'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            script_name: scriptNameForRequest,
            host_name: hostName,
            device_id: deviceId,
            parameters: Object.entries(scriptParams).map(([key, value]) => `${key}=${value}`).join(' '),
            ...(scriptIdentity?.prefix && { prefix: scriptIdentity.prefix }),
            ...(scriptIdentity?.display_name && { display_name: scriptIdentity.display_name }),
          }),
        });

        const initialResult = await response.json();

        if (response.status === 202 && initialResult.task_id) {
          // Async execution started
          const taskId = initialResult.task_id;
          console.log('[@CampaignBuilder:executeBlock] Script started with task ID:', taskId);

          const scriptEvent = await waitForExecutionSocketEvent(taskId, ['script'], 7200000);
          const scriptResult = scriptEvent.result || {};
          unifiedExecution.completeExecution({
            success: scriptResult.success || false,
            result_type: scriptResult.success ? 'success' : 'failure',
            execution_time_ms: scriptResult.execution_time || 0,
            error: scriptEvent.error || scriptResult.stderr,
            step_count: 1,
          });
        } else {
          // Synchronous result
          unifiedExecution.completeExecution({
            success: initialResult.success || false,
            result_type: initialResult.success ? 'success' : 'failure',
            execution_time_ms: 0,
            error: initialResult.error,
            step_count: 1,
          });
        }
      } else {
        throw new Error(`Unsupported executable type: ${blockToExecute.data.executableType}`);
      }

    } catch (error) {
      console.error('[@CampaignBuilder:executeBlock] Error executing block:', error);

      unifiedExecution.completeExecution({
        success: false,
        result_type: 'error',
        execution_time_ms: 0,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        step_count: 0,
      });

      throw error; // Re-throw for CampaignBlock to handle
    }
  }, [nodes, unifiedExecution]);

  // Computed execution state
  const isExecuting = unifiedExecution.state.isExecuting;
  const isExecutable = nodes.filter(n => n.type !== 'start' && n.type !== 'success' && n.type !== 'failure').length > 0;

  const value: CampaignBuilderContextValue = {
    state,
    unifiedExecution,
    updateCampaignConfig,
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    addNode,
    updateNode,
    deleteNode,
    selectedNode,
    selectNode,
    linkOutputToInput,
    unlinkInput,
    campaignInputs,
    campaignOutputs,
    campaignReports,
    addCampaignInput,
    addCampaignOutput,
    addCampaignReportField,
    removeCampaignInput,
    removeCampaignOutput,
    removeCampaignReportField,
    setCampaignReportsMode,
    saveCampaign,
    loadCampaign,
    fetchCampaignList,
    campaignList,
    isLoadingCampaignList,
    hasUnsavedChanges,
    resetBuilder,
    executeCurrentCampaign,
    executeBlock,
    isExecuting,
    isExecutable,
  };

  return (
    <CampaignBuilderContext.Provider value={value}>
      {children}
    </CampaignBuilderContext.Provider>
  );
};
