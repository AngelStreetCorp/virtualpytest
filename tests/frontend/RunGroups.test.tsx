import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  workspace: { activeWorkspace: null },
  server: { selectedServer: 'server-a' },
  permissions: { hasPermission: () => true },
  toast: { showError: () => {}, showSuccess: () => {}, showInfo: () => {}, showWarning: () => {} },
}));

vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({
  useWorkspaceContext: () => mocks.workspace,
}));
vi.mock('../../frontend/src/hooks/useServerManager', () => ({ useServerManager: () => mocks.server }));
vi.mock('../../frontend/src/hooks/auth/usePermissions', () => ({ usePermissions: () => mocks.permissions }));
vi.mock('../../frontend/src/hooks/useToast', () => ({ useToast: () => mocks.toast, default: () => mocks.toast }));
vi.mock('../../frontend/src/components/reports/RunCharts', () => ({
  RunStatusDonut: () => <div data-testid="donut" />,
  RunTrendChart: () => <div data-testid="trend" />,
}));
vi.mock('../../frontend/src/hooks/reports/runManagementApi', async () => {
  const actual = await vi.importActual<typeof import('../../frontend/src/hooks/reports/runManagementApi')>(
    '../../frontend/src/hooks/reports/runManagementApi',
  );
  return {
    ...actual,
    fetchRunGroups: vi.fn(),
    archiveRunGroup: vi.fn(async () => ({})),
    restoreRunGroup: vi.fn(async () => ({})),
    updateRunGroup: vi.fn(async () => ({})),
    fetchGroupReport: vi.fn(),
    rerunGroup: vi.fn(),
  };
});

import * as rmApi from '../../frontend/src/hooks/reports/runManagementApi';
import RunGroupDetail from '../../frontend/src/pages/RunGroupDetail';
import RunGroups from '../../frontend/src/pages/RunGroups';
import { emptyCounts, type GroupReportResponse, type RunGroup } from '../../frontend/src/types/reports';

const group = (overrides: Partial<RunGroup> = {}): RunGroup => ({
  id: 'g-1',
  name: 'Release 12 smoke',
  description: null,
  color: null,
  pinned: false,
  archived: false,
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-02T00:00:00Z',
  ...overrides,
});

const wrap = (ui: React.ReactElement, path: string, routePath: string) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={routePath} element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe('RunGroups list', () => {
  beforeEach(() => {
    vi.mocked(rmApi.fetchRunGroups).mockReset();
    vi.mocked(rmApi.archiveRunGroup).mockClear();
    vi.mocked(rmApi.restoreRunGroup).mockClear();
  });

  it('archives (never deletes) an active group and explains that links are kept', async () => {
    vi.mocked(rmApi.fetchRunGroups).mockResolvedValue({ items: [group()] });
    const user = userEvent.setup();
    wrap(<RunGroups />, '/test-results/groups', '/test-results/groups');

    expect(await screen.findByText('Release 12 smoke')).toBeInTheDocument();
    expect(screen.getByText(/keep their results and links/)).toBeInTheDocument();
    expect(screen.queryByText(/delete/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Archive' }));
    expect(rmApi.archiveRunGroup).toHaveBeenCalledWith('g-1');
    expect(vi.mocked(rmApi.fetchRunGroups).mock.calls[0][0]).toBe(false);
  });

  it('lists archived groups when the URL asks for them and restores one', async () => {
    vi.mocked(rmApi.fetchRunGroups).mockResolvedValue({ items: [group({ archived: true })] });
    const user = userEvent.setup();
    wrap(<RunGroups />, '/test-results/groups?archived=1', '/test-results/groups');

    expect(await screen.findByText('Archived')).toBeInTheDocument();
    expect(vi.mocked(rmApi.fetchRunGroups).mock.calls[0][0]).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Restore' }));
    expect(rmApi.restoreRunGroup).toHaveBeenCalledWith('g-1');
  });
});

// Shape of POST /server/run-groups/:id/rerun (202): queued deployments, never a live task id.
const rerunOk = {
  request_id: 'req-1',
  run_group_id: 'g-1',
  mode: 'failures',
  status: 'dispatched',
  idempotent_replay: false,
  dispatched: [{ script_result_id: 'r-1', source_script_result_id: 'r-1', deployment_id: 'dep-1', task_id: null }],
  skipped_manual: [],
  skipped_not_in_mode: [],
  skipped: [],
  error: null,
};

describe('RunGroupDetail rerun', () => {
  const report: GroupReportResponse = {
    group: group({ member_count: 1, attempt_count: 5 }),
    counts: { ...emptyCounts(), total: 1, failed: 1 },
    attempts_total: 5,
    attempts: { ...emptyCounts(), total: 5, passed: 2, failed: 3 },
    rerun_preview: { all: { targets: 1, skipped: [] }, failures: { targets: 1, skipped: [] } },
    rows: [
      {
        script_result_id: 'r-1',
        name: 'zap_check',
        script_type: 'script',
        status: 'failed',
        userinterface_name: 'ui',
        environment: 'prod',
        host_name: 'h',
        device_name: 'd',
        started_at: '2026-10-02T00:00:00Z',
        completed_at: null,
        execution_time_ms: 1000,
        discard: false,
        attempts: 3,
      },
    ],
  };

  beforeEach(() => {
    vi.mocked(rmApi.fetchGroupReport).mockReset();
    vi.mocked(rmApi.rerunGroup).mockReset();
    vi.mocked(rmApi.fetchGroupReport).mockResolvedValue(report);
  });

  it('reuses the idempotency key on retry after a failure and uses a new key for the next click', async () => {
    const rerun = vi.mocked(rmApi.rerunGroup);
    rerun
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce(rerunOk)
      .mockResolvedValueOnce(rerunOk);
    const user = userEvent.setup();
    wrap(<RunGroupDetail />, '/test-results/groups/g-1', '/test-results/groups/:groupId');

    await user.click(await screen.findByRole('button', { name: 'Rerun failures' }));
    expect(screen.getByText(/Manual runs are never replayed/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Rerun' }));
    expect(await screen.findByText(/Rerun failed: network down/)).toBeInTheDocument();

    // The confirm dialog hides the page from the accessibility tree until it has closed.
    await user.click(await screen.findByRole('button', { name: 'Retry' }));
    expect(await screen.findByTestId('rerun-result')).toHaveTextContent('Dispatched 1 run');
    expect(screen.getByTestId('rerun-result')).toHaveTextContent(/queued on its original target/);
    expect(screen.queryByRole('link', { name: /live/i })).not.toBeInTheDocument();

    await user.click(await screen.findByRole('button', { name: 'Rerun failures' }));
    await user.click(screen.getByRole('button', { name: 'Rerun' }));
    await screen.findByTestId('rerun-result');

    expect(rerun).toHaveBeenCalledTimes(3);
    const [first, second, third] = rerun.mock.calls.map((call) => call[1]);
    expect(first.mode).toBe('failures');
    expect(first.idempotency_key).toBeTruthy();
    expect(second.idempotency_key).toBe(first.idempotency_key);
    expect(third.idempotency_key).not.toBe(first.idempotency_key);
  });

  it('shows the latest-attempt rollup and attempts separately', async () => {
    wrap(<RunGroupDetail />, '/test-results/groups/g-1', '/test-results/groups/:groupId');
    expect(await screen.findByTestId('count-total')).toHaveTextContent('1');
    expect(screen.getByTestId('count-failed')).toHaveTextContent('1');
    expect(screen.getByText('All attempts')).toBeInTheDocument();
    expect(screen.getByTestId('child-row')).toHaveTextContent('3');
  });
});
