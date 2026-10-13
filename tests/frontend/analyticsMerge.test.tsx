import React from 'react';
import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';

import { mergeAnalyticsArtifact } from '../../frontend/src/components/agent-chat/analyticsMerge';
import { ContentViewer } from '../../frontend/src/components/agent-chat/ContentViewer';
import type { AnalyticsArtifactSpec, AnalyticsVisualizationSpec } from '../../frontend/src/components/agent-chat/AnalyticsArtifactViewer';

vi.mock('../../frontend/src/hooks/useHostManager', () => ({
  useHostData: () => ({ getAllHosts: () => [], getDevicesFromHost: () => [] }),
  useHostControl: () => ({ isControlActive: false, selectedHost: null, selectedDeviceId: null }),
}));
vi.mock('../../frontend/src/components/agent-chat/NavigationTreeViewer', () => ({ NavigationTreeViewer: () => null }));
vi.mock('../../frontend/src/components/agent-chat/TestCaseFlowViewer', () => ({ TestCaseFlowViewer: () => null }));
vi.mock('../../frontend/src/components/agent-chat/CampaignFlowViewer', () => ({ CampaignFlowViewer: () => null }));
vi.mock('../../frontend/src/components/agent-chat/HeatmapViewer', () => ({ HeatmapViewer: () => null }));
vi.mock('../../frontend/src/components/agent-chat/AlertsViewer', () => ({ AlertsViewer: () => null }));
vi.mock('../../frontend/src/components/common/DeviceStreaming/DeviceStreamGrid', () => ({ DeviceStreamGrid: () => null }));

const panel = (title: string, mark: 'bar' | 'line' | 'table' = 'table', source = 'script_results'): AnalyticsVisualizationSpec => ({
  schema: 'vpt-artifact/v1', kind: 'visualization', title, mark,
  data: { model: 'analytics-tabular-v1', source_id: source, fields: ['k'], rows: [{ k: title }], row_count: 1, truncated: false },
  encoding: { x: 'k', y: null, series: null, tooltip: [] },
  options: { legend: false, missing: 'gap', max_categories: 40, max_series: 12, fallback_applied: null, unit: null },
});
const art = (p: AnalyticsArtifactSpec) => ({ title: p.title, data: { artifact_spec: p } });
const panelsOf = (c: { data: { artifact_spec?: AnalyticsArtifactSpec } }) => {
  const s = c.data.artifact_spec!;
  return s.kind === 'canvas' ? s.panels : [s];
};

describe('mergeAnalyticsArtifact', () => {
  it('folds three single-panel artifacts of one turn into one canvas', () => {
    let c = mergeAnalyticsArtifact(null, art(panel('Pass rate', 'bar')), 1);
    expect(c.data.artifact_spec!.kind).toBe('visualization');
    c = mergeAnalyticsArtifact(c, art(panel('Duration trend', 'line')), 1);
    expect(c.data.artifact_spec!.kind).toBe('canvas');
    expect(panelsOf(c)).toHaveLength(2);
    c = mergeAnalyticsArtifact(c, art(panel('Failing cases')), 1);
    expect(panelsOf(c).map((p) => p.title)).toEqual(['Pass rate', 'Duration trend', 'Failing cases']);
    expect(c.title).toBe('Analytics canvas');
  });

  it('replaces, not duplicates, the same artifact rendered twice', () => {
    let c = mergeAnalyticsArtifact(null, art(panel('Pass rate', 'bar')), 1);
    c = mergeAnalyticsArtifact(c, art(panel('Pass rate', 'bar')), 1);
    expect(panelsOf(c)).toHaveLength(1);
    expect(c.data.artifact_spec!.kind).toBe('visualization');
    c = mergeAnalyticsArtifact(c, art(panel('Other')), 1);
    c = mergeAnalyticsArtifact(c, art(panel('Pass rate', 'line')), 1);
    expect(panelsOf(c)).toHaveLength(2);
    expect(panelsOf(c)[0].mark).toBe('line');
  });

  it('starts fresh on a new turn', () => {
    let c = mergeAnalyticsArtifact(null, art(panel('Pass rate', 'bar')), 1);
    c = mergeAnalyticsArtifact(c, art(panel('Failing cases')), 2);
    expect(c.data.artifact_spec!.kind).toBe('visualization');
    expect(c.title).toBe('Failing cases');
  });

  it('renders the merged canvas with both panels', () => {
    let c = mergeAnalyticsArtifact(null, art(panel('Pass rate', 'table')), 1);
    c = mergeAnalyticsArtifact(c, art(panel('Failing cases')), 1);
    render(<ContentViewer onClose={() => {}} selectedDevices={['h:d']} contentType="report-chart"
      contentData={c.data} activeTab="analytics" analyticsContent={c} />);
    expect(screen.getAllByText('Pass rate').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Failing cases').length).toBeGreaterThan(0);
  });
});
