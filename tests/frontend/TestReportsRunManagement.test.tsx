/**
 * TestReports + run management: the existing controls stay, and the additions (summary
 * links, server-side governance filters, bulk assignment, flaky badges, no rerun for
 * manual rows) behave as specified.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => {
  const rows = [
    {
      id: 'r-auto',
      team_id: 't',
      script_name: 'dns_lookuptime.py',
      script_type: 'script',
      userinterface_name: 'ui-a',
      host_name: 'host-1',
      device_name: 'dev-1',
      success: false,
      execution_time_ms: 12000,
      started_at: '2026-10-01T10:00:00Z',
      completed_at: '2026-10-01T10:00:12Z',
      html_report_r2_path: null,
      html_report_r2_url: 'https://storage.example/report.html',
      logs_r2_path: null,
      logs_r2_url: 'https://storage.example/logs.txt',
      discard: false,
      error_msg: null,
      metadata: {},
      created_at: '2026-10-01T10:00:00Z',
      updated_at: '2026-10-01T10:00:12Z',
      checked: true,
      check_type: 'ai',
      // getAllScriptResults rows now carry governance columns and their labels.
      milestone_id: 'm-1',
      run_group_id: null,
      labels: [{ id: 'l-1', name: 'nightly', color: '#2a78d6' }],
    },
    {
      id: 'r-manual',
      team_id: 't',
      script_name: 'manual_checkout',
      script_type: 'manual',
      userinterface_name: null,
      host_name: 'host-1',
      device_name: 'dev-1',
      success: true,
      execution_time_ms: 5000,
      started_at: '2026-10-01T09:00:00Z',
      completed_at: '2026-10-01T09:00:05Z',
      html_report_r2_path: null,
      html_report_r2_url: null,
      logs_r2_path: null,
      logs_r2_url: null,
      discard: false,
      error_msg: null,
      metadata: {},
      created_at: '2026-10-01T09:00:00Z',
      updated_at: '2026-10-01T09:00:05Z',
      milestone_id: null,
      run_group_id: null,
      labels: [],
    },
  ];
  const flakyData = {
    window_days: 14,
    window_start: '2026-09-19T00:00:00Z',
    window_end: '2026-10-03T00:00:00Z',
    sample_size: 20,
    min_attempts: 5,
    row_total: 1,
    scope: { host_count: 1, device_filter_applied: false },
    identities_evaluated: 4,
    rows: [
      {
        identity: {
          script_name: 'dns_lookuptime.py',
          script_type: 'dns_lookuptime.py',
          userinterface_name: 'ui-a',
          environment: 'prod',
          host_name: 'host-1',
          device_name: 'dev-1',
        },
        attempts: 6,
        passes: 3,
        failures: 3,
        transitions: 5,
        flaky_score: 1,
        last_status: 'failed',
        first_started_at: '2026-09-25T10:00:00Z',
        last_started_at: '2026-10-01T10:00:00Z',
        latest_script_result_id: 'r-auto',
      },
    ],
  };
  return {
    rows,
    getAllScriptResults: vi.fn(async () => rows),
    useQualityQuery: vi.fn(() => ({ data: flakyData, isLoading: false, error: null })),
    milestones: { data: { items: [{ id: 'm-1', name: 'Release 1' }] }, isLoading: false, error: null },
    empty: { data: { items: [] }, isLoading: false, error: null },
    idleMutation: { mutateAsync: vi.fn(async () => ({})), isPending: false },
    rerunPayload: { type: 'script', scriptName: 'x', hostName: 'host-1', deviceId: 'device1' },
  };
});

vi.mock('../../frontend/src/hooks/pages/useScriptResults', () => ({
  useScriptResults: () => ({
    getAllScriptResults: h.getAllScriptResults,
    updateCheckedStatus: async () => {},
    updateDiscardStatus: async () => {},
  }),
}));
vi.mock('../../frontend/src/hooks/pages/useCampaignResults', () => ({
  useCampaignResults: () => ({ getAllCampaignResults: async () => [] }),
}));
vi.mock('../../frontend/src/hooks/useHostManager', () => ({ useHostData: () => ({ getAllHosts: () => [] }) }));
vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({ selectedServer: 'server-1' }),
}));
vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({
  useWorkspaceContext: () => ({ activeWorkspace: null, isDeviceAllowed: () => true }),
}));
vi.mock('../../frontend/src/hooks/script/useRerun', () => ({
  useRerun: () => ({ rerun: async () => ({ started: true }), rerunningIds: [] }),
}));
// Every row gets a rerun payload here, so a missing rerun button can only come from the
// manual-row rule in TestReports itself.
vi.mock('../../frontend/src/utils/executionUtils', () => ({
  formatScriptLabel: (name: string) => name,
  ensureScriptIdentityMap: () => {},
  buildRerunPayloadFromResult: () => h.rerunPayload,
}));
vi.mock('../../frontend/src/hooks/useToast', () => ({
  useToast: () => ({ showSuccess: () => {}, showError: () => {}, showInfo: () => {}, showWarning: () => {} }),
}));
vi.mock('../../frontend/src/hooks/reports/useRunManagement', () => ({
  useMilestones: () => h.milestones,
  useRunGroups: () => h.empty,
  useLabels: () => h.empty,
  useQualityQuery: h.useQualityQuery,
  useReportPermissions: () => ({ canEdit: true }),
  useGovernanceMutations: () => ({
    setResultMilestone: h.idleMutation,
    setResultRunGroup: h.idleMutation,
    setResultLabels: h.idleMutation,
    batchAssign: h.idleMutation,
  }),
}));

import TestReports from '../../frontend/src/pages/TestReports';

const renderAt = (url = '/test-results/reports') =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <TestReports />
    </MemoryRouter>,
  );

describe('TestReports with run management', () => {
  beforeEach(() => {
    localStorage.clear();
    h.getAllScriptResults.mockClear();
    h.useQualityQuery.mockClear();
  });

  it('keeps rerun, report, logs, checked and discard controls', async () => {
    renderAt();
    await screen.findByText('dns_lookuptime.py');

    // The (hidden) Campaigns table renders its own Report/Logs headers too.
    expect(screen.getByText('Rerun')).toBeInTheDocument();
    expect(screen.getAllByText('Report').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Logs').length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText('Rerun on the same target with the same config').length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: 'Open Report' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: 'Open Logs' }).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: 'Show Analysis' }));
    expect(screen.getByText('Checked')).toBeInTheDocument();
    expect(screen.getByText('Discard')).toBeInTheDocument();
  });

  it('shows the labels the list endpoint returns per row, without another request', async () => {
    renderAt();
    expect(await screen.findByTestId('result-label')).toHaveTextContent('nightly');
  });

  it('links each script row to its run summary', async () => {
    renderAt();
    await screen.findByText('dns_lookuptime.py');
    // The script name itself is the link to the run summary (no separate icon).
    const links = screen.getAllByRole('link').filter((link) => link.getAttribute('href')?.startsWith('/test-results/runs/script/'));
    expect(links.map((link) => link.getAttribute('href'))).toEqual(
      expect.arrayContaining(['/test-results/runs/script/r-auto', '/test-results/runs/script/r-manual']),
    );
  });

  it('shows no rerun button for a manual row', async () => {
    renderAt();
    await screen.findByText('manual_checkout');
    // The existing rerun control is an icon button inside a tooltip-labelled span.
    const rerunControls = screen.getAllByLabelText('Rerun on the same target with the same config');
    expect(rerunControls).toHaveLength(1);
    const manualRow = screen.getByText('manual_checkout').closest('tr') as HTMLElement;
    expect(within(manualRow).queryByLabelText('Rerun on the same target with the same config')).toBeNull();
  });

  it('passes the URL governance filter to the server query', async () => {
    renderAt('/test-results/reports?milestone=m-1&label=l-9');
    await waitFor(() =>
      expect(h.getAllScriptResults).toHaveBeenCalledWith(
        expect.objectContaining({ milestone_id: 'm-1', label_id: 'l-9' }),
      ),
    );
  });

  it('badges flaky rows from one table-wide quality query', async () => {
    renderAt();
    await screen.findByText('dns_lookuptime.py');
    expect(screen.getAllByTestId('flaky-badge')).toHaveLength(1);
    const autoRow = screen.getByText('dns_lookuptime.py').closest('tr') as HTMLElement;
    expect(within(autoRow).getByTestId('flaky-badge')).toBeInTheDocument();
    // Only the flaky insight is requested, and never with a per-row parameter.
    for (const call of h.useQualityQuery.mock.calls) {
      expect(call[0]).toBe('flaky');
      expect(call[1]).toEqual({ windowDays: 14 });
    }
  });

  it('enables bulk assignment once a row is selected', async () => {
    renderAt();
    await screen.findByText('dns_lookuptime.py');
    const assign = screen.getByRole('button', { name: 'Assign (0)' });
    expect(assign).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select dns_lookuptime.py' }));
    expect(screen.getByRole('button', { name: 'Assign (1)' })).toBeEnabled();
  });
});
