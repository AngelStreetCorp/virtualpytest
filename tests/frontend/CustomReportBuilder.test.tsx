import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  validateTql: vi.fn(),
  runReportQuery: vi.fn(),
  fetchCustomReports: vi.fn(),
  createCustomReport: vi.fn(),
  updateCustomReport: vi.fn(),
  deleteCustomReport: vi.fn(),
}));

vi.mock('../../frontend/src/hooks/reports/runManagementApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../frontend/src/hooks/reports/runManagementApi')>();
  return { ...actual, ...api };
});
vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({
  useWorkspaceContext: () => ({ activeWorkspace: null }),
}));
vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({ selectedServer: 'server-a' }),
}));
vi.mock('../../frontend/src/hooks/useToast', () => ({
  useToast: () => ({ showError: vi.fn(), showWarning: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn() }),
}));

import CustomReportBuilder from '../../frontend/src/pages/CustomReportBuilder';

const renderPage = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/test-results/custom-reports']}>
        <CustomReportBuilder />
      </MemoryRouter>
    </QueryClientProvider>,
  );

// POST /server/run-management/query response as the server builds it.
const queryResponse = {
  definition: {
    filter: { schema_version: 1, tql: 'status:failed since:7d' },
    columns: ['script_name', 'status'],
    chart: { type: 'status_by_day' },
    sort: 'started_at',
    order: 'desc',
    include_discarded: false,
  },
  window: { since: '2026-09-26T00:00:00+00:00', until: '2026-10-03T00:00:00+00:00' },
  scope: { host_count: 2, device_filter_applied: false },
  columns: ['script_name', 'status'],
  rows: [
    { script_name: 'zap_channel', status: 'failed', script_result_id: 'sr-1' },
    { script_name: 'boot_check', status: 'passed', script_result_id: 'sr-2' },
  ],
  total: 2,
  counts: { total: 2, passed: 1, failed: 1, running: 0, pending: 0, skipped: 0, cancelled: 0, unknown: 0 },
  chart: { type: 'status_by_day', points: [{ x: '2026-10-02', passed: 1, failed: 1, other: 0 }] },
  limit: 100,
  offset: 0,
};

const stored = {
  created_by: 'user-1',
  sort: 'started_at',
  order: 'desc',
  include_discarded: false,
};

beforeEach(() => {
  api.fetchCustomReports.mockResolvedValue({
    items: [
      {
        id: 'r1',
        name: 'Failures this week',
        filter: { schema_version: 1, tql: 'status:failed since:7d' },
        columns: ['script_name', 'status'],
        chart: { type: 'status_by_day' },
        created_at: '2026-10-01T00:00:00Z',
        updated_at: '2026-10-01T00:00:00Z',
        ...stored,
        valid: true,
      },
      {
        id: 'r0',
        name: 'Old schema',
        filter: { schema_version: 0, tql: 'status:failed' },
        columns: ['script_name'],
        chart: { type: 'status_share' },
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        ...stored,
        // The server revalidates on read and reports the failure instead of hiding it.
        valid: false,
        validation_error: { error: 'unsupported filter schema_version 0; expected 1', field: 'filter.schema_version' },
      },
    ],
  });
  api.validateTql.mockImplementation(async (q: string) =>
    q.includes('bogus')
      ? { ok: false, error: "unknown status 'bogus'", position: 7 }
      : { ok: true, clauses: [], filter: {} },
  );
  api.runReportQuery.mockResolvedValue(queryResponse);
});

describe('CustomReportBuilder', () => {
  it('lists saved reports as private, with no sharing control', async () => {
    renderPage();
    expect(await screen.findByText('Failures this week')).toBeInTheDocument();
    expect(screen.getByTestId('reports-private-note')).toHaveTextContent('Visible only to you');
    expect(screen.queryByText(/share/i)).not.toBeInTheDocument();
  });

  it('shows the server TQL error with its position and blocks Run', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText('TQL filter'), 'status:bogus');
    const error = await screen.findByTestId('tql-error');
    expect(error).toHaveTextContent("unknown status 'bogus'");
    expect(error).toHaveTextContent('(at character 8)');
    expect(screen.getByTestId('tql-caret').textContent).toBe('status:bogus\n       ^');
    expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled();
    expect(api.runReportQuery).not.toHaveBeenCalled();
  });

  it('renders counts, chart and table from ONE query response', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText('Failures this week'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Run' }));

    expect(await screen.findAllByTestId('report-row')).toHaveLength(2);
    expect(api.runReportQuery).toHaveBeenCalledTimes(1);
    expect(api.runReportQuery).toHaveBeenCalledWith(
      expect.objectContaining({
        filter: { schema_version: 1, tql: 'status:failed since:7d' },
        columns: ['script_name', 'status'],
        chart: { type: 'status_by_day' },
        limit: 100,
        offset: 0,
      }),
      expect.objectContaining({ serverKey: expect.any(String) }),
    );
    expect(screen.getAllByRole('link', { name: 'Summary' })[0]).toHaveAttribute('href', '/test-results/runs/script/sr-1');
    expect(screen.getByTestId('report-count-total')).toHaveTextContent('2');
    expect(screen.getByTestId('report-count-failed')).toHaveTextContent('1');
    expect(screen.getByTestId('report-count-passed')).toHaveTextContent('1');
    expect(screen.getByText('zap_channel')).toBeInTheDocument();
    expect(screen.getByText('Rows 1–2 of 2')).toBeInTheDocument();
  });

  it('requires a re-save before running a report saved with another schema version', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText('Old schema'));
    expect(screen.getByTestId('schema-mismatch')).toHaveTextContent('schema version 0');
    expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled();
  });

  it('hides the chart when the report asks for none', async () => {
    api.runReportQuery.mockResolvedValueOnce({ ...queryResponse, chart: { type: 'none', points: [] } });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText('Failures this week'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Run' }));
    expect(await screen.findAllByTestId('report-row')).toHaveLength(2);
    expect(screen.queryByText('Nothing to chart for this filter.')).not.toBeInTheDocument();
  });
});
