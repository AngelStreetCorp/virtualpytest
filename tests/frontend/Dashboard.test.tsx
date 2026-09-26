import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/hooks/useResponsiveMode', () => ({
  useResponsiveMode: () => ({
    mode: 'desktop',
    isMobile: false,
    isTablet: false,
    isDesktop: true,
    theme: {},
  }),
}));

vi.mock('../../frontend/src/hooks/useHostManager', () => ({
  useHostData: () => ({
    getAllHosts: () => [],
  }),
}));

vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({
    serverHostsData: [],
    isLoading: false,
    error: null,
    refreshServerData: () => {},
  }),
}));

vi.mock('../../frontend/src/hooks/pages/useRec', () => ({
  useRec: () => ({
    restartStreams: () => {},
    isRestarting: false,
  }),
}));

vi.mock('../../frontend/src/hooks/pages/useDashboard', () => ({
  useDashboard: () => ({
    stats: {
      testCases: 7,
      campaigns: 3,
      trees: 5,
      recentActivity: [],
    },
    loading: false,
    error: null,
  }),
}));

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

// Dashboard reads `hasPermission('device_control:execute')` to decide whether to
// render the per-host restart/stop/reboot/auto-fix row. Default the mock to
// `true` so existing assertions still pass; a separate case covers the viewer.
vi.mock('../../frontend/src/contexts/auth/PermissionContext', () => ({
  PermissionProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  usePermissionContext: () => ({
    role: 'admin',
    permissions: ['*'],
    hasRole: () => true,
    hasPermission: () => true,
    canAccess: () => true,
  }),
}));

import Dashboard from '../../frontend/src/pages/Dashboard';

describe('Dashboard page', () => {
  it('renders dashboard heading and registered servers section', () => {
    render(
      <BrowserRouter>
        <Dashboard />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    // Dashboard shows "Registered Servers" section
    expect(screen.getByText(/Servers/i)).toBeInTheDocument();
  });
});
