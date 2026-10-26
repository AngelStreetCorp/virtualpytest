import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';
import { CustomThemeProvider } from '../../frontend/src/contexts/ThemeContext';

// Settings renders the signed-in user's chip via useAuth() -> useAuthContext(), which throws
// outside an AuthProvider. Every other dependency in this suite is mocked the same way; wrapping
// the render in a real provider would put a Supabase session behind a render test.
vi.mock('../../frontend/src/hooks/auth/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'test-user', email: 'tester@vpt.local' },
    signOut: vi.fn(),
  }),
}));

vi.mock('../../frontend/src/hooks/pages', () => ({
  useSettings: () => ({
    config: {
      server: {
        SERVER_NAME: '',
        SERVER_URL: '',
        SERVER_PORT: '5109',
        ENVIRONMENT: 'development',
        DEBUG: '1',
        PYTHONUNBUFFERED: '1',
      },
      frontend: {
        VITE_SERVER_URL: '',
        VITE_SLAVE_SERVER_URL: '',
        VITE_GRAFANA_URL: '',
        VITE_CLOUDFLARE_R2_PUBLIC_URL: '',
        VITE_DEV_MODE: 'true',
        VITE_FEATURE_DEPLOYMENTS: 'true',
        VITE_FEATURE_RUN_VERSION_SELECTOR: 'false',
        VITE_NAV_HIDDEN: '',
        VITE_NAV_DISABLED: '',
        VITE_NAV_COMING_SOON: '',
      },
      host: {
        HOST_NAME: '',
        HOST_PORT: '6109',
        HOST_URL: '',
        HOST_API_URL: '',
      },
      devices: {},
    },
    loading: false,
    saving: false,
    error: null,
    success: false,
    loadConfig: () => {},
    saveConfig: () => {},
    updateServerConfig: () => {},
    updateFrontendConfig: () => {},
    updateHostConfig: () => {},
    updateDeviceConfig: () => {},
    addDevice: () => {},
    deleteDevice: () => {},
    setError: () => {},
    setSuccess: () => {},
    loadHostConfig: () => {},
    saveHostConfig: () => {},
    grabbers: { grabbers: [], bluetooth: [], infrared: [] },
    grabbersLoading: false,
    grabbersError: null,
    loadGrabbers: () => {},
    usedGrabberVideoPaths: () => new Set<string>(),
    applyGrabberToDevice: () => {},
    getAudioSource: () => '',
  }),
}));

// This page gates UI on permissions via usePermissions() -> usePermissionContext(), which
// throws outside a PermissionProvider. Mocked at the module boundary, the same way every
// other provider in this suite is (see Dashboard.test.tsx), rather than wrapping the tree
// in real providers that would then want a real session.
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

import Settings from '../../frontend/src/pages/Settings';

// Settings also reads useProfile() (see hooks/auth/useProfile.ts:1-10), which
// calls useAuthContext() directly. The mocks at the top of this file only
// replace useAuth; useProfile is a separate module import and would still
// throw "useAuthContext must be used within AuthProvider" inside the
// Settings tree. Mock it here, at the module boundary, the same way
// useAuth is mocked above.
vi.mock('../../frontend/src/hooks/auth/useProfile', () => ({
  useProfile: () => ({
    profile: { id: 'test-user', email: 'tester@vpt.local', team_id: 'test-team' },
    loading: false,
    error: null,
    refreshProfile: async () => {},
    updateProfile: async () => {},
  }),
}));

// Settings.tsx calls useServerManager() for per-server branding / restart URLs (TASK-113);
// the hook throws "useServerManager must be used within a ServerManagerProvider" without a
// provider. Other suites mock the hook the same way instead of mounting the real provider.
vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({
    serverHostsData: [],
    selectedServer: 'test-server',
    selectServer: () => {},
    refreshServerData: async () => {},
  }),
}));

describe('Settings page', () => {
  it('renders the Settings heading', () => {
    // The Appearance tab calls the project's local useTheme() (contexts/ThemeContext),
    // which throws "useTheme must be used within a ThemeProvider" without its provider.
    // Wrap the page in CustomThemeProvider the same way the real App does; mocking the
    // hook would also be fine, but the provider keeps the theme-store side-effects
    // (localStorage, system-mode detection) in their normal lifecycle for this test.
    render(
      <CustomThemeProvider>
        <BrowserRouter>
          <Settings />
        </BrowserRouter>
      </CustomThemeProvider>,
    );

    expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
  });
});
