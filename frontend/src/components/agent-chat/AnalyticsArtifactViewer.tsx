import React, { useEffect, useRef, useState } from 'react';
import { Box, Button, Card, CardContent, Link, Tooltip as MuiTooltip, Typography, useTheme } from '@mui/material';
import { alpha } from '@mui/material/styles';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts';

import {
  artifactDisclosures,
  artifactFilename,
  artifactPanels,
  artifactToCsv,
  artifactToJson,
  buildReportHtml,
  downloadBlob,
  canvasScopeNotes,
  grafanaExpiryLabel,
  isRegression,
  safeGrafanaUrl,
  missingLabel,
  serializeSvg,
  slugify,
  svgSize,
  svgToPngBlob,
} from './analyticsExport';

export type AnalyticsMark = 'radar' | 'line' | 'area' | 'bar' | 'stacked-bar' | 'pie' | 'scatter' | 'heatmap' | 'stat' | 'state-timeline' | 'table';

export interface AnalyticsTabularData {
  model: 'analytics-tabular-v1';
  source_id: string;
  fields: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
}

export interface AnalyticsEncoding {
  x: string | null;
  y: string | null;
  series: string | null;
  tooltip: string[];
  time_grain?: 'hour' | 'day' | 'week' | 'month' | null;
}

export interface AnalyticsOptions {
  legend: boolean;
  missing: 'gap';
  max_categories: number;
  max_series: number;
  fallback_applied: string | null;
  fallback_reason?: string | null;
  scope_note?: string | null;
  defaulted_filters?: Record<string, string> | null;
  defaulted_filters_note?: string | null;
  category_overflow?: { kept: number; omitted: number; ranked_by: string; omitted_categories: string[] } | null;
  unit: string | null;
  units?: Record<string, string | null>;
}

export interface AnalyticsComparisonRow {
  [alignValue: string]: unknown;
  baseline: number | null;
  candidate: number | null;
  delta: number | null;
  percent_delta: number | null;
  baseline_samples: number | null;
  candidate_samples: number | null;
  missing: 'baseline' | 'candidate' | null;
}

export interface AnalyticsComparison {
  model: 'analytics-comparison-v1';
  align_by: string;
  series_field: string;
  metric: string;
  baseline: string | number;
  candidate: string | number;
  sample_metric: string;
  regression_over_percent?: number | null;
  direction?: 'lower_is_better' | 'higher_is_better';
  rows: AnalyticsComparisonRow[];
}

export interface AnalyticsProvenance {
  source_id: string;
  preset?: string | null;
  dashboard_ref?: string | null;
}

export interface AnalyticsVisualizationSpec {
  schema: 'vpt-artifact/v1';
  kind: 'visualization';
  title: string;
  mark: AnalyticsMark;
  data: AnalyticsTabularData;
  encoding: AnalyticsEncoding;
  options: AnalyticsOptions;
  comparison?: AnalyticsComparison;
  preset?: string;
  provenance?: AnalyticsProvenance;
}

/** Grafana dashboard Atlas created (a temporary draft) or found (a maintained dashboard) for a canvas. */
export interface AnalyticsGrafanaLink {
  /** `/grafana/d/<uid>?...`; resolved against the app's Grafana base by `safeGrafanaUrl`. */
  path: string;
  uid: string;
  expires_at: string | null;
  reused: boolean;
}

export interface AnalyticsCanvasSpec {
  schema: 'vpt-artifact/v1';
  kind: 'canvas';
  title: string;
  layout: { columns: 1 | 2 | 3 };
  panels: AnalyticsVisualizationSpec[];
  grafana?: AnalyticsGrafanaLink;
  preset?: string;
  provenance?: AnalyticsProvenance;
}

export type AnalyticsArtifactSpec = AnalyticsVisualizationSpec | AnalyticsCanvasSpec;

interface Props {
  spec?: AnalyticsArtifactSpec;
  chartType?: string;
  chartData?: any;
}

const COLORS = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4'];

function legacySpec(chartType?: string, chartData?: any): AnalyticsArtifactSpec | undefined {
  if (!chartType || !chartData) return undefined;
  if (Array.isArray(chartData.categories) && Array.isArray(chartData.series)) {
    const rows = chartData.categories.flatMap((category: string, categoryIndex: number) =>
      chartData.series.map((series: any) => ({ category, series: series.name, value: series.values?.[categoryIndex] ?? null })),
    );
    return {
      schema: 'vpt-artifact/v1', kind: 'visualization', title: '', mark: chartType as AnalyticsMark,
      data: { model: 'analytics-tabular-v1', source_id: '', fields: ['category', 'series', 'value'], rows, row_count: rows.length, truncated: false },
      encoding: { x: 'category', series: 'series', y: 'value', tooltip: [] },
      options: { legend: true, missing: 'gap', max_categories: rows.length, max_series: chartData.series.length, fallback_applied: null, unit: null },
    };
  }
  return undefined;
}

export function pivotRows(spec: AnalyticsVisualizationSpec) {
  const rows = spec.data?.rows || [];
  const x = spec.encoding?.x;
  const y = spec.encoding?.y;
  const series = spec.encoding?.series;
  if (!x || !y) return { rows, seriesNames: [y || 'value'] };
  if (!series) return { rows, seriesNames: [y] };
  const byX = new Map<unknown, Record<string, unknown>>();
  const seriesNames: string[] = [];
  rows.forEach((row) => {
    const name = String(row[series] ?? 'Unknown');
    if (!seriesNames.includes(name)) seriesNames.push(name);
    const key = row[x];
    const target = byX.get(key) || { [x]: key };
    target[name] = row[y] ?? null;
    byX.set(key, target);
  });
  return { rows: Array.from(byX.values()), seriesNames };
}

const CHART_MARKS: AnalyticsMark[] = ['radar', 'line', 'area', 'bar', 'stacked-bar', 'pie', 'scatter'];
const CHART_SVG_SELECTOR = '.recharts-wrapper > svg.recharts-surface';
const ISO_TIMESTAMP = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(:\d{2}(\.\d+)?)?([+-]\d{2}:\d{2}|Z)?$/;

/** Timestamps from the API (`2026-09-17T00:00:00+00:00`, with microseconds) read as `2026-09-17` or `2026-10-04 08:08`. */
export const formatAnalyticsValue = (value: unknown): string => {
  if (value == null) return '—';
  const text = String(value);
  const match = ISO_TIMESTAMP.exec(text);
  if (!match) return text;
  return match[2] === '00:00' && !match[4] ? match[1] : `${match[1]} ${match[2]}`;
};
const show = formatAnalyticsValue;

const DURATION_UNIT_MS: Record<string, number> = { ms: 1, s: 1000, sec: 1000, min: 60000 };
const trimNumber = (n: number): string => {
  const abs = Math.abs(n);
  const text = abs >= 100 ? String(Math.round(n)) : abs >= 10 ? n.toFixed(1) : n.toFixed(2);
  return text.includes('.') ? text.replace(/\.?0+$/, '') : text;
};
/** True when `unit` is a duration unit (ms, s, min) that `formatAnalyticsValueWithUnit` humanizes. */
export const isDurationUnit = (unit: string | null | undefined): boolean => !!unit && unit in DURATION_UNIT_MS;
/** Display-only: 1,600,000 ms -> "26.7 min", 90 min -> "1.5 h". Raw values are never changed (exports keep numbers). */
export const formatDuration = (value: unknown, unit: string): string => {
  const factor = DURATION_UNIT_MS[unit];
  const n = typeof value === 'number' ? value : value == null || value === '' ? NaN : Number(value);
  if (!factor || !Number.isFinite(n)) return show(value);
  const ms = n * factor;
  const abs = Math.abs(ms);
  if (abs >= 3600000) return `${trimNumber(ms / 3600000)} h`;
  if (abs >= 60000) return `${trimNumber(ms / 60000)} min`;
  if (abs >= 1000) return `${trimNumber(ms / 1000)} s`;
  return `${trimNumber(ms)} ms`;
};
/** Value + unit for axes, tooltips and cells. Null stays an em dash with no unit. */
export const formatAnalyticsValueWithUnit = (value: unknown, unit: string | null | undefined): string => {
  if (value == null) return '—';
  if (!unit) return show(value);
  return isDurationUnit(unit) ? formatDuration(value, unit) : `${show(value)} ${unit}`;
};

const DataTable: React.FC<{ spec: AnalyticsVisualizationSpec }> = ({ spec }) => {
  const theme = useTheme();
  const rows = spec.data?.rows || [];
  const fields = spec.data?.fields?.length ? spec.data.fields : (rows.length ? Object.keys(rows[0]) : []);
  const units = spec.options?.units || {};
  return (
    <Box data-analytics-table sx={{ overflowX: 'auto', overflowY: 'auto', maxWidth: '100%', maxHeight: '100%' }}>
      <table style={{ width: '100%', minWidth: 'max-content', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
        <thead><tr>{fields.map((field) => <th key={field} style={{ padding: 8, textAlign: 'left', whiteSpace: 'nowrap', borderBottom: `2px solid ${theme.palette.divider}` }}>{field.replace(/_/g, ' ')}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={index}>{fields.map((field) => <td key={field} style={{ padding: 8, borderBottom: `1px solid ${theme.palette.divider}` }}>{formatAnalyticsValueWithUnit(row[field], units[field])}</td>)}</tr>)}</tbody>
      </table>
    </Box>
  );
};

const ComparisonTable: React.FC<{ comparison: AnalyticsComparison }> = ({ comparison }) => {
  const theme = useTheme();
  const cell = { padding: 6, textAlign: 'left' as const, borderBottom: `1px solid ${theme.palette.divider}` };
  const head = { ...cell, borderBottom: `2px solid ${theme.palette.divider}`, position: 'sticky' as const, top: 0, background: theme.palette.background.paper };
  const percent = (value: number | null) => (value == null ? '—' : `${value > 0 ? '+' : ''}${value}%`);
  const headers = [comparison.align_by.replace(/_/g, ' '), `Baseline (${comparison.baseline})`, `Candidate (${comparison.candidate})`, 'Δ', '% Δ', 'Baseline samples', 'Candidate samples', 'Status'];
  // Rows with data on one side only cannot be compared; with a regression filter they would
  // bury the regressions (live: 5 regressions under 18 "missing" rows), so they fold away.
  const compared = comparison.rows.filter((row) => !row.missing);
  const oneSided = comparison.rows.filter((row) => row.missing);
  const [showOneSided, setShowOneSided] = useState(false);
  const shown = showOneSided ? [...compared, ...oneSided] : compared;
  return (
    <Box sx={{ mb: 1, flexShrink: 0 }}>
      <Typography variant="caption" color="text.secondary">{comparison.metric.replace(/_/g, ' ')}: {String(comparison.baseline)} vs {String(comparison.candidate)} — {compared.filter((row) => isRegression(comparison, row)).length} regression(s) in {compared.length} compared</Typography>
      <Box sx={{ overflow: 'auto', maxHeight: 280 }}>
        <table aria-label="comparison" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
          <thead><tr>{headers.map((header) => <th key={header} style={head}>{header}</th>)}</tr></thead>
          <tbody>{shown.map((row, index) => {
            const regression = isRegression(comparison, row);
            const rowStyle = regression ? { backgroundColor: alpha(theme.palette.error.main, 0.08) } : undefined;
            const deltaStyle = regression ? { ...cell, color: theme.palette.error.main, fontWeight: 600 } : cell;
            return <tr key={index} style={rowStyle} data-regression={regression || undefined}>
              <td style={cell}>{show(row[comparison.align_by])}</td>
              <td style={cell}>{show(row.baseline)}</td>
              <td style={cell}>{show(row.candidate)}</td>
              <td style={deltaStyle}>{show(row.delta)}</td>
              <td style={deltaStyle}>{percent(row.percent_delta)}</td>
              <td style={cell}>{show(row.baseline_samples)}</td>
              <td style={cell}>{show(row.candidate_samples)}</td>
              <td style={{ ...cell, color: row.missing || regression ? theme.palette.error.main : undefined }}>{missingLabel(row) || (regression ? 'Regression' : '')}</td>
            </tr>;
          })}</tbody>
        </table>
      </Box>
      {oneSided.length > 0 && (
        <Button size="small" onClick={() => setShowOneSided((value) => !value)} sx={{ textTransform: 'none', mt: 0.5 }}>
          {showOneSided ? 'Hide' : 'Show'} {oneSided.length} with data on one side only
        </Button>
      )}
    </Box>
  );
};

const Heatmap: React.FC<{ spec: AnalyticsVisualizationSpec }> = ({ spec }) => {
  const rows = spec.data?.rows || [];
  const x = spec.encoding?.x || '';
  const series = spec.encoding?.series || '';
  const y = spec.encoding?.y || '';
  const values = rows.map((row) => Number(row[y])).filter(Number.isFinite);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 1);
  return <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 1, p: 1 }}>
    {rows.map((row, index) => {
      const value = Number(row[y]);
      const strength = Number.isFinite(value) ? (value - min) / Math.max(max - min, 1) : 0;
      return <Box key={index} title={`${String(row[x])} / ${String(row[series])}: ${show(row[y])}`} sx={{ p: 1.5, borderRadius: 1, color: strength > 0.55 ? '#fff' : 'text.primary', bgcolor: `rgba(238,102,102,${0.12 + strength * 0.88})` }}>
        <Typography variant="caption" display="block">{String(row[x])}</Typography>
        {series && <Typography variant="caption" display="block">{String(row[series])}</Typography>}
        <Typography variant="subtitle2">{show(row[y])}</Typography>
      </Box>;
    })}
  </Box>;
};

/** Angled category labels are cut to this many characters (full value stays in the tooltip, table and exports). */
export const TICK_MAX_CHARS = 18;
/** XAxis height reserved for angled labels so they never run over the legend below. */
const TICK_AXIS_HEIGHT = 80;
export const truncateTick = (label: string, max = TICK_MAX_CHARS): string => (label.length > max ? `${label.slice(0, max - 1)}…` : label);

const Visualization: React.FC<{ spec: AnalyticsVisualizationSpec }> = ({ spec }) => {
  const { rows, seriesNames } = pivotRows(spec);
  const x = spec.encoding?.x || 'category';
  const y = spec.encoding?.y || 'value';
  const mark = spec.mark || 'table';
  const unit = spec.options?.units?.[y] ?? spec.options?.unit;
  const formatValue = (value: unknown) => formatAnalyticsValueWithUnit(value, unit);
  // Reserve the widest Y label (recharts clips tick text that does not fit the axis width).
  const yValues = rows.flatMap((row) => seriesNames.map((name) => row[name])).filter((v) => typeof v === 'number') as number[];
  const yExtremes = yValues.length ? [Math.min(...yValues, 0), Math.max(...yValues)] : [];
  const yAxisWidth = Math.min(160, Math.max(60, ...yExtremes.map((v) => formatValue(v).length * 7 + 16)));
  // Recharts silently drops category labels that overlap (live: a device bar had no name).
  const dense = rows.length > 6;
  if (mark === 'table') return <DataTable spec={spec} />;
  if (mark === 'heatmap' || mark === 'state-timeline') return <Heatmap spec={spec} />;
  if (mark === 'stat') {
    const first = spec.data?.rows?.[0] || {};
    const metrics = (spec.data?.fields || []).filter((field) => typeof first[field] === 'number');
    return <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, p: 2 }}>{metrics.map((metric) => <Card key={metric} variant="outlined"><CardContent><Typography variant="caption">{metric.replace(/_/g, ' ')}</Typography><Typography variant="h4">{show(first[metric])}</Typography></CardContent></Card>)}</Box>;
  }
  if (mark === 'pie') {
    return <ResponsiveContainer width="100%" height="100%"><PieChart><Tooltip formatter={formatValue} /><Legend /><Pie data={spec.data?.rows || []} dataKey={y} nameKey={x} outerRadius="72%" label>{(spec.data?.rows || []).map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}</Pie></PieChart></ResponsiveContainer>;
  }
  if (mark === 'radar') {
    return <ResponsiveContainer width="100%" height="100%"><RadarChart data={rows} outerRadius="68%"><PolarGrid /><PolarAngleAxis dataKey={x} tick={{ fontSize: 11 }} /><PolarRadiusAxis tick={{ fontSize: 10 }} tickFormatter={formatValue} /><Tooltip formatter={formatValue} /><Legend />{seriesNames.map((name, index) => <Radar key={name} name={name} dataKey={name} stroke={COLORS[index % COLORS.length]} fill={COLORS[index % COLORS.length]} fillOpacity={0.18} connectNulls={false} />)}</RadarChart></ResponsiveContainer>;
  }
  if (mark === 'scatter') {
    const seriesField = spec.encoding?.series;
    const groups = seriesField ? seriesNames : [y];
    return <ResponsiveContainer width="100%" height="100%"><ScatterChart><CartesianGrid /><XAxis dataKey={x} name={x} /><YAxis dataKey={y} name={y} width={yAxisWidth} tickFormatter={formatValue} /><ZAxis range={[50, 300]} /><Tooltip formatter={formatValue} /><Legend />{groups.map((name, index) => <Scatter key={name} name={name} data={(spec.data?.rows || []).filter((row) => !seriesField || String(row[seriesField]) === name)} fill={COLORS[index % COLORS.length]} />)}</ScatterChart></ResponsiveContainer>;
  }
  if (mark === 'line' || mark === 'area') {
    const Chart = mark === 'line' ? LineChart : AreaChart;
    return <ResponsiveContainer width="100%" height="100%"><Chart data={rows}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey={x} tickFormatter={show} /><YAxis width={yAxisWidth} tickFormatter={formatValue} /><Tooltip formatter={formatValue} labelFormatter={show} /><Legend />{seriesNames.map((name, index) => mark === 'line' ? <Line key={name} type="monotone" dataKey={name} stroke={COLORS[index % COLORS.length]} connectNulls={false} /> : <Area key={name} type="monotone" dataKey={name} stroke={COLORS[index % COLORS.length]} fill={COLORS[index % COLORS.length]} fillOpacity={0.2} connectNulls={false} />)}</Chart></ResponsiveContainer>;
  }
  return <ResponsiveContainer width="100%" height="100%"><BarChart data={rows} margin={dense ? { bottom: 8 } : undefined}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey={x} tickFormatter={dense ? (value: unknown) => truncateTick(show(value)) : show} interval={0} angle={dense ? -30 : 0} textAnchor={dense ? 'end' : 'middle'} height={dense ? TICK_AXIS_HEIGHT : 30} tick={{ fontSize: dense ? 11 : 12 }} /><YAxis width={yAxisWidth} tickFormatter={formatValue} /><Tooltip formatter={formatValue} labelFormatter={show} /><Legend />{seriesNames.map((name, index) => <Bar key={name} dataKey={name} stackId={mark === 'stacked-bar' ? 'stack' : undefined} fill={COLORS[index % COLORS.length]} />)}</BarChart></ResponsiveContainer>;
};

const DisclosureList: React.FC<{ notes: string[] }> = ({ notes }) => {
  if (!notes.length) return null;
  return <Box sx={{ mb: 1 }}>{notes.map((note) => <Typography key={note} variant="caption" color="warning.main" display="block">{note}</Typography>)}</Box>;
};

/** `chartHeight` fixes the chart height (canvas cells); without it the chart fills the remaining space. */
/** `hideScope`: the canvas already shows the scope note once for all panels. */
const Panel: React.FC<{ spec: AnalyticsVisualizationSpec; index: number; chartHeight?: number; hideScope?: boolean }> = ({ spec, index, chartHeight, hideScope }) => (
  !spec.data?.rows?.length && !spec.comparison?.rows?.length
    ? <Box data-analytics-panel={index} data-empty sx={{ p: 2 }}><Typography color="text.secondary">No data matched this question{spec.data?.source_id ? ` (${spec.data.source_id.replace(/_/g, ' ')})` : ''}.</Typography></Box>
    : <Box data-analytics-panel={index} sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
    <DisclosureList notes={artifactDisclosures(spec, !hideScope)} />
    {spec.comparison && spec.mark !== 'table'
      // The chart is the headline: beside the table when wide, on top when narrow (never below the fold).
      ? <Box sx={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: 2, alignItems: 'flex-start' }}>
        <Box data-analytics-chart sx={{ flex: '1 1 420px', minWidth: 0, height: chartHeight ?? 360 }}><Visualization spec={spec} /></Box>
        <Box sx={{ flex: '1 1 420px', minWidth: 0 }}><ComparisonTable comparison={spec.comparison} /></Box>
      </Box>
      : <>
        {spec.comparison && <ComparisonTable comparison={spec.comparison} />}
        {!(spec.comparison && spec.mark === 'table') && <Box sx={chartHeight ? { height: chartHeight } : { flex: 1, minHeight: 300 }}><Visualization spec={spec} /></Box>}
      </>}
  </Box>
);

const ExportToolbar: React.FC<{ spec: AnalyticsArtifactSpec; rootRef: React.RefObject<HTMLDivElement> }> = ({ spec, rootRef }) => {
  const theme = useTheme();
  const [chartCount, setChartCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const panels = artifactPanels(spec);
  const hasChartMark = panels.some((panel) => CHART_MARKS.includes(panel.mark));

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return undefined;
    const update = () => setChartCount(root.querySelectorAll(CHART_SVG_SELECTOR).length);
    update();
    const observer = new MutationObserver(update);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [rootRef, spec]);

  const panelSvg = (index: number) => rootRef.current?.querySelector<SVGSVGElement>(`[data-analytics-panel="${index}"] ${CHART_SVG_SELECTOR}`) ?? null;
  const chartFiles = () => panels.flatMap((panel, index) => {
    const svg = panelSvg(index);
    if (!svg) return [];
    const base = spec.kind === 'canvas' ? `${slugify(spec.title)}-${index + 1}-${slugify(panel.title)}` : slugify(spec.title);
    return [{ svg, base }];
  });
  const exportText = (extension: string, type: string, text: string) => downloadBlob(artifactFilename(spec.title, extension), new Blob([text], { type }));
  const exportSvg = () => chartFiles().forEach(({ svg, base }) => downloadBlob(`${base}.svg`, new Blob([serializeSvg(svg)], { type: 'image/svg+xml' })));
  const exportPng = async () => {
    setError(null);
    try {
      for (const { svg, base } of chartFiles()) {
        const { width, height } = svgSize(svg);
        downloadBlob(`${base}.png`, await svgToPngBlob(serializeSvg(svg), width, height, theme.palette.background.paper));
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'PNG export failed');
    }
  };
  const exportReport = () => {
    const svgs = panels.map((_, index) => {
      const svg = panelSvg(index);
      return svg ? serializeSvg(svg) : null;
    });
    exportText('html', 'text/html;charset=utf-8', buildReportHtml(spec, svgs));
  };

  const imageReason = chartCount ? '' : hasChartMark ? 'The chart has not rendered yet' : 'Table, stat and heatmap views have no chart image — use CSV, JSON or Report';
  const button = (label: string, title: string, onClick: () => void, disabled = false) => (
    <MuiTooltip key={label} title={title}><span><Button size="small" variant="text" disabled={disabled} onClick={onClick} sx={{ minWidth: 0, px: 1 }}>{label}</Button></span></MuiTooltip>
  );
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 0.5, flexWrap: 'wrap', mb: 1 }}>
      {error && <Typography variant="caption" color="error" sx={{ mr: 1 }}>{error}</Typography>}
      <Typography variant="caption" color="text.secondary" sx={{ mr: 0.5 }}>Export</Typography>
      {button('CSV', 'Download the data as CSV', () => exportText('csv', 'text/csv;charset=utf-8', artifactToCsv(spec)))}
      {button('JSON', 'Download the data as JSON', () => exportText('json', 'application/json', artifactToJson(spec)))}
      {button('SVG', imageReason || 'Download the chart as SVG', exportSvg, !chartCount)}
      {button('PNG', imageReason || 'Download the chart as PNG', () => { void exportPng(); }, !chartCount)}
      {button('Report', 'Download a static HTML report', exportReport)}
    </Box>
  );
};

const GrafanaLink: React.FC<{ link?: AnalyticsGrafanaLink }> = ({ link }) => {
  const url = safeGrafanaUrl(link);
  if (!link || !url) return null;
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 1, mb: 1 }}>
      <Link href={url} target="_blank" rel="noopener noreferrer" variant="body2">Open in Grafana</Link>
      <Typography variant="caption" color="text.secondary">{grafanaExpiryLabel(link)}</Typography>
    </Box>
  );
};

export const AnalyticsArtifactViewer: React.FC<Props> = ({ spec: supplied, chartType, chartData }) => {
  const rootRef = useRef<HTMLDivElement>(null);
  const spec = supplied || legacySpec(chartType, chartData);
  if (!spec) return <Typography color="text.secondary">No chart data to display.</Typography>;
  if (spec.kind === 'canvas') {
    return <Box ref={rootRef} sx={{ width: '100%', height: '100%', overflow: 'auto', p: 2 }}>
      <GrafanaLink link={spec.grafana} />
      <ExportToolbar spec={spec} rootRef={rootRef} />
      <DisclosureList notes={canvasScopeNotes(spec.panels)} />
      <Box sx={{ display: 'grid', gridTemplateColumns: `repeat(${spec.layout?.columns || 2}, minmax(0, 1fr))`, gap: 2 }}>
        {spec.panels.map((panel, index) => <Card key={index} variant="outlined" sx={{ minHeight: 360, minWidth: 0 }}><CardContent><Typography variant="subtitle1" sx={{ mb: 1 }}>{panel.title}</Typography><Panel spec={panel} index={index} chartHeight={300} hideScope /></CardContent></Card>)}
      </Box>
    </Box>;
  }
  return <Box ref={rootRef} sx={{ width: '100%', height: '100%', minHeight: 520, p: 2, display: 'flex', flexDirection: 'column', overflow: 'auto' }}>
    <ExportToolbar spec={spec} rootRef={rootRef} />
    <Box sx={{ flex: 1, minHeight: 400 }}><Panel spec={spec} index={0} /></Box>
  </Box>;
};
