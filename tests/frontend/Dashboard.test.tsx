import { render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

const { mockServerHostsData } = vi.hoisted(() => ({
  mockServerHostsData: [] as unknown[],
}));

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
    serverHostsData: mockServerHostsData,
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

// Dashboard renders `<WidgetArea area="dashboard" />` which throws without the
// full AuthProvider → ModsProvider → useWidgetArea stack. The test only
// checks for the page heading and "Servers" section — widget behaviour is
// covered by its own tests. Stub the widget area and the mod hook instead
// of standing up the full chain.
vi.mock('../../frontend/src/mods/core/components/widgets/WidgetArea', () => ({
  WidgetArea: () => null,
  WidgetAddButton: () => null,
}));
vi.mock('../../frontend/src/mods/core/components/ModsProvider', async () => {
  const React = await import('react');
  return {
    ModsProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    useMods: () => ({
      registry: { gate: () => Promise.resolve({ allow: true }), emit: () => undefined },
      api: {
        ui: { toast: () => undefined, openPane: () => undefined, closePane: () => undefined, confirm: () => Promise.resolve(true) },
        clock: { now: () => Date.now() },
      },
      openPaneId: null,
    }),
  };
});

import Dashboard from '../../frontend/src/pages/Dashboard';

describe('Dashboard page', () => {
  afterEach(() => {
    mockServerHostsData.length = 0;
  });

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

  it('does not crash when deployment telemetry is temporarily partial', () => {
    mockServerHostsData.push({
      server_info: {
        server_name: 'test-server',
        server_url: 'https://example.test',
        server_url_display: 'example.test',
        server_port: '443',
        service_health: { overall_status: 'online', services: [] },
        system_stats: { cpu_percent: 12, platform: 'Linux', architecture: 'x86_64' },
      },
      hosts: [{
        host_name: 'test-host',
        host_url: '/host/test-host',
        host_port: 6109,
        devices: [{ device_id: 'device-1', device_name: 'Device 1' }],
        device_count: 1,
        status: 'online',
        last_seen: Date.now(),
        registered_at: new Date().toISOString(),
        system_stats: { cpu_percent: 12, platform: 'Linux', architecture: 'x86_64' },
        isLocked: false,
      }],
    });

    expect(() => render(
      <BrowserRouter>
        <Dashboard />
      </BrowserRouter>,
    )).not.toThrow();

    expect(screen.getByText('test-host')).toBeInTheDocument();
  });
});
