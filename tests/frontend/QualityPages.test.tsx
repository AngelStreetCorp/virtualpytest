import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import React from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  fetchFlaky: vi.fn(),
  fetchSlow: vi.fn(),
  fetchNotExecuted: vi.fn(),
}));

vi.mock('../../frontend/src/hooks/reports/runManagementApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../frontend/src/hooks/reports/runManagementApi')>();
  return { ...actual, ...api };
});

const workspace = vi.hoisted(() => ({ activeWorkspace: null as null | { id: string; device_filter: string[] } }));
vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({
  useWorkspaceContext: () => workspace,
}));
vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({ selectedServer: 'server-a' }),
}));
vi.mock('../../frontend/src/hooks/useToast', () => ({
  useToast: () => ({ showError: vi.fn(), showWarning: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn() }),
}));

import { QualityTabRedirect } from '../../frontend/src/components/reports/TabRedirects';
import FlakyTests from '../../frontend/src/pages/FlakyTests';
import NeverExecuted from '../../frontend/src/pages/NeverExecuted';
import Quality from '../../frontend/src/pages/Quality';
import SlowTests from '../../frontend/src/pages/SlowTests';

const windowMeta = (days: number) => ({
  window_days: days,
  window_start: '2026-09-19T00:00:00Z',
  window_end: '2026-10-03T00:00:00Z',
  sample_size: 57,
  min_attempts: 5,
  row_total: 2,
  scope: { host_count: 2, device_filter_applied: false },
});

const identity = (device: string) => ({
  script_name: 'zap_channel',
  script_type: 'zap_channel',
  userinterface_name: 'lobby_tv',
  environment: 'prod',
  host_name: 'host-1',
  device_name: device,
});

const renderPage = (ui: React.ReactElement, path: string) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );

beforeEach(() => {
  workspace.activeWorkspace = null;
  api.fetchFlaky.mockImplementation(async (params: { windowDays: number }) => ({
    ...windowMeta(params.windowDays),
    identities_evaluated: 3,
    metric: 'adjacent pass/fail transitions / (attempts - 1)',
    rows: [
      {
        identity: identity('stb-1'),
        attempts: 5,
        passes: 3,
        failures: 2,
        transitions: 4,
        flaky_score: 1,
        last_status: 'passed',
        first_started_at: '2026-09-28T10:00:00Z',
        last_started_at: '2026-10-02T10:00:00Z',
        latest_script_result_id: 'sr-1',
      },
      {
        identity: identity('stb-2'),
        attempts: 5,
        passes: 4,
        failures: 1,
        transitions: 1,
        flaky_score: 0.25,
        last_status: 'failed',
        first_started_at: '2026-09-28T11:00:00Z',
        last_started_at: '2026-10-02T11:00:00Z',
        latest_script_result_id: null,
      },
    ],
  }));
  api.fetchSlow.mockImplementation(async (params: { windowDays: number }) => ({
    ...windowMeta(params.windowDays),
    percentile_method: 'nearest-rank',
    rows: [
      {
        identity: identity('stb-1'),
        sample_count: 9,
        p50_ms: 61000,
        p95_ms: 125000,
        max_ms: 130000,
        last_started_at: '2026-10-02T10:00:00Z',
        latest_script_result_id: 'sr-9',
      },
    ],
  }));
  api.fetchNotExecuted.mockImplementation(async (params: { windowDays: number }) => ({
    ...windowMeta(params.windowDays),
    row_total: 1,
    label: 'not executed in window',
    runnable_total: 12,
    rows: [
      {
        script_name: 'boot_check',
        script_type: 'script',
        testcase_id: null,
        userinterface_name: null,
        environment: null,
        last_executed_at: null,
      },
    ],
  }));
});

describe('FlakyTests', () => {
  it('uses the 14 day default window and states the sample and window', async () => {
    renderPage(<FlakyTests />, '/test-results/quality/flaky');
    const indicator = await screen.findByTestId('quality-window-indicator');
    expect(indicator).toHaveTextContent('(14 days)');
    expect(indicator).toHaveTextContent('Sample: 57 eligible attempts');
    expect(indicator).toHaveTextContent('Minimum 5 attempts per test');
    expect(indicator).toHaveTextContent('Discarded and unfinished attempts excluded');
    expect(api.fetchFlaky).toHaveBeenCalledWith(
      expect.objectContaining({ windowDays: 14 }),
      expect.objectContaining({ hostFilter: undefined, deviceFilter: undefined }),
    );
  });

  it('reads the window from the URL', async () => {
    renderPage(<FlakyTests />, '/test-results/quality/flaky?window=30');
    expect(await screen.findByTestId('quality-window-indicator')).toHaveTextContent('(30 days)');
    expect(api.fetchFlaky).toHaveBeenCalledWith(
      expect.objectContaining({ windowDays: 30 }),
      expect.objectContaining({ hostFilter: undefined }),
    );
  });

  it('keeps one row per device identity with its score and evidence link', async () => {
    renderPage(<FlakyTests />, '/test-results/quality/flaky');
    const rows = await screen.findAllByTestId('flaky-row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('host-1 / stb-1')).toBeInTheDocument();
    expect(within(rows[0]).getByText('100%')).toBeInTheDocument();
    expect(within(rows[0]).getByText('4 / 4')).toBeInTheDocument();
    expect(within(rows[0]).getByRole('link', { name: 'Latest run' })).toHaveAttribute(
      'href',
      '/test-results/runs/script/sr-1',
    );
    expect(within(rows[1]).getByText('host-1 / stb-2')).toBeInTheDocument();
    expect(within(rows[1]).getByText('25%')).toBeInTheDocument();
  });

  it('sends the workspace host scope and says so', async () => {
    workspace.activeWorkspace = { id: 'ws', device_filter: ['host-2:dev-a', 'host-1:dev-b', 'host-2:dev-c'] };
    renderPage(<FlakyTests />, '/test-results/quality/flaky');
    expect(await screen.findByTestId('quality-scope-note')).toHaveTextContent('host-1, host-2');
    expect(api.fetchFlaky).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        hostFilter: ['host-1', 'host-2'],
        // Device keys go to the server too; it maps them to device names.
        deviceFilter: ['host-1:dev-b', 'host-2:dev-a', 'host-2:dev-c'],
      }),
    );
  });
});

describe('SlowTests', () => {
  it('defaults to 30 days and shows p50/p95 with the sample count', async () => {
    renderPage(<SlowTests />, '/test-results/quality/slow');
    expect(await screen.findByTestId('quality-window-indicator')).toHaveTextContent('(30 days)');
    expect(screen.getByText('1m 1s')).toBeInTheDocument();
    expect(screen.getByText('2m 5s')).toBeInTheDocument();
    expect(screen.getByText('9')).toBeInTheDocument();
  });
});

describe('NeverExecuted', () => {
  it('says "not executed in window", never "never executed"', async () => {
    renderPage(<NeverExecuted />, '/test-results/quality/not-executed');
    expect(await screen.findByRole('heading', { name: 'Not executed in window' })).toBeInTheDocument();
    expect(screen.getByText('boot_check')).toBeInTheDocument();
    // The server only knows "not in the window": no last-execution date is invented.
    expect(screen.queryByText(/No execution on record/)).not.toBeInTheDocument();
    expect(screen.getByText(/1 of 12 runnable tests had no execution in the last 30 days/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/never executed/i);
  });
});

const LocationProbe: React.FC = () => {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
};

const renderQuality = (path: string) =>
  renderPage(
    <>
      <Routes>
        <Route path="/test-results/quality" element={<Quality />} />
        <Route path="/test-results/quality/:tab" element={<QualityTabRedirect />} />
      </Routes>
      <LocationProbe />
    </>,
    path,
  );

describe('Quality page', () => {
  it('opens on the Flaky tab and switches tabs through the URL', async () => {
    renderQuality('/test-results/quality');
    expect(screen.getByRole('heading', { name: 'Quality' })).toBeInTheDocument();
    expect(await screen.findAllByTestId('flaky-row')).toHaveLength(2);
    fireEvent.click(screen.getByTestId('quality-tab-slow'));
    expect(await screen.findByTestId('quality-window-indicator')).toHaveTextContent('(30 days)');
    expect(screen.getByTestId('location')).toHaveTextContent('/test-results/quality?tab=slow');
  });

  it('redirects the old per-insight URLs to their tab, keeping the window', async () => {
    renderQuality('/test-results/quality/not-executed?window=7');
    expect(await screen.findByRole('heading', { name: 'Not executed in window' })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/test-results/quality?window=7&tab=not-executed');
    expect(api.fetchNotExecuted).toHaveBeenCalledWith(expect.objectContaining({ windowDays: 7 }), expect.anything());
  });
});
