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

vi.mock('../../frontend/src/hooks/useToast', () => ({
  useToast: () => ({
    showSuccess: vi.fn(),
    showError: vi.fn(),
    showWarning: vi.fn(),
    showInfo: vi.fn(),
  }),
}));

vi.mock('../../frontend/src/hooks/useHostManager', () => ({
  useHostData: () => ({
    getDevicesFromHost: () => [],
  }),
}));

// Functions must be stable across renders (created once in the mock factory,
// not per-hook-call) so the page's useCallback([listDeployments, showError])
// load-on-mount effect does not re-fire every render.
vi.mock('../../frontend/src/hooks/useDeployment', () => {
  const listDeployments = vi.fn(async () => ({ success: true, deployments: [] }));
  const updateDeployment = vi.fn(async () => ({ success: true }));
  const pauseDeployment = vi.fn(async () => ({ success: true }));
  const resumeDeployment = vi.fn(async () => ({ success: true }));
  const deleteDeployment = vi.fn(async () => ({ success: true }));
  return {
    useDeployment: () => ({
      listDeployments,
      updateDeployment,
      pauseDeployment,
      resumeDeployment,
      deleteDeployment,
    }),
  };
});

vi.mock('../../frontend/src/contexts/RunExecutionsContext', () => ({
  useRunExecutions: () => ({
    runningExecutions: [],
    queuedExecutions: [],
    completedExecutions: [],
    refresh: vi.fn(),
    subscribeSystemUpdate: () => () => {},
  }),
}));

// Avoid a real network fetch for the script identity map (ensureScriptIdentityMap
// hits the backend) — none of these are exercised with real data in this smoke test.
vi.mock('../../frontend/src/utils/executionUtils', () => ({
  getLogsUrl: (url: string) => url,
  getStatusChip: (status: string) => <span>{status}</span>,
  getScriptDisplayName: (name: string) => name,
  ensureScriptIdentityMap: async () => {},
}));

import MonitorTests from '../../frontend/src/pages/MonitorTests';

describe('MonitorTests page', () => {
  it('renders monitor tests heading and empty execution sections', async () => {
    render(
      <BrowserRouter>
        <MonitorTests />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Monitor Tests' })).toBeInTheDocument();
    expect(screen.getByText('No running executions')).toBeInTheDocument();
    expect(screen.getByText('No queued executions')).toBeInTheDocument();

    // Let the async listDeployments() mock resolve and its setState flush
    // before the test ends, so React doesn't warn about an update outside act().
    expect(await screen.findByText('No scheduled executions')).toBeInTheDocument();
  });
});
