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

import TestReports from '../../frontend/src/pages/TestReports';

describe('TestReports page', () => {
  it('renders the Test Reports heading and Quick Stats section', () => {
    render(
      <BrowserRouter>
        <TestReports />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Test Reports' })).toBeInTheDocument();
    expect(screen.getByText('Quick Stats')).toBeInTheDocument();
  });
});
