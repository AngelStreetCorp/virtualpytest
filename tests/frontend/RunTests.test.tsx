import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

// NOTE: every mocked hook below returns the SAME object/function references on
// every call (hoisted to module scope) rather than a fresh literal per render.
// RunTests.tsx has effects/callbacks that depend on these values; a fresh
// literal per call makes React think the dependency changed every render,
// causing an infinite re-render loop severe enough to crash the Vitest worker
// outright (not just fail slowly) — hit this exact bug backfilling on 2026-09-06.

const responsiveMode = {
  mode: 'desktop',
  isMobile: false,
  isTablet: false,
  isDesktop: true,
  theme: {},
};
vi.mock('../../frontend/src/hooks/useResponsiveMode', () => ({
  useResponsiveMode: () => responsiveMode,
}));

const resizableColumns = {
  widths: {},
  onMouseDown: () => () => {},
  headerCellSx: () => ({}),
  bodyCellSx: () => ({}),
  resizeHandleSx: {},
};
vi.mock('../../frontend/src/hooks/useResizableColumns', () => ({
  useResizableColumns: () => resizableColumns,
}));

const scriptHook = {
  executeScript: async () => ({ success: true, stdout: '', stderr: '', exit_code: 0 }),
  executeMultipleScripts: async () => ({}),
  waitForTask: async () => ({ success: true, stdout: '', stderr: '', exit_code: 0 }),
  isExecuting: false,
  executingIds: [],
  lastResult: null,
  error: null,
};
vi.mock('../../frontend/src/hooks/script/useScript', () => ({
  useScript: () => scriptHook,
}));

const campaignExecutionProgress = {
  current_script_index: 0,
  total_scripts: 0,
  completed_scripts: 0,
  successful_scripts: 0,
  failed_scripts: 0,
};
const campaignBuilderState = {
  config: {},
  selectedHost: '',
  selectedDevice: '',
  availableScripts: [],
  scriptAnalysisCache: {},
  isValid: true,
  validationErrors: [],
};
const campaignHook = {
  executeCampaign: async () => ({ success: true, result: {} }),
  isExecuting: false,
  currentExecution: null,
  executionProgress: campaignExecutionProgress,
  campaignConfig: {},
  updateCampaignConfig: () => {},
  resetCampaignConfig: () => {},
  availableScripts: [],
  aiTestCasesInfo: [],
  loadAvailableScripts: async () => {},
  addScript: () => {},
  removeScript: () => {},
  reorderScripts: () => {},
  updateScriptConfiguration: () => {},
  scriptAnalysisCache: {},
  loadScriptAnalysis: async () => null,
  validateCampaignConfig: () => ({ valid: true, errors: [], warnings: [] }),
  validateScriptConfiguration: () => ({ script_name: '', valid: true, errors: [], parameter_errors: {} }),
  campaignHistory: [],
  builderState: campaignBuilderState,
  isLoading: false,
  error: null,
};
vi.mock('../../frontend/src/hooks/pages/useCampaign', () => ({
  useCampaign: () => campaignHook,
}));

const recentExecutions = {
  success: true,
  running_executions: [],
  queued_executions: [],
  completed_executions: [],
  running_count: 0,
  queued_count: 0,
  completed_count: 0,
};
const deploymentHook = {
  loading: false,
  createDeployment: async () => ({ success: true }),
  listDeployments: async () => ({ success: true, deployments: [] }),
  updateDeployment: async () => ({ success: true }),
  pauseDeployment: async () => ({ success: true }),
  resumeDeployment: async () => ({ success: true }),
  deleteDeployment: async () => ({ success: true }),
  getDeploymentHistory: async () => ({ success: true, history: [] }),
  getRecentExecutions: async () => recentExecutions,
  runDeploymentNow: async () => ({ success: true }),
};
vi.mock('../../frontend/src/hooks/useDeployment', () => ({
  useDeployment: () => deploymentHook,
}));

const runExecutionsHook = {
  runningExecutions: [],
  queuedExecutions: [],
  completedExecutions: [],
  refresh: async () => {},
  subscribeSystemUpdate: () => () => {},
};
vi.mock('../../frontend/src/contexts/RunExecutionsContext', () => ({
  useRunExecutions: () => runExecutionsHook,
}));

const testCaseExecutionHook = {
  executeTestCase: async () => ({ success: true }),
  getTestCaseHistory: async () => ({ success: true, history: [] }),
};
vi.mock('../../frontend/src/hooks/testcase/useTestCaseExecution', () => ({
  useTestCaseExecution: () => testCaseExecutionHook,
}));

const testCaseSaveHook = {
  saveTestCase: async () => ({ success: true }),
  listTestCases: async () => ({ success: true, testcases: [] }),
  getTestCase: async () => ({ success: true, testcase: null }),
  deleteTestCase: async () => ({ success: true }),
};
vi.mock('../../frontend/src/hooks/testcase/useTestCaseSave', () => ({
  useTestCaseSave: () => testCaseSaveHook,
}));

const firstSelectedDevice = { hostName: '', deviceId: '', deviceModel: 'unknown' };
const targetSelectionHook = {
  selectedDevices: new Map(),
  toggleTarget: () => {},
  updateDeviceUserinterface: () => {},
  getTargetDisplayName: (key: string) => key,
  reconcileTargets: () => {},
  clearTargets: () => {},
  filterCompatible: () => {},
  filterTargetKeys: () => {},
  firstSelectedDevice,
  allHosts: [],
  getDevicesFromHost: () => [],
};
vi.mock('../../frontend/src/hooks/useTargetSelection', () => ({
  useTargetSelection: () => targetSelectionHook,
}));

vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({
  WorkspaceProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useWorkspaceContext: () => ({
    userWorkspaces: [],
    activeWorkspace: null,
    setActiveWorkspace: () => {},
    isLoadingWorkspaces: false,
    isDeviceAllowed: () => true,
    isScriptAllowed: () => true,
    isPathHidden: () => false,
  }),
}));

const runHook = {
  scriptAnalysis: null,
  parameterValues: {},
  analyzingScript: false,
  handleParameterChange: () => {},
  validateParameters: () => ({ valid: true, errors: [] }),
};
vi.mock('../../frontend/src/hooks/useRun', () => ({
  useRun: () => runHook,
}));

const toastHook = {
  showSuccess: () => {},
  showError: () => {},
  showWarning: () => {},
  showInfo: () => {},
};
vi.mock('../../frontend/src/hooks/useToast', () => ({
  useToast: () => toastHook,
  default: () => toastHook,
}));

import RunTests from '../../frontend/src/pages/RunTests';

describe('RunTests page', () => {
  it('renders the Run Tests heading', () => {
    render(
      <BrowserRouter>
        <RunTests />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Run Tests' })).toBeInTheDocument();
  });
});
