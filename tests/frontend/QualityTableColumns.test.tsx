// @vitest-environment jsdom
/**
 * The Quality tables keep their Test column on a phone (BUG-0794).
 *
 * The first `<col>` of the flaky / slow / never-executed tables had no width, so the Test
 * column collapsed and the test names broke to one letter per line in a 358 px box. Each table
 * now gives that column an explicit width and a minimum width for the whole table, so the
 * container scrolls sideways instead of squeezing the names.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
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

import FlakyTests from '../../frontend/src/pages/FlakyTests';
import NeverExecuted from '../../frontend/src/pages/NeverExecuted';
import SlowTests from '../../frontend/src/pages/SlowTests';

const windowMeta = (days: number) => ({
  window_days: days,
  window_start: '2026-09-19T00:00:00Z',
  window_end: '2026-10-03T00:00:00Z',
  sample_size: 57,
  min_attempts: 5,
  row_total: 1,
  scope: { host_count: 2, device_filter_applied: false },
});

const identity = {
  script_name: 'zap_channel',
  script_type: 'zap_channel',
  userinterface_name: 'lobby_tv',
  environment: 'prod',
  host_name: 'host-1',
  device_name: 'stb-1',
};

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
    identities_evaluated: 1,
    metric: 'adjacent pass/fail transitions / (attempts - 1)',
    rows: [
      {
        identity,
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
    ],
  }));
  api.fetchSlow.mockImplementation(async (params: { windowDays: number }) => ({
    ...windowMeta(params.windowDays),
    percentile_method: 'nearest-rank',
    rows: [
      {
        identity,
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

/** The width the first column asks for, in px, and the minimum width of the whole table. */
const columnGeometry = (table: HTMLTableElement) => {
  const cols = Array.from(table.querySelectorAll('col'));
  const first = cols[0] as HTMLTableColElement | undefined;
  return {
    firstWidth: first ? first.style.width : '',
    minWidth: window.getComputedStyle(table).minWidth,
  };
};

describe('the Quality tables on a phone (BUG-0794)', () => {
  it('gives the flaky table a width for the Test column and a minimum width for the table', async () => {
    renderPage(<FlakyTests />, '/test-results/quality/flaky');
    const table = (await screen.findByRole('table')) as HTMLTableElement;
    const geometry = columnGeometry(table);
    expect(geometry.firstWidth).not.toBe('');
    expect(parseInt(geometry.firstWidth, 10)).toBeGreaterThanOrEqual(200);
    expect(parseInt(geometry.minWidth, 10)).toBeGreaterThanOrEqual(600);
  });

  it('gives the slow table a width for the Test column', async () => {
    renderPage(<SlowTests />, '/test-results/quality/slow');
    const table = (await screen.findByRole('table')) as HTMLTableElement;
    await waitFor(() => expect(table.querySelectorAll('col').length).toBeGreaterThan(0));
    const geometry = columnGeometry(table);
    expect(geometry.firstWidth).not.toBe('');
    expect(parseInt(geometry.minWidth, 10)).toBeGreaterThanOrEqual(600);
  });

  it('gives the never-executed table a width for the Test column', async () => {
    renderPage(<NeverExecuted />, '/test-results/quality/not-executed');
    const table = (await screen.findByRole('table')) as HTMLTableElement;
    await waitFor(() => expect(table.querySelectorAll('col').length).toBeGreaterThan(0));
    const geometry = columnGeometry(table);
    expect(geometry.firstWidth).not.toBe('');
    expect(parseInt(geometry.minWidth, 10)).toBeGreaterThanOrEqual(600);
  });
});
