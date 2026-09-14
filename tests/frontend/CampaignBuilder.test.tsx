import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

// NOTE: every mocked hook below returns *stable* function/object references
// (created once at module scope inside the factory) instead of a fresh
// literal on every call. CampaignBuilder.tsx feeds several of these
// functions into useEffect dependency arrays (e.g. getAllUserInterfaces);
// a mock returning a new reference each render makes those effects re-fire
// every render and - since some unconditionally call setState with a new
// array - creates an infinite render loop that hangs the test runner
// instead of failing fast.

// Heavy visual canvas library - stub it out entirely for a smoke test.
vi.mock('reactflow', () => ({
  __esModule: true,
  default: ({ children }: { children?: React.ReactNode }) => <div data-testid="react-flow">{children}</div>,
  ReactFlowProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  ConnectionMode: { Loose: 'loose', Strict: 'strict' },
  MarkerType: { ArrowClosed: 'arrowclosed' },
}));

vi.mock('../../frontend/src/components/common/builder', () => ({
  BuilderPageLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  BuilderSidebarContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  BuilderMainContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  BuilderStatsBarContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock('../../frontend/src/components/testcase/blocks/StartBlock', () => ({ StartBlock: () => null }));
vi.mock('../../frontend/src/components/testcase/blocks/SuccessBlock', () => ({ SuccessBlock: () => null }));
vi.mock('../../frontend/src/components/testcase/blocks/FailureBlock', () => ({ FailureBlock: () => null }));
vi.mock('../../frontend/src/components/testcase/edges/SuccessEdge', () => ({ SuccessEdge: () => null }));
vi.mock('../../frontend/src/components/testcase/edges/FailureEdge', () => ({ FailureEdge: () => null }));
vi.mock('../../frontend/src/components/testcase/builder/TestCaseBuilderCanvas', () => ({
  TestCaseBuilderCanvas: () => <div data-testid="testcase-builder-canvas" />,
}));
vi.mock('../../frontend/src/components/testcase/builder/TestCaseBuilderHeader', () => ({
  TestCaseBuilderHeader: () => <h1>Campaign Builder</h1>,
}));

vi.mock('../../frontend/src/contexts/campaign/CampaignBuilderContext', () => {
  const value = {
    nodes: [] as any[],
    edges: [] as any[],
    onNodesChange: () => {},
    onEdgesChange: () => {},
    onConnect: () => {},
    addNode: () => {},
    updateNode: () => {},
    saveCampaign: async () => true,
    state: { campaign_name: '', campaign_id: null },
    fetchCampaignList: async () => {},
    campaignList: [] as any[],
    isLoadingCampaignList: false,
    hasUnsavedChanges: false,
    loadCampaign: async () => true,
    executeCurrentCampaign: async () => {},
    isExecuting: false,
    isExecutable: false,
    unifiedExecution: {
      state: { currentBlockId: null, blockStates: {}, isExecuting: false, result: null },
      resetExecution: () => {},
    },
  };
  return {
    CampaignBuilderProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    useCampaignBuilder: () => value,
  };
});

vi.mock('../../frontend/src/components/campaign/blocks/CampaignBlock', () => ({ CampaignBlock: () => null }));
vi.mock('../../frontend/src/components/campaign/builder/CampaignToolbox', () => ({
  CampaignToolbox: () => <div data-testid="campaign-toolbox" />,
}));
vi.mock('../../frontend/src/components/campaign/builder/CampaignBuilderDialogs', () => ({
  CampaignBuilderDialogs: () => null,
}));
vi.mock('../../frontend/src/components/common/ExecutionProgressOverlay', () => ({
  ExecutionProgressOverlay: () => null,
}));

vi.mock('../../frontend/src/hooks/testcase/useTestCaseSave', () => {
  const getTestCase = async () => ({ success: false, testcase: null });
  return {
    useTestCaseSave: () => ({ getTestCase }),
  };
});

vi.mock('../../frontend/src/contexts/ThemeContext', () => {
  const value = { actualMode: 'light' };
  return {
    useTheme: () => value,
  };
});

vi.mock('../../frontend/src/hooks/useHostManager', () => {
  const hostDataValue = { availableHosts: [] as any[] };
  const handleDeviceSelect = () => {};
  const handleToggleRemotePanel = () => {};
  const handleControlStateChange = () => {};
  const isDeviceLocked = () => false;
  const hostControlValue = {
    selectedHost: null,
    selectedDeviceId: null,
    isControlActive: false,
    isRemotePanelOpen: false,
    handleDeviceSelect,
    handleToggleRemotePanel,
    handleControlStateChange,
    isDeviceLocked,
  };
  return {
    useHostData: () => hostDataValue,
    useHostControl: () => hostControlValue,
  };
});

vi.mock('../../frontend/src/hooks/pages/useUserInterface', () => {
  const getAllUserInterfaces = async () => [] as any[];
  const getUserInterfaceByName = async () => null;
  return {
    useUserInterface: () => ({ getAllUserInterfaces, getUserInterfaceByName }),
  };
});

vi.mock('../../frontend/src/contexts/builder/useBuilder', () => {
  const fetchStandardBlocks = async () => {};
  return {
    useBuilder: () => ({ standardBlocks: [] as any[], fetchStandardBlocks }),
  };
});

vi.mock('../../frontend/src/hooks/useDeviceControlWithForceUnlock', () => {
  const handleDeviceControl = () => {};
  return {
    useDeviceControlWithForceUnlock: () => ({ isControlLoading: false, handleDeviceControl }),
  };
});

vi.mock('../../frontend/src/contexts/navigation/NavigationConfigContext', () => {
  const loadTreeByUserInterface = async () => ({ tree: null });
  return {
    NavigationConfigProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    useNavigationConfig: () => ({ loadTreeByUserInterface }),
  };
});

vi.mock('../../frontend/src/contexts/navigation/NavigationEditorProvider', () => ({
  NavigationEditorProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('../../frontend/src/contexts/device/DeviceDataContext', () => {
  const setControlState = () => {};
  const fetchAvailableActions = async () => {};
  return {
    useDeviceData: () => ({ setControlState, fetchAvailableActions }),
  };
});

import CampaignBuilder from '../../frontend/src/pages/CampaignBuilder';

describe('CampaignBuilder page', () => {
  it('renders without crashing', async () => {
    render(<CampaignBuilder />);

    expect(await screen.findByRole('heading', { name: 'Campaign Builder' })).toBeInTheDocument();
    expect(screen.getByTestId('react-flow')).toBeInTheDocument();
  });
});
