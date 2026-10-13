import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

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

describe('Settings page', () => {
  it('renders the Settings heading', () => {
    render(
      <BrowserRouter>
        <Settings />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
  });
});
