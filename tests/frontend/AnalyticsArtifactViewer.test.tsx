import React from 'react';
import { artifactToCsv, artifactToJson } from '../../frontend/src/components/agent-chat/analyticsExport';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import {
  AnalyticsArtifactViewer,
  AnalyticsCanvasSpec,
  AnalyticsVisualizationSpec,
  pivotRows,
  truncateTick,
  formatDuration,
  formatAnalyticsValueWithUnit,
} from '../../frontend/src/components/agent-chat/AnalyticsArtifactViewer';

// jsdom has no layout, so ResponsiveContainer would never measure a size and recharts would draw nothing.
vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('recharts')>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactElement }) => (
      <div style={{ width: 800, height: 400 }}>{React.cloneElement(children as React.ReactElement<any>, { width: 800, height: 400 })}</div>
    ),
  };
});

function viz(overrides: Partial<AnalyticsVisualizationSpec> = {}): AnalyticsVisualizationSpec {
  const rows = overrides.data?.rows ?? [];
  return {
    schema: 'vpt-artifact/v1', kind: 'visualization', title: 'Artifact', mark: 'table',
    data: { model: 'analytics-tabular-v1', source_id: 'kpi', fields: Object.keys(rows[0] || {}), rows, row_count: rows.length, truncated: false },
    encoding: { x: null, y: null, series: null, tooltip: [] },
    options: { legend: true, missing: 'gap', max_categories: 40, max_series: 12, fallback_applied: null, unit: null },
    ...overrides,
  };
}

const radarRows = [
  { kpi_name: 'Home', variant: 'v1', avg_ms: 100 }, { kpi_name: 'Guide', variant: 'v1', avg_ms: 200 }, { kpi_name: 'VOD', variant: 'v1', avg_ms: 300 },
  { kpi_name: 'Home', variant: 'v2', avg_ms: 110 }, { kpi_name: 'Guide', variant: 'v2', avg_ms: null }, { kpi_name: 'VOD', variant: 'v2', avg_ms: 280 },
];
const radar = (rows = radarRows) => viz({
  title: 'KPI radar', mark: 'radar',
  data: { model: 'analytics-tabular-v1', source_id: 'kpi', fields: ['kpi_name', 'variant', 'avg_ms'], rows, row_count: rows.length, truncated: false },
  encoding: { x: 'kpi_name', y: 'avg_ms', series: 'variant', tooltip: ['avg_ms'] },
});

describe('AnalyticsArtifactViewer', () => {
  it('renders normalized table data and explicit missing values', () => {
    render(<AnalyticsArtifactViewer spec={viz({ data: { model: 'analytics-tabular-v1', source_id: 'kpi', fields: ['kpi_name', 'value'], rows: [{ kpi_name: 'Home', value: null }], row_count: 1, truncated: false } })} />);
    expect(screen.getByText('kpi name')).toBeInTheDocument();
    expect(screen.getByText('Home')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('renders a bounded multi-panel canvas', () => {
    const panel = viz({ title: 'Pass rate', mark: 'stat', data: { model: 'analytics-tabular-v1', source_id: 'scripts', fields: ['pass_rate'], rows: [{ pass_rate: 97.5 }], row_count: 1, truncated: false } });
    const canvas: AnalyticsCanvasSpec = {
      schema: 'vpt-artifact/v1', kind: 'canvas', title: 'Overview', layout: { columns: 3 },
      panels: [panel, { ...panel, title: 'Duration' }, { ...panel, title: 'Failures' }],
    };
    const { container } = render(<AnalyticsArtifactViewer spec={canvas} />);
    expect(screen.getByText('Pass rate')).toBeInTheDocument();
    expect(screen.getByText('Duration')).toBeInTheDocument();
    expect(screen.getAllByText('97.5')).toHaveLength(3);
    expect(container.querySelectorAll('[data-analytics-panel]')).toHaveLength(3);
    expect(screen.getAllByRole('button', { name: 'CSV' })).toHaveLength(1);
  });

  it('renders radar series names', async () => {
    const { container } = render(<AnalyticsArtifactViewer spec={radar()} />);
    await waitFor(() => expect(container.querySelector('svg.recharts-surface')).not.toBeNull());
    expect(await screen.findByText('v1')).toBeInTheDocument();
    expect(screen.getByText('v2')).toBeInTheDocument();
  });

  it('keeps a missing radar value as a gap instead of zero', async () => {
    expect(pivotRows(radar()).rows.find((row) => row.kpi_name === 'Guide')).toEqual({ kpi_name: 'Guide', v1: 200, v2: null });
    const rows = radarRows.filter((row) => !(row.variant === 'v2' && row.kpi_name === 'Guide'));
    expect(pivotRows(radar(rows)).rows.find((row) => row.kpi_name === 'Guide')).toEqual({ kpi_name: 'Guide', v1: 200 });
    const { container } = render(<AnalyticsArtifactViewer spec={radar()} />);
    await waitFor(() => expect(container.querySelector('svg.recharts-surface')).not.toBeNull());
    expect(await screen.findByText('v2')).toBeInTheDocument();
  });

  it('discloses a readability fallback and truncation', async () => {
    const spec = viz({
      mark: 'bar', options: { ...viz().options, fallback_applied: 'bar', fallback_reason: 'radar needs 3 to 20 categories' },
      data: { model: 'analytics-tabular-v1', source_id: 'kpi', fields: ['kpi_name', 'avg_ms'], rows: [{ kpi_name: 'Home', avg_ms: 1 }, { kpi_name: 'Guide', avg_ms: 2 }], row_count: 2, truncated: true },
      encoding: { x: 'kpi_name', y: 'avg_ms', series: null, tooltip: [] },
    });
    render(<AnalyticsArtifactViewer spec={spec} />);
    expect(screen.getByText('Shown as bar instead of the requested chart: radar needs 3 to 20 categories')).toBeInTheDocument();
    expect(screen.getByText('Showing first 2 rows')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'SVG' })).toBeEnabled());
  });

  it('renders the comparison table with samples, missing side and regressions', () => {
    const spec = viz({
      comparison: {
        model: 'analytics-comparison-v1', align_by: 'kpi_name', series_field: 'variant', metric: 'avg_ms', baseline: 'v1', candidate: 'v2',
        sample_metric: 'sample_count', direction: 'lower_is_better',
        rows: [
          { kpi_name: 'Home', baseline: 100, candidate: 130, delta: 30, percent_delta: 30, baseline_samples: 11, candidate_samples: 12, missing: null },
          { kpi_name: 'VOD', baseline: 50, candidate: null, delta: null, percent_delta: null, baseline_samples: 7, candidate_samples: 0, missing: 'candidate' },
        ],
      },
    });
    const { container } = render(<AnalyticsArtifactViewer spec={spec} />);
    expect(screen.getByRole('table', { name: 'comparison' })).toBeInTheDocument();
    expect(screen.getByText('Baseline (v1)')).toBeInTheDocument();
    expect(screen.queryByText('Missing in candidate')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /with data on one side only/ }));
    expect(screen.getByText('Missing in candidate')).toBeInTheDocument();
    expect(screen.getByText('11')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('+30%')).toBeInTheDocument();
    expect(screen.getByText('Regression')).toBeInTheDocument();
    expect(container.querySelectorAll('tr[data-regression]')).toHaveLength(1);
  });

  it('shows export buttons and disables image exports for a table', () => {
    render(<AnalyticsArtifactViewer spec={viz({ data: { model: 'analytics-tabular-v1', source_id: 'kpi', fields: ['a'], rows: [{ a: 1 }], row_count: 1, truncated: false } })} />);
    ['CSV', 'JSON', 'Report'].forEach((name) => expect(screen.getByRole('button', { name })).toBeEnabled());
    expect(screen.getByRole('button', { name: 'SVG' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'PNG' })).toBeDisabled();
  });

  it('enables image exports once the chart is drawn', async () => {
    render(<AnalyticsArtifactViewer spec={radar()} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'SVG' })).toBeEnabled());
    expect(screen.getByRole('button', { name: 'PNG' })).toBeEnabled();
  });

  it('downloads CSV through an object URL', async () => {
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:analytics');
    const revokeObjectURL = vi.fn();
    const original = { createObjectURL: URL.createObjectURL, revokeObjectURL: URL.revokeObjectURL };
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(<AnalyticsArtifactViewer spec={viz({ title: 'My KPIs', data: { model: 'analytics-tabular-v1', source_id: 'kpi', fields: ['a'], rows: [{ a: '=1+1' }], row_count: 1, truncated: false } })} />);
    fireEvent.click(screen.getByRole('button', { name: 'CSV' }));
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const anchor = click.mock.instances[0] as unknown as HTMLAnchorElement;
    expect(anchor.download).toBe('my-kpis.csv');
    const blob = createObjectURL.mock.calls[0][0];
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob);
    });
    expect(text).toBe("a\r\n'=1+1\r\n");
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith('blob:analytics'));
    Object.assign(URL, original);
  });
});

describe('scope note and comparison layout (TASK-43 UI polish)', () => {
  const NOTE = 'Limited to the 2 host(s) of the selected server';
  const scoped = (title: string, note: string | null = NOTE) => {
    const base = radar();
    return { ...base, title, options: { ...base.options, scope_note: note } };
  };
  const canvas = (panels: AnalyticsVisualizationSpec[]): AnalyticsCanvasSpec => ({
    schema: 'vpt-artifact/v1', kind: 'canvas', title: 'Overview', layout: { columns: 2 }, panels,
  });

  it('shows the scope note once for a whole canvas, not once per panel', () => {
    render(<AnalyticsArtifactViewer spec={canvas([scoped('A'), scoped('B'), scoped('C')])} />);
    expect(screen.getAllByText(NOTE)).toHaveLength(1);
  });

  it('shows each distinct scope note once', () => {
    render(<AnalyticsArtifactViewer spec={canvas([scoped('A'), scoped('B', 'Other scope'), scoped('C')])} />);
    expect(screen.getAllByText(NOTE)).toHaveLength(1);
    expect(screen.getAllByText('Other scope')).toHaveLength(1);
  });

  it('shows a defaulted-interface note once per canvas', () => {
    const DEFAULTED = 'Interface: stb_tv (most KPI samples in scope); ask for another interface to change';
    const panel = (title: string) => {
      const base = radar();
      return { ...base, title, options: { ...base.options, defaulted_filters: { userinterface_name: 'stb_tv' }, defaulted_filters_note: DEFAULTED } };
    };
    render(<AnalyticsArtifactViewer spec={canvas([panel('A'), panel('B')])} />);
    expect(screen.getAllByText(DEFAULTED)).toHaveLength(1);
  });

  it('still shows the note on a single visualization', () => {
    render(<AnalyticsArtifactViewer spec={scoped('Solo')} />);
    expect(screen.getAllByText(NOTE)).toHaveLength(1);
  });

  it('carries the note once in a canvas report export', async () => {
    const { buildReportHtml } = await import('../../frontend/src/components/agent-chat/analyticsExport');
    const html = buildReportHtml(canvas([scoped('A'), scoped('B'), scoped('C')]));
    expect(html.split(NOTE).length - 1).toBe(1);
    expect(buildReportHtml(scoped('Solo')).split(NOTE).length - 1).toBe(1);
  });

  it('puts the radar chart before the comparison table', () => {
    const spec = {
      ...radar(),
      comparison: {
        model: 'analytics-comparison-v1' as const, align_by: 'kpi_name', series_field: 'variant', metric: 'avg_ms',
        baseline: 'v1', candidate: 'v2', sample_metric: 'n', direction: 'lower_is_better' as const, regression_over_percent: 10,
        rows: [
          { kpi_name: 'Home', baseline: 100, candidate: 110, delta: 10, percent_delta: 10, baseline_samples: 1, candidate_samples: 1, missing: null },
          { kpi_name: 'Guide', baseline: 200, candidate: null, delta: null, percent_delta: null, baseline_samples: 1, candidate_samples: 0, missing: 'candidate' as const },
        ],
      },
    };
    const { container } = render(<AnalyticsArtifactViewer spec={spec} />);
    const chart = container.querySelector('[data-analytics-chart]') as HTMLElement;
    const table = screen.getByRole('table', { name: 'comparison' });
    expect(chart).toBeTruthy();
    expect(chart.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Show 1 with data on one side only' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'CSV' })).toBeInTheDocument();
  });

  it('truncates long angled bar labels and reserves axis height (BUG-0314)', async () => {
    const long = 'acceptance-stb4-tv-20261002-0607-stb';
    const rows = Array.from({ length: 8 }, (_, i) => ({ device: `${long}${i}`, avg_kpi_ms: 100 + i }));
    const spec = viz({
      title: 'KPI avg', mark: 'bar',
      data: { model: 'analytics-tabular-v1', source_id: 'kpi', fields: ['device', 'avg_kpi_ms'], rows, row_count: 8, truncated: false },
      encoding: { x: 'device', y: 'avg_kpi_ms', series: null, tooltip: [] },
    });
    const { container } = render(<AnalyticsArtifactViewer spec={spec} />);
    await waitFor(() => expect(container.querySelector('.recharts-xAxis')).not.toBeNull());
    // jsdom draws no tick text; the XAxis height reserved for angled labels is still observable.
    expect(container.querySelector('.recharts-xAxis .recharts-cartesian-axis-line')?.getAttribute('height')).toBe('80');
    expect(truncateTick('short')).toBe('short');
    expect(truncateTick(long)).toHaveLength(18);
    expect(truncateTick(long).endsWith('…')).toBe(true);
  });

  it('humanizes durations for display only (BUG-0316)', () => {
    expect(formatDuration(850, 'ms')).toBe('850 ms');
    expect(formatDuration(1500, 'ms')).toBe('1.5 s');
    expect(formatDuration(1800000, 'ms')).toBe('30 min');
    expect(formatDuration(5400000, 'ms')).toBe('1.5 h');
    expect(formatDuration(1600000, 'ms')).toBe('26.7 min');
    expect(formatDuration(-1500, 'ms')).toBe('-1.5 s');
    expect(formatDuration(90, 's')).toBe('1.5 min');
    expect(formatDuration(90, 'min')).toBe('1.5 h');
    expect(formatDuration(null, 'ms')).toBe('—');
    expect(formatAnalyticsValueWithUnit(null, 'ms')).toBe('—');
    expect(formatAnalyticsValueWithUnit(12, 'fps')).toBe('12 fps');
    expect(formatAnalyticsValueWithUnit(12, null)).toBe('12');
  });

  it('shows humanized Y ticks wide enough for the labels and keeps raw numbers in exports (BUG-0316)', async () => {
    const rows = [{ day: '2026-10-01', avg_duration_ms: 1800000 }, { day: '2026-10-02', avg_duration_ms: 1350000 }];
    const spec = viz({
      title: 'Duration Trend', mark: 'line',
      data: { model: 'analytics-tabular-v1', source_id: 'runs', fields: ['day', 'avg_duration_ms'], rows, row_count: 2, truncated: false },
      encoding: { x: 'day', y: 'avg_duration_ms', series: null, tooltip: [] },
      options: { legend: true, missing: 'gap', max_categories: 40, max_series: 12, fallback_applied: null, unit: 'ms' },
    });
    const { container } = render(<AnalyticsArtifactViewer spec={spec} />);
    await waitFor(() => expect(container.querySelector('.recharts-yAxis')).not.toBeNull());
    const width = Number(container.querySelector('.recharts-yAxis .recharts-cartesian-axis-line')?.getAttribute('width'));
    expect(width).toBeGreaterThanOrEqual('30 min'.length * 7);
    expect(artifactToCsv(spec)).toContain('1800000');
    expect(artifactToJson(spec)).toContain('1800000');
    expect(artifactToCsv(spec)).not.toContain('30 min');
  });

  it('keeps table columns whole and scrollable inside a canvas cell (BUG-0317)', () => {
    const rows = [{ test_case: 'login', failure_count: 7 }];
    const panel = viz({
      title: 'Failing Test Cases', mark: 'table',
      data: { model: 'analytics-tabular-v1', source_id: 'runs', fields: ['test_case', 'failure_count'], rows, row_count: 1, truncated: false },
    });
    const canvas = { schema: 'vpt-artifact/v1', kind: 'canvas', title: 'C', layout: { columns: 3 }, panels: [panel], options: {} } as unknown as AnalyticsCanvasSpec;
    const { container } = render(<AnalyticsArtifactViewer spec={canvas} />);
    const header = screen.getByText('failure count');
    expect((header as HTMLElement).style.whiteSpace).toBe('nowrap');
    const wrapper = container.querySelector('[data-analytics-table]') as HTMLElement;
    expect(getComputedStyle(wrapper).overflowX).toBe('auto');
    expect(wrapper.querySelector('table')?.style.minWidth).toBe('max-content');
  });

  describe('Grafana link', () => {
    const withGrafana = (grafana: AnalyticsCanvasSpec['grafana']): AnalyticsCanvasSpec => ({
      schema: 'vpt-artifact/v1', kind: 'canvas', title: 'Overview', layout: { columns: 2 }, panels: [radar(), radar()], grafana,
    });

    afterEach(() => { delete (window as any).__VPT_CONFIG__; });

    it('resolves the server path against the app Grafana base, opens in a new tab and shows the expiry', () => {
      (window as any).__VPT_CONFIG__ = { VITE_GRAFANA_URL: 'https://vpt.example.test/grafana/' };
      render(<AnalyticsArtifactViewer spec={withGrafana({ path: '/grafana/d/atlas-draft-1?var-workspace=w1', uid: 'atlas-draft-1', expires_at: '2026-10-06T12:00:00+00:00', reused: false })} />);
      const link = screen.getByRole('link', { name: 'Open in Grafana' });
      expect(link).toHaveAttribute('href', 'https://vpt.example.test/grafana/d/atlas-draft-1?var-workspace=w1');
      expect(link).toHaveAttribute('target', '_blank');
      expect(link.getAttribute('rel')).toContain('noopener');
      expect(screen.getByText(/draft · expires/)).toBeInTheDocument();
    });

    it('never links to the marketing domain: the app base wins, whatever server answered', () => {
      (window as any).__VPT_CONFIG__ = { VITE_GRAFANA_URL: 'https://virtualpytest.angelstreet.io/grafana' };
      render(<AnalyticsArtifactViewer spec={withGrafana({ path: '/grafana/d/atlas-draft-9', uid: 'atlas-draft-9', expires_at: null, reused: false })} />);
      expect(screen.getByRole('link', { name: 'Open in Grafana' })).toHaveAttribute('href', 'https://virtualpytest.angelstreet.io/grafana/d/atlas-draft-9');
    });

    it('keeps the same-origin /grafana path when no base is configured', () => {
      render(<AnalyticsArtifactViewer spec={withGrafana({ path: '/grafana/d/atlas-draft-9', uid: 'atlas-draft-9', expires_at: null, reused: false })} />);
      expect(screen.getByRole('link', { name: 'Open in Grafana' })).toHaveAttribute('href', '/grafana/d/atlas-draft-9');
    });

    it('labels a maintained dashboard and shows nothing when absent or unsafe', () => {
      const { unmount } = render(<AnalyticsArtifactViewer spec={withGrafana({ path: '/grafana/d/maintained', uid: 'maintained', expires_at: null, reused: true })} />);
      expect(screen.getByText('maintained dashboard')).toBeInTheDocument();
      unmount();
      render(<AnalyticsArtifactViewer spec={withGrafana(undefined)} />);
      expect(screen.queryByText('Open in Grafana')).toBeNull();
      cleanup();
      render(<AnalyticsArtifactViewer spec={withGrafana({ path: 'javascript:alert(1)', uid: 'x', expires_at: null, reused: false })} />);
      expect(screen.queryByText('Open in Grafana')).toBeNull();
    });
  });
});
