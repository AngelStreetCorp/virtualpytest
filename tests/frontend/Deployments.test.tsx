import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

// Deployments opens a real socket.io connection on mount — stub it out.
vi.mock('socket.io-client', () => ({
  io: () => ({
    on: () => {},
    disconnect: () => {},
  }),
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

vi.mock('../../frontend/src/hooks/useDeployment', () => ({
  useDeployment: () => ({
    loading: false,
    createDeployment: async () => ({ success: true }),
    listDeployments: async () => ({ success: true, deployments: [] }),
    updateDeployment: async () => ({ success: true }),
    pauseDeployment: async () => ({ success: true }),
    resumeDeployment: async () => ({ success: true }),
    deleteDeployment: async () => ({ success: true }),
    getDeploymentHistory: async () => ({ success: true, history: [] }),
    getRecentExecutions: async () => ({
      success: true,
      running_executions: [],
      queued_executions: [],
      completed_executions: [],
    }),
    runDeploymentNow: async () => ({ success: true }),
  }),
}));

vi.mock('../../frontend/src/hooks/useHostManager', () => ({
  useHostData: () => ({
    getAllHosts: () => [],
    getDevicesFromHost: () => [],
    getHostByName: () => null,
  }),
}));

vi.mock('../../frontend/src/hooks/useRun', () => ({
  useRun: () => ({
    scriptAnalysis: null,
    parameterValues: {},
    handleParameterChange: () => {},
  }),
}));

vi.mock('../../frontend/src/hooks/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    dialogState: {
      open: false,
      title: 'Confirm Action',
      message: '',
      confirmText: 'OK',
      cancelText: 'Cancel',
      confirmColor: 'primary',
      onConfirm: () => {},
    },
    confirm: () => {},
    handleConfirm: () => {},
    handleCancel: () => {},
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

vi.mock('../../frontend/src/components/common/UserinterfaceSelector', () => ({
  UserinterfaceSelector: () => null,
}));

vi.mock('../../frontend/src/components/common/ParameterInput/ScriptParameterRow', () => ({
  ScriptParameterRow: () => null,
}));

vi.mock('../../frontend/src/components/common/CronHelper', () => ({
  CronHelper: () => null,
}));

vi.mock('../../frontend/src/components/rec/RecHostStreamModal', () => ({
  RecHostStreamModal: () => null,
}));

vi.mock('../../frontend/src/components/common/ConfirmDialog', () => ({
  ConfirmDialog: () => null,
}));

import Deployments from '../../frontend/src/pages/Deployments';

describe('Deployments page', () => {
  it('renders without crashing and shows the Deployments heading', () => {
    render(
      <BrowserRouter>
        <Deployments />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Deployments' })).toBeInTheDocument();
  });
});
