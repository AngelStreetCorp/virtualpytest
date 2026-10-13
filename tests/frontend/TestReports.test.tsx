import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/hooks/pages/useScriptResults', () => ({
  useScriptResults: () => ({
    getAllScriptResults: async () => [],
    updateCheckedStatus: async () => {},
    updateDiscardStatus: async () => {},
  }),
}));

vi.mock('../../frontend/src/hooks/pages/useCampaignResults', () => ({
  useCampaignResults: () => ({
    getAllCampaignResults: async () => [],
  }),
}));

vi.mock('../../frontend/src/hooks/useHostManager', () => ({
  useHostData: () => ({
    getAllHosts: () => [],
  }),
}));

vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({
    selectedServer: 'server-1',
    availableServers: ['server-1'],
    setSelectedServer: () => {},
    serverHostsData: [],
    isLoading: false,
    error: null,
    pendingServers: new Set(),
    failedServers: new Set(),
    isServerChanging: false,
    refreshServerData: async () => {},
  }),
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

// Something in this tree renders the signed-in user, and useAuthContext() throws outside an
// AuthProvider. Mocked as signed-out-but-resolved: isLoading false so no spinner branch,
// isAuthenticated true so the page renders its content rather than a redirect.
vi.mock('../../frontend/src/contexts/auth/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuthContext: () => ({
    user: null,
    profile: null,
    session: null,
    isLoading: false,
    isAuthenticated: true,
    signInWithGoogle: async () => {},
    signInWithGithub: async () => {},
    signInWithEmail: async () => {},
    signUpWithEmail: async () => {},
    resetPassword: async () => {},
    signOut: async () => {},
    refreshProfile: async () => {},
  }),
}));

// Toasts are fire-and-forget here; useToastContext() throws outside a ToastProvider.
vi.mock('../../frontend/src/contexts/ToastContext', () => ({
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useToastContext: () => ({
    showSuccess: () => {},
    showError: () => {},
    showWarning: () => {},
    showInfo: () => {},
  }),
  __esModule: true,
}));

// Run-management additions (governance filters, flaky badges, bulk assignment) read React
// Query hooks; stubbed with stable empty results so this smoke test needs no QueryClient.
const { emptyQuery, idleMutation } = vi.hoisted(() => ({
  emptyQuery: { data: { items: [], rows: [] }, isLoading: false, error: null },
  idleMutation: { mutateAsync: async () => ({}), isPending: false },
}));
vi.mock('../../frontend/src/hooks/reports/useRunManagement', () => ({
  useMilestones: () => emptyQuery,
  useRunGroups: () => emptyQuery,
  useLabels: () => emptyQuery,
  useQualityQuery: () => emptyQuery,
  useReportPermissions: () => ({ canEdit: false }),
  useGovernanceMutations: () => ({
    setResultMilestone: idleMutation,
    setResultRunGroup: idleMutation,
    setResultLabels: idleMutation,
    batchAssign: idleMutation,
  }),
}));

import TestReports from '../../frontend/src/pages/TestReports';

describe('TestReports page', () => {
  it('renders the Test Reports heading and the success-rate tile', () => {
    render(
      <BrowserRouter>
        <TestReports />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Test Reports' })).toBeInTheDocument();
    expect(screen.getByText('Success rate')).toBeInTheDocument();
  });
});
