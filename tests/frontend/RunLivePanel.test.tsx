import { act, fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { LiveRunStatus } from '../../frontend/src/types/reports';

const api = vi.hoisted(() => ({
  fetchLiveStatus: vi.fn(),
  stopLiveRun: vi.fn(),
}));

vi.mock('../../frontend/src/hooks/reports/runManagementApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../frontend/src/hooks/reports/runManagementApi')>();
  return { ...actual, fetchLiveStatus: api.fetchLiveStatus, stopLiveRun: api.stopLiveRun };
});

const permissions = vi.hoisted(() => ({ value: { canStop: true } as Record<string, boolean> }));
const scope = vi.hoisted(() => ({ serverKey: 'server-a', hostFilter: undefined, deviceFilter: undefined }));
vi.mock('../../frontend/src/hooks/reports/useRunManagement', () => ({
  useReportPermissions: () => permissions.value,
  useReportScope: () => scope,
}));

// RunLivePanel reads the selected host's metadata via useHostData() (the HostManager hook).
// The hook throws outside <HostManagerProvider>, and standing up the real provider would
// also want a real host list. Mock at the module boundary — the host metadata isn't part of
// what the panel asserts, only stop-permission / task-status handling is.
vi.mock('../../frontend/src/hooks/useHostManager', () => ({
  useHostData: () => ({
    getAllHosts: () => [],
    getHostByName: () => null,
    getDevicesFromHost: () => [],
  }),
}));

// useTargetSelection (called by the panel) reads `isDeviceAllowed` from the workspace
// context, which throws outside <WorkspaceProvider>. Mock the hook with the same defaults
// every other provider-mock in this file uses, so the panel renders without a real workspace
// hook doing real Supabase fetches under the test.
vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({
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

import { ApiError } from '../../frontend/src/hooks/reports/runManagementApi';
import { RunLivePanel } from '../../frontend/src/components/reports/RunLivePanel';

const running = (overrides: Partial<LiveRunStatus> = {}): LiveRunStatus => ({
  task_id: 'task-1',
  status: 'running',
  stale: false,
  script_name: 'goto_live.py',
  host_name: 'host-a',
  device_name: 'device1',
  started_at: '2026-10-03T10:00:00Z',
  elapsed_ms: 5000,
  progress: null,
  eta_ms: null,
  updated_at: '2026-10-03T10:00:05Z',
  script_result_id: null,
  stop_requested: false,
  can_stop: true,
  ...overrides,
});

let visibility: DocumentVisibilityState = 'visible';

const setVisibility = (value: DocumentVisibilityState) => {
  visibility = value;
  document.dispatchEvent(new Event('visibilitychange'));
};

const flush = async (ms = 0) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

const renderPanel = (props: Partial<React.ComponentProps<typeof RunLivePanel>> = {}) =>
  render(
    <MemoryRouter>
      <RunLivePanel taskId="task-1" {...props} />
    </MemoryRouter>,
  );

describe('RunLivePanel', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    visibility = 'visible';
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility });
    permissions.value = { canStop: true };
    api.fetchLiveStatus.mockReset();
    api.stopLiveRun.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('polls every 2 seconds while visible and active', async () => {
    api.fetchLiveStatus.mockResolvedValue(running());
    renderPanel();
    await flush();
    expect(api.fetchLiveStatus).toHaveBeenCalledTimes(1);
    await flush(2000);
    expect(api.fetchLiveStatus).toHaveBeenCalledTimes(2);
    await flush(2000);
    expect(api.fetchLiveStatus).toHaveBeenCalledTimes(3);
  });

  it('pauses while the page is hidden and refetches when visible again', async () => {
    api.fetchLiveStatus.mockResolvedValue(running());
    renderPanel();
    await flush();
    expect(api.fetchLiveStatus).toHaveBeenCalledTimes(1);

    act(() => setVisibility('hidden'));
    await flush(10_000);
    expect(api.fetchLiveStatus).toHaveBeenCalledTimes(1);

    act(() => setVisibility('visible'));
    await flush();
    expect(api.fetchLiveStatus).toHaveBeenCalledTimes(2);
  });

  it('stops polling at a terminal status and hands off to the summary', async () => {
    const onCompleted = vi.fn();
    api.fetchLiveStatus.mockResolvedValue(running({ status: 'passed', script_result_id: 'sr-9' }));
    renderPanel({ onCompleted });
    await flush();
    await flush(10_000);
    expect(api.fetchLiveStatus).toHaveBeenCalledTimes(1);
    expect(onCompleted).toHaveBeenCalledTimes(1);
    expect(onCompleted).toHaveBeenCalledWith('sr-9');
    expect(screen.getByRole('link', { name: /open run summary/i })).toHaveAttribute(
      'href',
      '/test-results/runs/script/sr-9',
    );
  });

  it('says the durable result is pending when a finished task has none yet', async () => {
    api.fetchLiveStatus.mockResolvedValue(running({ status: 'failed', script_result_id: null }));
    renderPanel();
    await flush();
    expect(screen.getByText(/waiting for the durable result/i)).toBeInTheDocument();
  });

  it('shows the stale banner when the server reports stale status', async () => {
    api.fetchLiveStatus.mockResolvedValue(running({ stale: true }));
    renderPanel();
    await flush();
    expect(screen.getByTestId('live-stale')).toBeInTheDocument();
  });

  it('renders unknown status honestly and no progress it was not given', async () => {
    api.fetchLiveStatus.mockResolvedValue(running({ status: 'unknown', elapsed_ms: null }));
    renderPanel();
    await flush();
    // Status chip says "Unknown", the meta line says "not reported" for the elapsed field
    // (the panel never infers a value it was not given), and RunNowPanel now only renders
    // an indeterminate LinearProgress. The previous "progress not reported" sentence lived
    // in an earlier version of the panel (commit 446b0de89 dropped it when the
    // run-management UI was rebuilt); update the assertions to what the panel says today.
    expect(screen.getByText('Unknown')).toBeInTheDocument();
    expect(screen.getByText('not reported')).toBeInTheDocument();
    expect(screen.getByText('elapsed')).toBeInTheDocument();
  });

  it('hides Stop when the server says the caller cannot stop the task', async () => {
    api.fetchLiveStatus.mockResolvedValue(running({ can_stop: false }));
    renderPanel();
    await flush();
    expect(screen.queryByRole('button', { name: /stop run/i })).not.toBeInTheDocument();
  });

  it('hides Stop without the stop permission', async () => {
    permissions.value = { canStop: false };
    api.fetchLiveStatus.mockResolvedValue(running());
    renderPanel();
    await flush();
    expect(screen.queryByRole('button', { name: /stop run/i })).not.toBeInTheDocument();
  });

  it('asks for confirmation before stopping', async () => {
    api.fetchLiveStatus.mockResolvedValue(running());
    // POST .../stop answers 202 while the host stops the process.
    api.stopLiveRun.mockResolvedValue({ success: true, status: 'running', stop_requested: true });
    renderPanel();
    await flush();

    fireEvent.click(screen.getByRole('button', { name: /stop run/i }));
    expect(api.stopLiveRun).not.toHaveBeenCalled();
    expect(screen.getByText(/releasing the device is not the same as stopping/i)).toBeInTheDocument();

    const buttons = screen.getAllByRole('button', { name: /stop run/i });
    fireEvent.click(buttons[buttons.length - 1]);
    await flush();
    expect(api.stopLiveRun).toHaveBeenCalledWith('task-1', scope);
    expect(screen.getByText(/stop requested/i)).toBeInTheDocument();
  });

  it('shows a task the server does not know as unknown, not as an error or completed', async () => {
    api.fetchLiveStatus.mockRejectedValue(
      new ApiError(404, 'task not found', { ...running({ status: 'unknown', stale: true, can_stop: false }), error: 'task not found' }),
    );
    renderPanel();
    await flush();
    expect(screen.getByText('Unknown')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /stop run/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/run finished/i)).not.toBeInTheDocument();
    expect(api.fetchLiveStatus).toHaveBeenCalledWith('task-1', expect.anything(), scope);
  });
});
