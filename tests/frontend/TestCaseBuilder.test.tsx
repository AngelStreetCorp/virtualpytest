import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

// TestCaseBuilder renders a ReactFlow canvas, which doesn't work in jsdom.
// Mock reactflow itself so the page can mount as a smoke test.
vi.mock('reactflow', () => {
  const ReactFlow = ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="reactflow-mock">{children}</div>
  );
  const ReactFlowProvider = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  return {
    __esModule: true,
    default: ReactFlow,
    ReactFlow,
    ReactFlowProvider,
    addEdge: (edge: any, edges: any[]) => [...edges, edge],
    MarkerType: { ArrowClosed: 'arrowclosed' },
  };
});
vi.mock('reactflow/dist/style.css', () => ({}));

vi.mock('../../frontend/src/hooks/pages/useTestCaseBuilderPage', () => ({
  useTestCaseBuilderPage: () => ({
    nodes: [],
    edges: [],
    setNodes: () => {},
    setEdges: () => {},
    onNodesChange: () => {},
    onEdgesChange: () => {},
    onConnect: () => {},
    addBlock: () => {},
    updateBlock: () => {},
    selectedBlock: null,
    setSelectedBlock: () => {},
    isConfigDialogOpen: false,
    setIsConfigDialogOpen: () => {},
    creationMode: 'manual',
    setCreationMode: () => {},
    selectedHost: null,
    selectedDeviceId: null,
    isControlActive: false,
    isControlLoading: false,
    isRemotePanelOpen: false,
    availableHosts: [],
    isDeviceLocked: false,
    handleDeviceSelect: () => {},
    handleDeviceControl: () => {},
    handleToggleRemotePanel: () => {},
    compatibleInterfaceNames: [],
    userinterfaceName: '',
    setUserinterfaceName: () => {},
    isLoadingTree: false,
    testcaseName: '',
    setTestcaseName: () => {},
    hasUnsavedChanges: false,
    handleNew: () => {},
    handleLoadClick: () => {},
    isLoadingTestCases: false,
    setSaveDialogOpen: () => {},
    saveDialogOpen: false,
    currentTestcaseId: null,
    handleExecute: () => {},
    executionState: { isExecuting: false, result: null },
    isExecutable: false,
    unifiedExecution: {
      state: {
        currentBlockId: null,
        previousBlockId: null,
        blockStates: new Map(),
        isExecuting: false,
        result: null,
      },
      resetExecution: () => {},
    },
    dynamicToolboxConfig: {},
    areActionsLoaded: false,
    aiPrompt: '',
    setAiPrompt: () => {},
    isGenerating: false,
    handleGenerateWithAI: () => {},
    aiGenerationResult: null,
    handleShowLastGeneration: () => {},
    showAIResultPanel: false,
    handleCloseAIResultPanel: () => {},
    handleRegenerateAI: () => {},
    disambiguationData: null,
    handleDisambiguationResolve: () => {},
    handleDisambiguationCancel: () => {},
    handleDisambiguationEditPrompt: () => {},
    description: '',
    setDescription: () => {},
    testcaseFolder: '',
    setTestcaseFolder: () => {},
    testcaseTags: [],
    setTestcaseTags: () => {},
    loadDialogOpen: false,
    setLoadDialogOpen: () => {},
    testcaseList: [],
    handleSave: () => {},
    handleLoad: () => {},
    handleDelete: () => {},
    aiGenerateConfirmOpen: false,
    setAiGenerateConfirmOpen: () => {},
    handleConfirmAIGenerate: () => {},
    deleteConfirmOpen: false,
    setDeleteConfirmOpen: () => {},
    deleteTargetTestCase: null,
    handleCancelDelete: () => {},
    handleConfirmDelete: () => {},
    newConfirmOpen: false,
    setNewConfirmOpen: () => {},
    handleConfirmNew: () => {},
    snackbar: { open: false, message: '', severity: 'info' },
    setSnackbar: () => {},
    showRemotePanel: false,
    showAVPanel: false,
    isAVPanelCollapsed: false,
    isAVPanelMinimized: false,
    captureMode: 'stream',
    isVerificationVisible: false,
    handleDisconnectComplete: () => {},
    handleAVPanelCollapsedChange: () => {},
    handleAVPanelMinimizedChange: () => {},
    handleCaptureModeChange: () => {},
    isMobileOrientationLandscape: false,
    handleMobileOrientationChange: () => {},
  }),
}));

vi.mock('../../frontend/src/contexts/testcase/TestCaseBuilderContext', () => ({
  TestCaseBuilderProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useTestCaseBuilder: () => ({
    undo: () => {},
    redo: () => {},
    canUndo: false,
    canRedo: false,
    resetBuilder: () => {},
    copyBlock: () => {},
    pasteBlock: () => {},
    scriptInputs: [],
    scriptOutputs: [],
    scriptVariables: [],
    executionOutputValues: {},
  }),
}));

vi.mock('../../frontend/src/contexts/navigation/NavigationEditorProvider', () => ({
  NavigationEditorProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('../../frontend/src/contexts/navigation/NavigationConfigContext', () => ({
  NavigationConfigProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('../../frontend/src/contexts/ThemeContext', () => ({
  useTheme: () => ({ actualMode: 'light' }),
}));

vi.mock('../../frontend/src/components/testcase/builder/TestCaseBuilderHeader', () => ({
  TestCaseBuilderHeader: () => <div data-testid="testcase-builder-header">TestCaseBuilder Header</div>,
}));

vi.mock('../../frontend/src/components/testcase/builder/TestCaseBuilderSidebar', () => ({
  TestCaseBuilderSidebar: () => <div data-testid="testcase-builder-sidebar" />,
}));

vi.mock('../../frontend/src/components/testcase/builder/TestCaseBuilderCanvas', () => ({
  TestCaseBuilderCanvas: () => <div data-testid="testcase-builder-canvas" />,
}));

vi.mock('../../frontend/src/components/common/DeviceControlPanels', () => ({
  DeviceControlPanels: () => null,
}));

vi.mock('../../frontend/src/components/common/ExecutionProgressOverlay', () => ({
  ExecutionProgressOverlay: () => null,
}));

vi.mock('../../frontend/src/components/common/VersionHistoryDialog', () => ({
  VersionHistoryDialog: () => null,
}));

vi.mock('../../frontend/src/components/testcase/dialogs/ActionConfigDialog', () => ({
  ActionConfigDialog: () => null,
}));

vi.mock('../../frontend/src/components/testcase/dialogs/LoopConfigDialog', () => ({
  LoopConfigDialog: () => null,
}));

vi.mock('../../frontend/src/components/testcase/dialogs/StandardBlockConfigDialog', () => ({
  StandardBlockConfigDialog: () => null,
}));

vi.mock('../../frontend/src/components/testcase/dialogs/ApiCallConfigModal', () => ({
  ApiCallConfigModal: () => null,
}));

vi.mock('../../frontend/src/components/testcase/builder/TestCaseBuilderDialogs', () => ({
  TestCaseBuilderDialogs: () => null,
}));

vi.mock('../../frontend/src/components/testcase/builder/AIGenerationResultPanel', () => ({
  AIGenerationResultPanel: () => null,
}));

vi.mock('../../frontend/src/components/ai/PromptDisambiguation', () => ({
  PromptDisambiguation: () => null,
}));

import TestCaseBuilder from '../../frontend/src/pages/TestCaseBuilder';

describe('TestCaseBuilder page', () => {
  it('renders without crashing', () => {
    render(<TestCaseBuilder />);

    expect(screen.getByTestId('testcase-builder-header')).toBeInTheDocument();
    expect(screen.getByTestId('reactflow-mock')).toBeInTheDocument();
  });
});
