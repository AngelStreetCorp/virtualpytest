import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Stable references: a fresh literal per render would retrigger effects forever.
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
vi.mock('../../frontend/src/utils/infrastructure/cloudflareUtils', () => ({ openR2Url: vi.fn() }));
vi.mock('../../frontend/src/components/reports/RunCharts', () => ({
  RunStatusDonut: () => <div data-testid="donut" />,
  RunTrendChart: () => <div data-testid="trend" />,
}));
vi.mock('../../frontend/src/components/reports/AssignmentDialog', () => ({ default: () => null }));
vi.mock('../../frontend/src/components/reports/RunLivePanel', () => ({
  default: ({ taskId }: { taskId: string }) => <div data-testid="live-panel">{taskId}</div>,
}));
vi.mock('../../frontend/src/hooks/reports/runManagementApi', async () => {
  const actual = await vi.importActual<typeof import('../../frontend/src/hooks/reports/runManagementApi')>(
    '../../frontend/src/hooks/reports/runManagementApi',
  );
  return {
    ...actual,
    fetchRunSummary: vi.fn(),
    fetchDefects: vi.fn(async () => ({ items: [] })),
    fetchShareSnapshots: vi.fn(async () => ({ items: [] })),
  };
});

import * as rmApi from '../../frontend/src/hooks/reports/runManagementApi';
import RunSummary from '../../frontend/src/pages/RunSummary';
import {
  emptyCounts,
  toRunStatus,
  scriptResultStatus,
  type RunChild,
  type RunStatusCounts,
  type RunSummaryResponse,
} from '../../frontend/src/types/reports';

const LocationProbe: React.FC = () => {
  const location = useLocation();
  return <div data-testid="location">{location.search}</div>;
};

const renderAt = (path: string) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/test-results/runs/:kind/:id"
            element={
              <>
                <RunSummary />
                <LocationProbe />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

const child = (overrides: Partial<RunChild> = {}): RunChild => ({
  script_result_id: 'r-1',
  name: 'dns_lookuptime',
  script_type: 'script',
  status: 'passed',
  userinterface_name: null,
  environment: null,
  host_name: 'host-1',
  device_name: 'device-1',
  started_at: '2026-10-01T10:00:00Z',
  completed_at: '2026-10-01T10:01:00Z',
  execution_time_ms: 60000,
  discard: false,
  report_url: null,
  logs_url: null,
  ...overrides,
});

const summary = (overrides: Partial<RunSummaryResponse> = {}, counts?: Partial<RunStatusCounts>): RunSummaryResponse => ({
  identity: { kind: 'script', id: 'r-1' },
  title: 'dns_lookuptime',
  status: 'passed',
  started_at: '2026-10-01T10:00:00Z',
  completed_at: '2026-10-01T10:01:00Z',
  execution_time_ms: 60000,
  counts: { ...emptyCounts(), ...counts },
  children: { items: [], total: 0, limit: 25, offset: 0 },
  // Same envelope as GET /server/run-management/summary (zero-filled points in real data).
  trend: { window_days: 30, points: [], excluded: { discarded: 0, not_terminal: 0 } },
  metadata: { labels: [], milestone: null, run_group: null },
  evidence: { report_url: null, logs_url: null, steps: null },
  generated_at: '2026-10-03T00:00:00+00:00',
  ...overrides,
});

const fetchRunSummary = vi.mocked(rmApi.fetchRunSummary);

describe('RunSummary', () => {
  beforeEach(() => {
    fetchRunSummary.mockReset();
  });

  it('shows a loading state while the summary is in flight', () => {
    fetchRunSummary.mockReturnValue(new Promise(() => {}));
    renderAt('/test-results/runs/script/r-1');
    expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument();
  });

  it('rejects an unknown run kind without calling the server', () => {
    renderAt('/test-results/runs/bogus/r-1');
    expect(screen.getByTestId('state-invalid')).toBeInTheDocument();
    expect(fetchRunSummary).not.toHaveBeenCalled();
  });

  it('renders a forbidden state on 403', async () => {
    fetchRunSummary.mockRejectedValue(new rmApi.ApiError(403, 'forbidden', null));
    renderAt('/test-results/runs/script/r-1');
    expect(await screen.findByTestId('state-forbidden')).toBeInTheDocument();
  });

  it('renders an honest empty state when the run has no children', async () => {
    fetchRunSummary.mockResolvedValue(summary());
    renderAt('/test-results/runs/script/r-1');
    expect(await screen.findByText('This run has no recorded tests.')).toBeInTheDocument();
    expect(screen.getByTestId('step-evidence')).toHaveTextContent('Step evidence not recorded for this run');
  });

  it('shows a child without recorded evidence as Unknown, never Failed', async () => {
    fetchRunSummary.mockResolvedValue(
      summary(
        {
          identity: { kind: 'campaign', id: 'ce-1' },
          children: {
            items: [
              child({
                script_result_id: null,
                name: 'never_ran',
                status: 'unknown',
                position: 3,
                unknown_reason: 'no persisted outcome for this planned script',
              }),
            ],
            total: 1,
            limit: 25,
            offset: 0,
          },
        },
        { total: 1, unknown: 1 },
      ),
    );
    renderAt('/test-results/runs/campaign/ce-1');
    const row = await screen.findByTestId('child-row');
    expect(within(row).getByText('Unknown')).toBeInTheDocument();
    expect(within(row).queryByText('Failed')).not.toBeInTheDocument();
    expect(within(row).getByText(/No result recorded — no persisted outcome/)).toBeInTheDocument();
    expect(toRunStatus('not-a-status')).toBe('unknown');
    // Raw result rows: success=false without a duration is an unfinished run, not a failure.
    expect(scriptResultStatus({ success: false, execution_time_ms: null })).toBe('unknown');
    expect(scriptResultStatus({ success: false, execution_time_ms: 1200 })).toBe('failed');
    expect(scriptResultStatus({ success: true, execution_time_ms: null })).toBe('passed');
    expect(toRunStatus(undefined)).toBe('unknown');
  });

  it('renders campaign counts exactly as the server computed them (33 = 4 failed / 12 skipped / 17 passed)', async () => {
    fetchRunSummary.mockResolvedValue(
      summary(
        {
          identity: { kind: 'campaign', id: 'ce-33' },
          status: 'failed',
          children: {
            items: [
              child({ status: 'failed', position: 0 }),
              // A skipped campaign child has no script_results row.
              child({ script_result_id: null, name: 'skipped_child', status: 'skipped', position: 1, skip_reason: 'skipped' }),
            ],
            total: 33,
            limit: 25,
            offset: 0,
          },
        },
        { total: 33, failed: 4, skipped: 12, passed: 17 },
      ),
    );
    renderAt('/test-results/runs/campaign/ce-33');
    expect(await screen.findByTestId('count-total')).toHaveTextContent('33');
    expect(screen.getByTestId('count-failed')).toHaveTextContent('4');
    expect(screen.getByTestId('count-skipped')).toHaveTextContent('12');
    expect(screen.getByTestId('count-passed')).toHaveTextContent('17');
    expect(screen.getByTestId('count-unknown')).toHaveTextContent('0');
    // Counts are not derived from the visible page of children.
    expect(screen.getAllByTestId('child-row')).toHaveLength(2);
  });

  it('reads the tab from the URL and writes it back on change', async () => {
    fetchRunSummary.mockResolvedValue(summary({}, { total: 2, passed: 1, failed: 1 }));
    const user = userEvent.setup();
    renderAt('/test-results/runs/script/r-1?tab=statistics');
    expect(await screen.findByTestId('statistics-table')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Statistics' })).toHaveAttribute('aria-selected', 'true');

    await user.click(screen.getByRole('tab', { name: 'Defects' }));
    expect(screen.getByTestId('location')).toHaveTextContent('tab=defects');

    await user.click(screen.getByRole('tab', { name: 'Tests' }));
    expect(screen.getByTestId('location')).not.toHaveTextContent('tab=');
  });

  it('keeps the child status filter and page in the URL and sends them to the server', async () => {
    fetchRunSummary.mockResolvedValue(summary({}, { total: 3, failed: 3 }));
    renderAt('/test-results/runs/script/r-1?status=failed&page=2');
    await screen.findByTestId('count-total');
    expect(fetchRunSummary).toHaveBeenCalledWith(
      { kind: 'script', id: 'r-1' },
      expect.objectContaining({ status: 'failed', offset: 50, limit: 25 }),
      expect.objectContaining({ hostFilter: undefined }),
    );
  });

  it('embeds the live panel when a task id is in the URL', async () => {
    fetchRunSummary.mockResolvedValue(summary());
    renderAt('/test-results/runs/script/r-1?task=task-9');
    expect(screen.getByTestId('live-panel')).toHaveTextContent('task-9');
  });
});
