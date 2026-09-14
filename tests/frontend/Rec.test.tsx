import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/components/rec/RecHostPreview', () => ({
  RecHostPreview: () => <div data-testid="rec-host-preview" />,
}));

vi.mock('../../frontend/src/components/rec/RecHostStreamModal', () => ({
  RecHostStreamModal: () => null,
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

vi.mock('../../frontend/src/hooks/pages/useRec', () => ({
  useRec: () => ({
    avDevices: [],
    isLoading: false,
    error: null,
    restartStreams: () => {},
    isRestarting: false,
  }),
}));

vi.mock('../../frontend/src/hooks/useDeviceFlags', () => ({
  useDeviceFlags: () => ({
    deviceFlags: [],
    uniqueFlags: [],
    batchUpdateDeviceFlags: async () => true,
  }),
}));

vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({
    isServerChanging: false,
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

import Rec from '../../frontend/src/pages/Rec';

describe('Rec page', () => {
  it('renders device page heading', () => {
    render(
      <BrowserRouter>
        <Rec />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Device' })).toBeInTheDocument();
  });
});
