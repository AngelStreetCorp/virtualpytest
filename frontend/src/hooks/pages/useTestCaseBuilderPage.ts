/**
 * TestCaseBuilder Page Hook
 * 
 * Orchestrates all TestCaseBuilder page logic:
 * - Device control and host management
 * - Interface and navigation tree loading
 * - AI generation
 * - Test case operations (save, load, execute)
 * - Toolbox building
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useHostData, useHostControl } from '../useHostManager';
import { useDeviceData } from '../../contexts/device/DeviceDataContext';
import { useDeviceControlWithForceUnlock } from '../useDeviceControlWithForceUnlock';
import { useNavigationEditor } from '../navigation/useNavigationEditor';
import { useNavigationConfig } from '../../contexts/navigation/NavigationConfigContext';
import { useUserInterface } from './useUserInterface';
import { useTestCaseBuilder } from '../../contexts/testcase/TestCaseBuilderContext';
import { useTestCaseAI } from '../testcase';
import { filterCompatibleInterfaces } from '../../utils/userinterface/deviceCompatibilityUtils';
import { buildToolboxFromNavigationData } from '../../utils/toolboxBuilder';
import { useBuilder } from '../../contexts/builder/useBuilder';
import { getErrorMessage } from '../../utils/testcase/testCaseHelpers';

export interface UseTestCaseBuilderPageReturn {
  // Device & Host
  selectedHost: any;
  selectedDeviceId: string | null;
  isControlActive: boolean;
  isControlLoading: boolean;
  isRemotePanelOpen: boolean;
  showRemotePanel: boolean;
  showAVPanel: boolean;
  availableHosts: any[];
  handleDeviceSelect: (host: any | null, deviceId: string | null) => void;
  handleDeviceControl: () => Promise<void>;
  handleToggleRemotePanel: () => void;
  handleDisconnectComplete: () => void;
  isDeviceLocked: (deviceKey: string) => boolean;
  
  // Interface & Navigation
  compatibleInterfaceNames: string[];
  userinterfaceName: string;
  setUserinterfaceName: (name: string) => void;
  navNodes: any[];
  isLoadingTree: boolean; // NEW: Tree loading state
  currentTreeId: string | null; // NEW: Current tree ID
  
  // Actions & Verifications
  availableActions: any;
  availableVerifications: any;
  areActionsLoaded: boolean;
  
  // Toolbox
  dynamicToolboxConfig: any;
  
  // AI Generation
  creationMode: 'visual' | 'ai';
  setCreationMode: (mode: 'visual' | 'ai') => void;
  aiPrompt: string;
  setAiPrompt: (prompt: string) => void;
  isGenerating: boolean;
  handleGenerateWithAI: () => Promise<void>;
  
  // Test Case Operations
  testcaseName: string;
  setTestcaseName: (name: string) => void;
  description: string;
  setDescription: (desc: string) => void;
  testcaseFolder: string; // NEW
  setTestcaseFolder: (folder: string) => void; // NEW
  testcaseTags: string[]; // NEW
  setTestcaseTags: (tags: string[]) => void; // NEW
  currentTestcaseId: string | null;
  testcaseList: any[];
  isLoadingTestCaseList: boolean;
  hasUnsavedChanges: boolean;
  handleSave: () => Promise<{ success: boolean; error?: string }>;
  handleLoad: (testcaseId: string) => Promise<void>;
  handleDelete: (testcaseId: string, testcaseName: string) => Promise<void>;
  handleExecute: () => Promise<void>;
  handleNew: () => void;
  
  // Dialogs
  saveDialogOpen: boolean;
  setSaveDialogOpen: (open: boolean) => void;
  loadDialogOpen: boolean;
  setLoadDialogOpen: (open: boolean) => void;
  isLoadingTestCases: boolean;
  handleLoadClick: () => Promise<void>;
  deleteConfirmOpen: boolean;
  setDeleteConfirmOpen: (open: boolean) => void;
  deleteTargetTestCase: { id: string; name: string } | null;
  setDeleteTargetTestCase: (target: { id: string; name: string } | null) => void;
  newConfirmOpen: boolean;
  setNewConfirmOpen: (open: boolean) => void;
  handleConfirmDelete: () => Promise<void>;
  handleCancelDelete: () => void;
  handleConfirmNew: () => void;
  aiGenerateConfirmOpen: boolean;
  setAiGenerateConfirmOpen: (open: boolean) => void;
  handleConfirmAIGenerate: () => void;
  aiGenerationResult: any | null;
  showAIResultPanel: boolean;
  handleCloseAIResultPanel: () => void;
  handleRegenerateAI: () => void;
  handleShowLastGeneration: () => void;
  
  // AI Disambiguation
  disambiguationData: any | null;
  handleDisambiguationResolve: (selections: Record<string, string>, saveToDb: boolean) => void;
  handleDisambiguationCancel: () => void;
  handleDisambiguationEditPrompt: () => void;
  
  // Execution (NEW: Unified execution state)
  unifiedExecution: ReturnType<typeof useTestCaseBuilder>['unifiedExecution'];
  
  // AV Panel
  isAVPanelCollapsed: boolean;
  setIsAVPanelCollapsed: (collapsed: boolean) => void;
  isAVPanelMinimized: boolean;
  setIsAVPanelMinimized: (minimized: boolean) => void;
  captureMode: 'stream' | 'screenshot' | 'video';
  setCaptureMode: (mode: 'stream' | 'screenshot' | 'video') => void;
  isVerificationVisible: boolean;
  handleAVPanelCollapsedChange: (collapsed: boolean) => void;
  handleCaptureModeChange: (mode: 'stream' | 'screenshot' | 'video') => void;
  handleAVPanelMinimizedChange: (minimized: boolean) => void;
  isMobileOrientationLandscape: boolean;
  handleMobileOrientationChange: (isLandscape: boolean) => void;
  
  // Snackbar
  snackbar: {
    open: boolean;
    message: string;
    severity: 'success' | 'error' | 'info';
  };
  setSnackbar: (snackbar: any) => void;
  
  // TestCase Builder Context
  nodes: any[];
  edges: any[];
  selectedBlock: any;
  setSelectedBlock: (block: any) => void;
  isConfigDialogOpen: boolean;
  setIsConfigDialogOpen: (open: boolean) => void;
  executionState: any;
  isExecutable: boolean;
  addBlock: (type: string, position: any, defaultData?: any) => void;
  updateBlock: (id: string, data: any) => void;
  onNodesChange: (changes: any) => void;
  onEdgesChange: (changes: any) => void;
  onConnect: (connection: any) => void;
  setNodes: (nodes: any) => void;
  setEdges: (edges: any) => void;
}

export function useTestCaseBuilderPage(): UseTestCaseBuilderPageReturn {
  // ==================== BUILDER CONTEXT ====================
  const { standardBlocks, fetchStandardBlocks } = useBuilder();
  
  // ==================== HOST & DEVICE ====================
  const { availableHosts } = useHostData();
  const {
    selectedHost,
    selectedDeviceId,
    isControlActive,
    isRemotePanelOpen,
    showRemotePanel,
    showAVPanel,
    handleDeviceSelect: hostManagerDeviceSelect,
    handleControlStateChange,
    handleToggleRemotePanel,
    handleDisconnectComplete,
    isDeviceLocked: hostManagerIsDeviceLocked,
  } = useHostControl();
  
  // Wrapper for handleDeviceSelect - no need to convert, just pass through
  const handleDeviceSelect = hostManagerDeviceSelect;
  
  // Wrapper for isDeviceLocked to match expected signature
  const isDeviceLocked = useCallback((deviceKey: string) => {
    const [hostName, deviceId] = deviceKey.includes(':')
      ? deviceKey.split(':')
      : [deviceKey, 'device1'];
    
    const host = availableHosts.find((h: any) => h.host_name === hostName);
    return hostManagerIsDeviceLocked(host || null, deviceId);
  }, [availableHosts, hostManagerIsDeviceLocked]);
  
  // ==================== INTERFACE & NAVIGATION (EARLY DECLARATION) ====================
  // Declare currentTreeId early so it can be used by device control hook
  const [currentTreeId, setCurrentTreeId] = useState<string | null>(null);
  const [isLoadingTree, setIsLoadingTree] = useState(false);
  
  // ==================== SNACKBAR (EARLY DECLARATION) ====================
  // Declare snackbar early so it can be used in control error display
  const [snackbar, setSnackbar] = useState<{
    open: boolean;
    message: string;
    severity: 'success' | 'error' | 'info';
  }>({
    open: false,
    message: '',
    severity: 'info',
  });

  const showSnackbar = useCallback(
    (message: string, severity: 'success' | 'error' | 'info' = 'info') => {
      setSnackbar({
        open: true,
        message,
        severity,
      });
    },
    []
  );
  
  // Use enhanced device control hook with force unlock and tree_id support
  const {
    isControlLoading,
    handleDeviceControl,
    controlError,
    clearError,
  } = useDeviceControlWithForceUnlock({
    host: selectedHost,
    device_id: selectedDeviceId,
    sessionId: 'testcase-builder-session',
    autoCleanup: true,
    tree_id: currentTreeId || undefined, // Pass tree_id for cache building
    requireTreeId: true, // TestCaseBuilder requires tree_id for navigation
    onControlStateChange: handleControlStateChange,
  });
  
  // Show control errors
  useEffect(() => {
    if (controlError) {
      showSnackbar(controlError, 'error');
      clearError();
    }
  }, [controlError, clearError, showSnackbar]);
  
  // ==================== DEVICE DATA ====================
  const {
    setControlState,
    getAvailableActions,
    getAvailableVerificationTypes,
    availableActionsLoading,
    fetchAvailableActions,
    setUserinterfaceName: setDeviceDataUserinterfaceName,
    fetchReferences,
  } = useDeviceData();
  
  // ==================== AUTO-LOAD FROM SESSION STORAGE ====================
  // Check if there's a testcase ID to load from TestCaseEditor
  // Note: loadTestCase will be extracted from useTestCaseBuilder() later
  const hasCheckedSessionStorage = useRef(false);
  
  useEffect(() => {
    setControlState(selectedHost, selectedDeviceId, isControlActive);
  }, [selectedHost, selectedDeviceId, isControlActive, setControlState]);

  useEffect(() => {
    if (!isControlActive || !selectedHost || !selectedDeviceId) return;

    const timer = setTimeout(async () => {
      await fetchAvailableActions(true);
      // Fetch standard blocks after control with host_name
      if (selectedHost?.host_name) {
        await fetchStandardBlocks(selectedHost.host_name, true);
      }
    }, 1000);

    return () => clearTimeout(timer);
  }, [isControlActive, selectedHost, selectedDeviceId, fetchAvailableActions, fetchStandardBlocks]);
  
  const availableActions = getAvailableActions();
  const availableVerifications = getAvailableVerificationTypes();
  const areActionsLoaded = isControlActive && !availableActionsLoading && Object.values(availableActions || {}).flat().length > 0;
  
  // ==================== INTERFACE & NAVIGATION ====================
  const { setUserInterfaceFromProps } = useNavigationEditor();
  const { loadTreeByUserInterface } = useNavigationConfig();
  const { getAllUserInterfaces, getUserInterfaceByName } = useUserInterface();
  const { generateTestCaseFromPrompt, saveDisambiguationAndRegenerate } = useTestCaseAI();
  
  const [compatibleInterfaceNames, setCompatibleInterfaceNames] = useState<string[]>([]);
  const [navNodes, setNavNodes] = useState<any[]>([]);
  // Note: currentTreeId is declared earlier for use in device control hook
  
  const {
    userinterfaceName,
    setUserinterfaceName,
    setAvailableNodes,
  } = useTestCaseBuilder();

  // Mirror the loaded navigation-tree nodes (navNodes) into the builder
  // context's availableNodes so the generic Navigation block's inline picker
  // (InlineNavigationConfig) has the destinations to choose from — reusing the
  // tree the toolbox already loaded instead of a separate failing fetch.
  useEffect(() => {
    setAvailableNodes(navNodes as any);
  }, [navNodes, setAvailableNodes]);

  // Keep DeviceDataContext's userinterface name in lockstep with the builder's
  // selected UI. References are bucketed by this name (DeviceDataContext:
  // bucketKey = userinterfaceName || originName), so the
  // VerificationConfigDialog can read them back via getModelReferences(name) —
  // exactly like the Navigation Node/Edge dialogs do.
  useEffect(() => {
    setDeviceDataUserinterfaceName(userinterfaceName || null);
  }, [userinterfaceName, setDeviceDataUserinterfaceName]);

  // Fetch references once control is active so the verification block config
  // dialog can offer existing references to pick (rather than forcing manual
  // params). Depends on userinterfaceName so it runs after the sync effect
  // above lands in context state and references bucket under the right key.
  // force=true bypasses the per-host dedup.
  useEffect(() => {
    if (!isControlActive || !selectedHost || !selectedDeviceId || !userinterfaceName) return;
    void fetchReferences(true);
  }, [isControlActive, selectedHost, selectedDeviceId, userinterfaceName, fetchReferences]);

  // Load compatible interfaces - using shared compatibility logic
  useEffect(() => {
    const loadCompatibleInterfaces = async () => {
      if (!selectedDeviceId || !selectedHost) {
        setCompatibleInterfaceNames([]);
        setUserinterfaceName('');
        return;
      }
      
      try {
        const selectedDevice = selectedHost.devices?.find((d: any) => d.device_id === selectedDeviceId);
        
        if (!selectedDevice) {
          console.warn('[@useTestCaseBuilderPage] Selected device not found');
          return;
        }
        
        const interfaces = await getAllUserInterfaces();
        
        // Use shared compatibility utility
        const compatibleInterfaces = filterCompatibleInterfaces(interfaces, selectedDevice);
        
        const names = compatibleInterfaces.map((ui: any) => ui.name);
        
        setCompatibleInterfaceNames(names);
        
        if (names.length > 0 && !names.includes(userinterfaceName)) {
          setUserinterfaceName(names[0]);
        }
      } catch (error) {
        console.error('[@useTestCaseBuilderPage] Failed to load compatible interfaces:', error);
      }
    };
    
    loadCompatibleInterfaces();
  }, [selectedDeviceId, selectedHost, getAllUserInterfaces, userinterfaceName, setUserinterfaceName]);
  
  // Load navigation tree
  useEffect(() => {
    const loadNavigationTree = async () => {
      if (!selectedDeviceId || !userinterfaceName) {
        setNavNodes([]);
        setCurrentTreeId(null);
        setIsLoadingTree(false);
        return;
      }
      
      setIsLoadingTree(true);
      
      try {
        const userInterface = await getUserInterfaceByName(userinterfaceName);

        if (userInterface) {
          // Load tree with nested trees included so we can navigate to any node
          const result = await loadTreeByUserInterface(userInterface.id, { includeNested: true });

          if (!result) {
            console.log('[@useTestCaseBuilderPage] ℹ️ No navigation tree available for this interface');
            setNavNodes([]);
            setCurrentTreeId(null);
            setUserInterfaceFromProps(userInterface);
            return;
          }

          setUserInterfaceFromProps(userInterface);
          
          console.log('[@useTestCaseBuilderPage] 🔍 DEBUG result structure:', {
            result_tree_id: result?.tree?.id,
            userInterface_root_tree: userInterface.root_tree,
            nested_trees_count: result?.nested_trees_count,
            total_nodes: result?.tree?.metadata?.nodes?.length,
            full_result: result
          });
          
          const nodes = result?.tree?.metadata?.nodes || result?.nodes || [];
          const treeId = result?.tree?.id || userInterface.root_tree;
          
          setNavNodes(nodes);
          setCurrentTreeId(treeId);
          
          console.log('[@useTestCaseBuilderPage] ✅ Loaded navigation tree with nested trees:', {
            interface: userinterfaceName,
            treeId: treeId,
            nestedTreesCount: result?.nested_trees_count || 0,
            nodeCount: nodes.length
          });
          
          if (!treeId) {
            console.error('[@useTestCaseBuilderPage] ❌ CRITICAL: tree_id is undefined!', {
              userInterface,
              result
            });
          } else {
            console.log('[@useTestCaseBuilderPage] 🗺️ tree_id ready for cache building:', treeId);
          }
        }
      } catch (error) {
        console.warn('[@useTestCaseBuilderPage] ⚠️ Failed to load navigation tree (this may be expected):', error);
        setNavNodes([]);
        setCurrentTreeId(null);
      } finally {
        setIsLoadingTree(false);
      }
    };
    
    loadNavigationTree();
  }, [selectedDeviceId, userinterfaceName, getUserInterfaceByName, loadTreeByUserInterface, setUserInterfaceFromProps]);
  
  // ==================== TOOLBOX ====================
  const dynamicToolboxConfig = useMemo(() => {
    if (!selectedDeviceId || !userinterfaceName || navNodes.length === 0) {
      return null;
    }
    
    // Only show toolbox after taking control, not just on device selection
    return buildToolboxFromNavigationData(navNodes, availableActions, availableVerifications, standardBlocks, isControlActive);
  }, [selectedDeviceId, userinterfaceName, navNodes, availableActions, availableVerifications, standardBlocks, isControlActive]);
  
  // ==================== TEST CASE CONTEXT ====================
  const {
    nodes,
    edges,
    selectedBlock,
    setSelectedBlock,
    isConfigDialogOpen,
    setIsConfigDialogOpen,
    executionState,
    isExecutable,
    testcaseName,
    setTestcaseName,
    description,
    setDescription,
    testcaseFolder, // NEW
    setTestcaseFolder, // NEW
    testcaseTags, // NEW
    setTestcaseTags, // NEW
    currentTestcaseId,
    testcaseList,
    isLoadingTestCaseList,
    hasUnsavedChanges,
    addBlock,
    updateBlock,
    onNodesChange,
    onEdgesChange,
    onConnect,
    saveCurrentTestCase,
    loadTestCase,
    executeCurrentTestCase,
    fetchTestCaseList,
    deleteTestCaseById,
    resetBuilder,
    setNodes,
    setEdges,
    unifiedExecution, // 🆕 ADD: Extract unifiedExecution from context
  } = useTestCaseBuilder();
  
  // ==================== AI GENERATION ====================
  const [creationMode, setCreationMode] = useState<'visual' | 'ai'>('visual');
  const [aiPrompt, setAiPrompt] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  
  // ==================== DIALOGS ====================
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [loadDialogOpen, setLoadDialogOpen] = useState(false);
  const [isLoadingTestCases, setIsLoadingTestCases] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteTargetTestCase, setDeleteTargetTestCase] = useState<{ id: string; name: string } | null>(null);
  const [newConfirmOpen, setNewConfirmOpen] = useState(false);
  const [aiGenerateConfirmOpen, setAiGenerateConfirmOpen] = useState(false);
  
  // AI Generation Result Panel State
  const [aiGenerationResult, setAiGenerationResult] = useState<any | null>(null);
  const [showAIResultPanel, setShowAIResultPanel] = useState(false);
  
  // AI Disambiguation state
  const [disambiguationData, setDisambiguationData] = useState<any | null>(null);
  
  // Handle Load button click - fetch data first, then open dialog
  const handleLoadClick = useCallback(async () => {
    setIsLoadingTestCases(true);
    await fetchTestCaseList();
    setIsLoadingTestCases(false);
    setLoadDialogOpen(true);
  }, [fetchTestCaseList]);
  
  // Remove the useEffect that fetches when dialog opens since we fetch before opening now
  // useEffect(() => {
  //   if (loadDialogOpen) {
  //     fetchTestCaseList();
  //   }
  // }, [loadDialogOpen, fetchTestCaseList]);
  
  // ==================== AUTO-LOAD FROM SESSION STORAGE ====================
  // Auto-load testcase from TestCaseEditor if stored in sessionStorage
  useEffect(() => {
    if (hasCheckedSessionStorage.current) return;
    
    const testcaseToLoad = sessionStorage.getItem('testcase_to_load');
    if (testcaseToLoad) {
      console.log('[@useTestCaseBuilderPage] Auto-loading testcase from sessionStorage:', testcaseToLoad);
      hasCheckedSessionStorage.current = true;
      
      // Clear the flag
      sessionStorage.removeItem('testcase_to_load');
      
      // Load the testcase after a short delay to let the UI render
      setTimeout(() => {
        loadTestCase(testcaseToLoad).then(() => {
          console.log('[@useTestCaseBuilderPage] Testcase loaded successfully');
          showSnackbar('Test case loaded successfully', 'success');
        }).catch((error) => {
          console.error('[@useTestCaseBuilderPage] Failed to load testcase:', error);
          showSnackbar(`Failed to load test case: ${getErrorMessage(error)}`, 'error');
        });
      }, 100);
    } else {
      hasCheckedSessionStorage.current = true;
    }
  }, [loadTestCase, showSnackbar]);
  
  // ==================== AV PANEL ====================
  const [isAVPanelCollapsed, setIsAVPanelCollapsed] = useState(true);
  const [isAVPanelMinimized, setIsAVPanelMinimized] = useState(false);
  const [captureMode, setCaptureMode] = useState<'stream' | 'screenshot' | 'video'>('stream');
  const [isMobileOrientationLandscape, setIsMobileOrientationLandscape] = useState(false);
  const isVerificationVisible = captureMode === 'screenshot' || captureMode === 'video';
  
  const handleAVPanelCollapsedChange = useCallback((isCollapsed: boolean) => {
    setIsAVPanelCollapsed(isCollapsed);
  }, []);
  
  const handleCaptureModeChange = useCallback((mode: 'stream' | 'screenshot' | 'video') => {
    setCaptureMode(mode);
  }, []);
  
  const handleAVPanelMinimizedChange = useCallback((isMinimized: boolean) => {
    setIsAVPanelMinimized(isMinimized);
  }, []);
  
  const handleMobileOrientationChange = useCallback((isLandscape: boolean) => {
    setIsMobileOrientationLandscape(isLandscape);
  }, []);
  
  // ==================== SNACKBAR ====================
  // Note: snackbar state is declared earlier for use in control error display
  
  // ==================== TEST CASE OPERATIONS ====================
  const handleSave = useCallback(async (): Promise<{ success: boolean; error?: string }> => {
    const result = await saveCurrentTestCase();
    if (result.success) {
      // Don't show toast - success is shown in dialog with green tick
      // Don't close dialog here - let the caller handle it
      return result;
    } else {
      showSnackbar(`Save failed: ${result.error}`, 'error');
      return result;
    }
  }, [saveCurrentTestCase, showSnackbar]);
  
  const handleLoad = useCallback(async (testcaseId: string) => {
    await loadTestCase(testcaseId);
    setLoadDialogOpen(false);
    showSnackbar(`Test case "${testcaseName}" loaded successfully`, 'success');
  }, [loadTestCase, testcaseName, showSnackbar]);
  
  // Ref to store promise resolver for delete confirmation
  const deletePromiseRef = useRef<{ resolve: () => void; reject: (error: Error) => void } | null>(null);
  
  const handleDelete = useCallback(async (testcaseId: string, testcaseName: string): Promise<void> => {
    // Show confirmation dialog first and return a promise
    return new Promise((resolve, reject) => {
      setDeleteTargetTestCase({ id: testcaseId, name: testcaseName });
      setDeleteConfirmOpen(true);
      
      // Store promise resolver in ref
      deletePromiseRef.current = { resolve, reject };
    });
  }, []);
  
  const handleConfirmDelete = useCallback(async () => {
    if (deleteTargetTestCase) {
      try {
        await deleteTestCaseById(deleteTargetTestCase.id);
        showSnackbar(`Test case "${deleteTargetTestCase.name}" deleted!`, 'success');
        
        // Resolve the promise to notify TestCaseSelector
        if (deletePromiseRef.current) {
          deletePromiseRef.current.resolve();
          deletePromiseRef.current = null;
        }
      } catch (error) {
        showSnackbar(`Failed to delete test case: ${getErrorMessage(error)}`, 'error');
        
        // Reject the promise on error
        if (deletePromiseRef.current) {
          deletePromiseRef.current.reject(error instanceof Error ? error : new Error('Delete failed'));
          deletePromiseRef.current = null;
        }
      } finally {
        setDeleteConfirmOpen(false);
        setDeleteTargetTestCase(null);
      }
    }
  }, [deleteTargetTestCase, deleteTestCaseById, showSnackbar]);
  
  const handleCancelDelete = useCallback(() => {
    // Reject the promise when user cancels
    if (deletePromiseRef.current) {
      deletePromiseRef.current.reject(new Error('Delete cancelled by user'));
      deletePromiseRef.current = null;
    }
    setDeleteConfirmOpen(false);
    setDeleteTargetTestCase(null);
  }, []);
  
  const handleExecute = useCallback(async () => {
    if (!selectedHost?.host_name) {
      showSnackbar('Please select a host first', 'error');
      return;
    }
    
    // Execute without showing toast - ExecutionProgressBar shows the status
    await executeCurrentTestCase(selectedHost.host_name);
  }, [selectedHost, executeCurrentTestCase, showSnackbar]);
  
  const handleNew = useCallback(() => {
    setNewConfirmOpen(true);
  }, []);
  
  const handleConfirmNew = useCallback(() => {
    resetBuilder();
    setCreationMode('visual');
    setAiPrompt('');
    setNewConfirmOpen(false);
  }, [resetBuilder, setCreationMode, setAiPrompt]);
  
  // ==================== AI GENERATION ====================
  const handleGenerateWithAI = useCallback(async () => {
    if (!aiPrompt.trim()) {
      showSnackbar('Please enter a prompt', 'error');
      return;
    }

    if (!userinterfaceName) {
      showSnackbar('Please select a user interface', 'error');
      return;
    }

    if (!selectedHost) {
      showSnackbar('Please select a host device', 'error');
      return;
    }

    if (!isControlActive) {
      showSnackbar('Please take control of the device first', 'error');
      return;
    }

    // Check for unsaved changes or existing nodes
    const hasExistingGraph = nodes.length > 2; // More than START and SUCCESS nodes
    const hasCurrentTestCase = !!currentTestcaseId; // Has a loaded test case
    
    // Only show warning if there's actual content to lose (existing graph OR saved test case with changes)
    if (hasExistingGraph && (hasUnsavedChanges || hasCurrentTestCase)) {
      // Show confirmation dialog
      setAiGenerateConfirmOpen(true);
      return;
    }

    // Proceed with generation
    await performAIGeneration();
  }, [aiPrompt, userinterfaceName, selectedHost, hasUnsavedChanges, nodes.length, currentTestcaseId, showSnackbar]);

  const performAIGeneration = useCallback(async () => {
    setIsGenerating(true);
    
    try {
      console.log('[@useTestCaseBuilderPage] Starting AI generation');
      const result = await generateTestCaseFromPrompt(
        aiPrompt, 
        userinterfaceName,
        selectedDeviceId || 'device1',
        selectedHost!.host_name
      );
      
      console.log('[@useTestCaseBuilderPage] AI generation result:', {
        success: result.success,
        needs_disambiguation: result.needs_disambiguation,
        has_graph: !!result.graph
      });
      
      // Handle disambiguation
      if (result.needs_disambiguation) {
        console.log('[@useTestCaseBuilderPage] Disambiguation needed, showing modal');
        setDisambiguationData(result);
        setIsGenerating(false);
        return;
      }
      
      if (result.success && result.graph) {
        // Load graph onto ReactFlow canvas (like loading a test case)
        const loadedNodes = result.graph.nodes.map((node: any) => ({
          id: node.id,
          type: node.type as any,
          position: node.position,
          data: node.data
        }));
        
        const loadedEdges = result.graph.edges.map((edge: any) => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          sourceHandle: edge.sourceHandle,
          type: edge.type as any,
          style: { 
            stroke: edge.type === 'success' ? '#10b981' : '#ef4444',
            strokeWidth: 2
          }
        }));
        
        // 🆕 AUTO-LAYOUT: Apply vertical layout immediately after AI generation
        const { getLayoutedElements } = await import('../../components/testcase/ai/autoLayout');
        const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
          loadedNodes,
          loadedEdges,
          { direction: 'TB' } // Force vertical layout
        );
        
        setNodes(layoutedNodes);
        setEdges(layoutedEdges);
        
        // Store the generation result for the result panel
        setAiGenerationResult(result);
        setShowAIResultPanel(true);
        
        // Switch to visual mode to show the graph
        setCreationMode('visual');
      } else {
        showSnackbar(`Generation failed: ${result.error || 'Unknown error'}`, 'error');
      }
    } catch (error) {
      console.error('AI generation error:', error);
      showSnackbar(`Generation failed: ${getErrorMessage(error)}`, 'error');
    } finally {
      setIsGenerating(false);
      setAiGenerateConfirmOpen(false); // Close dialog after generation
    }
  }, [aiPrompt, userinterfaceName, selectedHost, selectedDeviceId, setNodes, setEdges, setTestcaseName, setDescription, generateTestCaseFromPrompt, setCreationMode, showSnackbar]);
  
  const handleConfirmAIGenerate = useCallback(() => {
    performAIGeneration();
  }, [performAIGeneration]);
  
  const handleCloseAIResultPanel = useCallback(() => {
    setShowAIResultPanel(false);
    // Keep aiGenerationResult so user can reopen it
  }, []);
  
  const handleShowLastGeneration = useCallback(() => {
    if (aiGenerationResult) {
      setShowAIResultPanel(true);
    }
  }, [aiGenerationResult]);
  
  const handleRegenerateAI = useCallback(() => {
    setShowAIResultPanel(false);
    setAiGenerationResult(null);
    setCreationMode('ai'); // Switch back to AI mode
  }, [setCreationMode]);
  
  // Disambiguation handlers
  const handleDisambiguationResolve = useCallback(async (
    selections: Record<string, string>,
    saveToDb: boolean
  ) => {
    console.log('[@useTestCaseBuilderPage] Resolving disambiguation', { selections, saveToDb });
    setDisambiguationData(null);
    setIsGenerating(true);
    
    try {
      if (saveToDb) {
        // Convert selections to array format expected by API
        const selectionsArray = Object.entries(selections).map(([phrase, resolved]) => ({
          phrase,
          resolved
        }));
        
        // Save disambiguation choices
        await saveDisambiguationAndRegenerate(
          aiPrompt,
          selectionsArray,
          userinterfaceName,
          selectedDeviceId || 'device1',
          selectedHost!.host_name
        );
      }
      
      // Regenerate with resolved selections
      await performAIGeneration();
    } catch (error) {
      console.error('[@useTestCaseBuilderPage] Disambiguation resolve error:', error);
      showSnackbar(`Failed to apply disambiguation: ${getErrorMessage(error)}`, 'error');
      setIsGenerating(false);
    }
  }, [aiPrompt, userinterfaceName, selectedDeviceId, selectedHost, performAIGeneration, saveDisambiguationAndRegenerate, showSnackbar]);
  
  const handleDisambiguationCancel = useCallback(() => {
    console.log('[@useTestCaseBuilderPage] Disambiguation cancelled');
    setDisambiguationData(null);
    setIsGenerating(false);
  }, []);
  
  const handleDisambiguationEditPrompt = useCallback(() => {
    console.log('[@useTestCaseBuilderPage] Edit prompt requested from disambiguation');
    setDisambiguationData(null);
    setIsGenerating(false);
    setCreationMode('ai'); // Switch to AI mode to edit prompt
  }, [setCreationMode]);
  
  // ==================== RETURN ====================
  return {
    // Device & Host
    selectedHost,
    selectedDeviceId,
    isControlActive,
    isControlLoading,
    isRemotePanelOpen,
    showRemotePanel,
    showAVPanel,
    availableHosts,
    handleDeviceSelect,
    handleDeviceControl,
    handleToggleRemotePanel,
    handleDisconnectComplete,
    isDeviceLocked,
    
    // Interface & Navigation
    compatibleInterfaceNames,
    userinterfaceName,
    setUserinterfaceName,
    navNodes,
    isLoadingTree,
    currentTreeId,
    
    // Actions & Verifications
    availableActions,
    availableVerifications,
    areActionsLoaded,
    
    // Toolbox
    dynamicToolboxConfig,
    
    // AI Generation
    creationMode,
    setCreationMode,
    aiPrompt,
    setAiPrompt,
    isGenerating,
    handleGenerateWithAI,
    
    // Test Case Operations
    testcaseName,
    setTestcaseName,
    description,
    setDescription,
    testcaseFolder, // NEW
    setTestcaseFolder, // NEW
    testcaseTags, // NEW
    setTestcaseTags, // NEW
    currentTestcaseId,
    testcaseList,
    isLoadingTestCaseList,
    hasUnsavedChanges,
    handleSave,
    handleLoad,
    handleDelete,
    handleExecute,
    handleNew,
    
    // Dialogs
    saveDialogOpen,
    setSaveDialogOpen,
    loadDialogOpen,
    setLoadDialogOpen,
    isLoadingTestCases,
    handleLoadClick,
    deleteConfirmOpen,
    setDeleteConfirmOpen,
    deleteTargetTestCase,
    setDeleteTargetTestCase,
    newConfirmOpen,
    setNewConfirmOpen,
    handleConfirmDelete,
    handleCancelDelete,
    handleConfirmNew,
    aiGenerateConfirmOpen,
    setAiGenerateConfirmOpen,
    handleConfirmAIGenerate,
    aiGenerationResult,
    showAIResultPanel,
    handleCloseAIResultPanel,
    handleRegenerateAI,
    handleShowLastGeneration,
    
    // AI Disambiguation
    disambiguationData,
    handleDisambiguationResolve,
    handleDisambiguationCancel,
    handleDisambiguationEditPrompt,
    
    // AV Panel
    isAVPanelCollapsed,
    setIsAVPanelCollapsed,
    isAVPanelMinimized,
    setIsAVPanelMinimized,
    captureMode,
    setCaptureMode,
    isVerificationVisible,
    handleAVPanelCollapsedChange,
    handleCaptureModeChange,
    handleAVPanelMinimizedChange,
    isMobileOrientationLandscape,
    handleMobileOrientationChange,
    
    // Snackbar
    snackbar,
    setSnackbar,
    
    // TestCase Builder Context
    nodes,
    edges,
    selectedBlock,
    setSelectedBlock,
    isConfigDialogOpen,
    setIsConfigDialogOpen,
    executionState,
    isExecutable,
    addBlock,
    updateBlock,
    onNodesChange,
    onEdgesChange,
    onConnect,
    setNodes,
    setEdges,
    
    // 🆕 NEW: Unified execution state
    unifiedExecution,
  };
}

