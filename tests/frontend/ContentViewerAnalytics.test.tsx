import React from 'react';
import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';

import { ContentViewer } from '../../frontend/src/components/agent-chat/ContentViewer';
import { formatAnalyticsValue } from '../../frontend/src/components/agent-chat/AnalyticsArtifactViewer';
import type { AnalyticsArtifactSpec } from '../../frontend/src/components/agent-chat/AnalyticsArtifactViewer';

vi.mock('../../frontend/src/hooks/useHostManager', () => ({
  useHostData: () => ({ getAllHosts: () => [], getDevicesFromHost: () => [] }),
  useHostControl: () => ({ isControlActive: false, selectedHost: null, selectedDeviceId: null }),
}));
vi.mock('../../frontend/src/components/agent-chat/NavigationTreeViewer', () => ({ NavigationTreeViewer: () => null }));
vi.mock('../../frontend/src/components/agent-chat/TestCaseFlowViewer', () => ({ TestCaseFlowViewer: () => null }));
vi.mock('../../frontend/src/components/agent-chat/CampaignFlowViewer', () => ({ CampaignFlowViewer: () => null }));
vi.mock('../../frontend/src/components/agent-chat/HeatmapViewer', () => ({ HeatmapViewer: () => null }));
vi.mock('../../frontend/src/components/agent-chat/AlertsViewer', () => ({ AlertsViewer: () => null }));
vi.mock('../../frontend/src/components/common/DeviceStreaming/DeviceStreamGrid', () => ({
  DeviceStreamGrid: () => <div>device stream grid</div>,
}));

const tableSpec = (rows: Record<string, unknown>[]): AnalyticsArtifactSpec => ({
  schema: 'vpt-artifact/v1', kind: 'visualization', title: 'Failing testcases', mark: 'table',
  data: { model: 'analytics-tabular-v1', source_id: 'script_results', fields: ['script_name', 'last_run_at'], rows, row_count: rows.length, truncated: false },
  encoding: { x: 'script_name', y: null, series: null, tooltip: [] },
  options: { legend: false, missing: 'gap', max_categories: 40, max_series: 12, fallback_applied: null, unit: null },
});

const tabModeProps = {
  onClose: () => {},
  selectedDevices: ['host-a:device1'],
  selectedUserInterface: undefined,
};

describe('ContentViewer — Atlas analytics in tab mode', () => {
  // Live on the deployed build: Agent Chat is always in tab mode (devices are always passed),
  // and tab mode never rendered the analytics artifact — the panel stayed on "Device".
  it('shows the artifact in an Analytics tab with its export toolbar', () => {
    const rows = [{ script_name: 'zap_check', last_run_at: '2026-10-04T08:08:09.245602+00:00' }];
    render(<ContentViewer {...tabModeProps} contentType="data-table" contentData={{ artifact_spec: tableSpec(rows) }}
      activeTab="analytics" analyticsContent={{ title: 'Failing testcases', data: { artifact_spec: tableSpec(rows) } }} />);
    expect(screen.getByRole('tab', { name: 'Failing testcases' })).toBeInTheDocument();
    expect(screen.getByText('zap_check')).toBeInTheDocument();
    expect(screen.getByText('2026-10-04 08:08')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'CSV' })).toBeInTheDocument();
    expect(screen.queryByText('device stream grid')).not.toBeInTheDocument();
  });

  it('has no Analytics tab until Atlas produced an artifact', () => {
    render(<ContentViewer {...tabModeProps} contentType={null} contentData={null} activeTab="device-preview" />);
    expect(screen.queryByRole('tab', { name: /analytics/i })).not.toBeInTheDocument();
  });

  it('says when nothing matched instead of drawing an empty chart', () => {
    render(<ContentViewer {...tabModeProps} contentType="data-table" contentData={null}
      activeTab="analytics" analyticsContent={{ data: { artifact_spec: tableSpec([]) } }} />);
    expect(screen.getByText('No data matched this question (script results).')).toBeInTheDocument();
  });
});

describe('formatAnalyticsValue', () => {
  it('reads API timestamps as dates or minutes, leaves other values alone', () => {
    expect(formatAnalyticsValue('2026-09-17T00:00:00+00:00')).toBe('2026-09-17');
    expect(formatAnalyticsValue('2026-10-04T08:08:09.245602+00:00')).toBe('2026-10-04 08:08');
    expect(formatAnalyticsValue('stb-testop')).toBe('stb-testop');
    expect(formatAnalyticsValue(null)).toBe('—');
    expect(formatAnalyticsValue(42)).toBe('42');
  });
});

describe('comparison table', () => {
  it('folds rows with one side missing and keeps the regressions visible', async () => {
    const { AnalyticsArtifactViewer } = await import('../../frontend/src/components/agent-chat/AnalyticsArtifactViewer');
    const { fireEvent } = await import('@testing-library/react');
    const spec: AnalyticsArtifactSpec = {
      ...tableSpec([{ script_name: 'x', last_run_at: null }]),
      comparison: {
        model: 'analytics-comparison-v1', align_by: 'kpi_label', series_field: 'variant', metric: 'avg_kpi_ms',
        baseline: 'Base', candidate: 'v1', sample_metric: 'sample_count', direction: 'lower_is_better', regression_over_percent: 10,
        rows: [
          { kpi_label: 'Home', baseline: 100, candidate: 150, delta: 50, percent_delta: 50, baseline_samples: 4, candidate_samples: 2, missing: null },
          { kpi_label: 'Guide', baseline: 90, candidate: null, delta: null, percent_delta: null, baseline_samples: 3, candidate_samples: 0, missing: 'candidate' },
        ],
      },
      options: { legend: false, missing: 'gap', max_categories: 40, max_series: 12, fallback_applied: null, unit: null,
                 scope_note: 'Limited to the 2 host(s) of the selected server' },
    };
    render(<AnalyticsArtifactViewer spec={spec} />);
    expect(screen.getByText('Home')).toBeInTheDocument();
    expect(screen.queryByText('Guide')).not.toBeInTheDocument();
    expect(screen.getByText(/1 regression\(s\) in 1 compared/)).toBeInTheDocument();
    expect(screen.getByText('Limited to the 2 host(s) of the selected server')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show 1 with data on one side only' }));
    expect(screen.getByText('Guide')).toBeInTheDocument();
  });
});

describe('who can open the Atlas chat', () => {
  // A viewer cannot start a conversation (read-only floor on POST /server/agent/sessions), so the
  // chat page needs ai_agent:use — held by tester, developer, manager and admin, not viewer.
  it('guards /ai-agent with ai_agent:use and leaves the agent dashboard on view', async () => {
    const { requiredPermissionForPath } = await import('../../frontend/src/types/auth');
    expect(requiredPermissionForPath('/ai-agent')).toBe('ai_agent:use');
    expect(requiredPermissionForPath('/agent-dashboard')).toBe('ai_agent:view');
  });
});
