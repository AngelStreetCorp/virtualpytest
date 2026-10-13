/**
 * Pure export helpers for `vpt-artifact/v1` analytics artifacts (CSV, JSON, SVG, PNG, static HTML report).
 *
 * Everything here serialises data only: no spec value is ever evaluated, and the HTML report is
 * escaped, script-free and locked down by a CSP meta tag. Chart SVG embedded in the report is
 * sanitised first (see `sanitizeSvgMarkup`).
 */
import type {
  AnalyticsArtifactSpec,
  AnalyticsComparison,
  AnalyticsCanvasSpec,
  AnalyticsComparisonRow,
  AnalyticsVisualizationSpec,
  AnalyticsGrafanaLink,
} from './AnalyticsArtifactViewer';
import { getEnv } from '../../config/constants';
import { AGENT_CHAT_PALETTE_LIGHT } from '../../constants/agentChatTheme';
import { resolveGrafanaPath } from '../../utils/grafanaUrl';

export const COMPARISON_FIELDS = ['baseline', 'candidate', 'delta', 'percent_delta', 'baseline_samples', 'candidate_samples', 'missing'] as const;

export function artifactPanels(spec: AnalyticsArtifactSpec): AnalyticsVisualizationSpec[] {
  return spec.kind === 'canvas' ? spec.panels : [spec];
}

export function slugify(text: string): string {
  return text.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80) || 'analytics';
}

export function artifactFilename(title: string, extension: string): string {
  return `${slugify(title)}.${extension}`;
}

/** True when the comparison row is worse for the candidate, honouring `direction` and `regression_over_percent`. */
export function isRegression(comparison: AnalyticsComparison, row: AnalyticsComparisonRow): boolean {
  const signed = typeof row.percent_delta === 'number' ? row.percent_delta : typeof row.delta === 'number' ? row.delta : null;
  if (signed == null) return false;
  const worse = (comparison.direction ?? 'lower_is_better') === 'lower_is_better' ? signed : -signed;
  if (worse <= 0) return false;
  const threshold = comparison.regression_over_percent;
  return threshold == null || (typeof row.percent_delta === 'number' && worse > threshold);
}

export function missingLabel(row: AnalyticsComparisonRow): string {
  return row.missing ? `Missing in ${row.missing}` : '';
}

/** Human-readable notes about how the shown data differs from what was asked for. */
/** The link's absolute URL on the app's Grafana base (VITE_GRAFANA_URL); anything that is not a /grafana path is ignored. */
export function safeGrafanaUrl(link?: AnalyticsGrafanaLink, base: string | undefined = getEnv('VITE_GRAFANA_URL')): string | null {
  return resolveGrafanaPath(link?.path, base);
}

export function grafanaExpiryLabel(link: AnalyticsGrafanaLink): string {
  if (link.reused) return 'maintained dashboard';
  const date = link.expires_at ? new Date(link.expires_at) : null;
  return date && !Number.isNaN(date.getTime()) ? `draft · expires ${date.toLocaleString()}` : 'draft';
}

function grafanaHtml(spec: AnalyticsCanvasSpec): string[] {
  const url = safeGrafanaUrl(spec.grafana);
  if (!spec.grafana || !url) return [];
  const label = grafanaExpiryLabel(spec.grafana);
  return [`<p class="meta"><a href="${escapeHtml(url)}" rel="noopener noreferrer">Open in Grafana</a> (${escapeHtml(label)})</p>`];
}

/** `includeScope: false` leaves the scope note out (a canvas shows it once, not per panel). */
export function artifactDisclosures(spec: AnalyticsVisualizationSpec, includeScope = true): string[] {
  const notes: string[] = [];
  const fallback = spec.options?.fallback_applied;
  if (fallback) {
    notes.push(`Shown as ${fallback} instead of the requested chart: ${spec.options.fallback_reason || 'the requested chart is not readable for this data'}`);
  }
  if (includeScope && spec.options?.scope_note) notes.push(spec.options.scope_note);
  if (includeScope && spec.options?.defaulted_filters_note) notes.push(spec.options.defaulted_filters_note);
  const overflow = spec.options?.category_overflow;
  if (overflow) {
    notes.push(`Showing the ${overflow.kept} categories with the most ${overflow.ranked_by.replace(/_/g, ' ')}; ${overflow.omitted} omitted: ${overflow.omitted_categories.join(', ')}`);
  }
  if (spec.data?.truncated) notes.push(`Showing first ${spec.data.rows.length} rows`);
  return notes;
}

// ---------------------------------------------------------------------------------------------
// CSV
// ---------------------------------------------------------------------------------------------

const FORMULA_PREFIX = /^[=+\-@\t\r]/;
const NUMERIC_LITERAL = /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/;

/**
 * One RFC-4180 cell. Strings a spreadsheet would treat as a formula (leading `=`, `+`, `-`, `@`,
 * tab or CR) get a leading `'`. A string that is a plain numeric literal ("-5", "+1.5e3") is left
 * alone because no spreadsheet evaluates it as a formula; JS numbers are never altered.
 */
export function csvCell(value: unknown): string {
  if (value == null) return '';
  let text = typeof value === 'object' ? JSON.stringify(value) : String(value);
  if (typeof value === 'string' && FORMULA_PREFIX.test(text) && !NUMERIC_LITERAL.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function csvTable(fields: readonly string[], rows: Record<string, unknown>[]): string[] {
  return [fields.map(csvCell).join(','), ...rows.map((row) => fields.map((field) => csvCell(row[field])).join(','))];
}

export function comparisonFields(comparison: AnalyticsComparison): string[] {
  return [comparison.align_by, ...COMPARISON_FIELDS];
}

function panelCsvLines(panel: AnalyticsVisualizationSpec): string[] {
  if (panel.comparison) return csvTable(comparisonFields(panel.comparison), panel.comparison.rows);
  return csvTable(panel.data?.fields || [], panel.data?.rows || []);
}

/** CSV of the artifact: comparison rows when present, otherwise the data rows; a canvas gets one `# <title>` section per panel. */
export function artifactToCsv(spec: AnalyticsArtifactSpec): string {
  if (spec.kind !== 'canvas') return `${panelCsvLines(spec).join('\r\n')}\r\n`;
  const sections = spec.panels.map((panel) => [`# ${(panel.title || '').replace(/[\r\n]+/g, ' ')}`, ...panelCsvLines(panel)].join('\r\n'));
  return `${sections.join('\r\n\r\n')}\r\n`;
}

// ---------------------------------------------------------------------------------------------
// JSON
// ---------------------------------------------------------------------------------------------

function panelJson(panel: AnalyticsVisualizationSpec) {
  return {
    title: panel.title, kind: panel.kind, mark: panel.mark, data: panel.data,
    comparison: panel.comparison ?? null, provenance: panel.provenance ?? null,
  };
}

export function artifactToJson(spec: AnalyticsArtifactSpec): string {
  const body = spec.kind === 'canvas'
    ? { schema: spec.schema, title: spec.title, kind: spec.kind, layout: spec.layout, panels: spec.panels.map(panelJson), provenance: spec.provenance ?? null }
    : { schema: spec.schema, ...panelJson(spec) };
  return JSON.stringify(body, null, 2);
}

// ---------------------------------------------------------------------------------------------
// SVG / PNG
// ---------------------------------------------------------------------------------------------

export function svgSize(svg: SVGSVGElement): { width: number; height: number } {
  const box = svg.getBoundingClientRect();
  const width = Math.round(box.width) || Number(svg.getAttribute('width')) || 800;
  const height = Math.round(box.height) || Number(svg.getAttribute('height')) || 400;
  return { width, height };
}

/** Standalone SVG document string for a rendered chart surface. */
export function serializeSvg(svg: SVGSVGElement): string {
  const { width, height } = svgSize(svg);
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');
  clone.setAttribute('width', String(width));
  clone.setAttribute('height', String(height));
  if (!clone.getAttribute('viewBox')) clone.setAttribute('viewBox', `0 0 ${width} ${height}`);
  return new XMLSerializer().serializeToString(clone);
}

/** Rasterise an SVG string to PNG via Image + canvas (browser only). */
export function svgToPngBlob(svgString: string, width: number, height: number, background?: string): Promise<Blob> {
  return new Promise((resolve, reject) => {
    if (typeof document === 'undefined' || typeof Image === 'undefined') {
      reject(new Error('PNG export needs a browser'));
      return;
    }
    const canvas = document.createElement('canvas');
    let context: CanvasRenderingContext2D | null = null;
    try {
      context = canvas.getContext('2d');
    } catch {
      context = null;
    }
    if (!context || typeof canvas.toBlob !== 'function') {
      reject(new Error('Canvas is not available for PNG export'));
      return;
    }
    const scale = typeof window !== 'undefined' && window.devicePixelRatio > 1 ? 2 : 1;
    canvas.width = width * scale;
    canvas.height = height * scale;
    const ctx = context;
    const image = new Image();
    image.onload = () => {
      ctx.scale(scale, scale);
      if (background) {
        ctx.fillStyle = background;
        ctx.fillRect(0, 0, width, height);
      }
      ctx.drawImage(image, 0, 0, width, height);
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('PNG encoding failed'))), 'image/png');
    };
    image.onerror = () => reject(new Error('Could not rasterise the chart SVG'));
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgString)}`;
  });
}

// ---------------------------------------------------------------------------------------------
// Sanitised SVG + static HTML report
// ---------------------------------------------------------------------------------------------

const FORBIDDEN_SVG_ELEMENTS = ['script', 'foreignObject', 'iframe', 'embed', 'object', 'set', 'animate', 'animateMotion', 'animateTransform', 'handler', 'listener'];

/**
 * Strip active content from SVG markup: script/foreignObject/embedding/animation elements, every
 * `on*` attribute, and any href that is not a same-document `#fragment` (which covers `javascript:`).
 * Returns '' for markup that does not parse as SVG.
 */
export function sanitizeSvgMarkup(markup: string): string {
  const doc = new DOMParser().parseFromString(markup, 'image/svg+xml');
  const root = doc.documentElement;
  if (!root || root.localName !== 'svg' || doc.getElementsByTagName('parsererror').length) return '';
  FORBIDDEN_SVG_ELEMENTS.forEach((name) => Array.from(root.getElementsByTagName(name)).forEach((node) => node.remove()));
  [root, ...Array.from(root.getElementsByTagName('*'))].forEach((element) => {
    Array.from(element.attributes).forEach((attribute) => {
      const name = attribute.name.toLowerCase();
      // Browsers ignore whitespace/control characters inside a URL scheme ("java\tscript:"), so compare without them.
      const value = Array.from(attribute.value).filter((ch) => ch.charCodeAt(0) > 0x20).join('').toLowerCase();
      if (name.startsWith('on') || ((name === 'href' || name.endsWith(':href')) && !value.startsWith('#')) || value.includes('javascript:')) {
        element.removeAttribute(attribute.name);
      }
    });
  });
  return new XMLSerializer().serializeToString(root);
}

export function escapeHtml(value: unknown): string {
  return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export const REPORT_CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'";

// The exported HTML is printed / opened standalone: light palette, the app's own colours.
const L = AGENT_CHAT_PALETTE_LIGHT;
const REPORT_STYLE = [
  `body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:${L.textPrimary};background:${L.surface}}`,
  'h1{font-size:1.4rem;margin:0 0 4px}h2{font-size:1.1rem;margin:24px 0 8px}',
  `.meta{color:${L.textSecondary};font-size:.85rem}dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;font-size:.85rem}dt{color:${L.textSecondary}}`,
  `.disclosure{background:${L.warning}1a;border-left:3px solid ${L.warning};padding:4px 8px;font-size:.85rem;margin:4px 0}`,
  'figure{margin:8px 0;overflow:auto}table{border-collapse:collapse;font-size:.8rem;margin:8px 0}',
  `th,td{border-bottom:1px solid ${L.borderColor};padding:4px 8px;text-align:left}th{border-bottom-width:2px}`,
  `tr.regression td{color:${L.error};font-weight:600}`,
].join('');

const cellText = (value: unknown) => (value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value));

function htmlTable(fields: readonly string[], rows: Record<string, unknown>[], rowClass?: (row: Record<string, unknown>) => string): string {
  const head = fields.map((field) => `<th>${escapeHtml(field.replace(/_/g, ' '))}</th>`).join('');
  const body = rows.map((row) => {
    const cls = rowClass?.(row);
    return `<tr${cls ? ` class="${escapeHtml(cls)}"` : ''}>${fields.map((field) => `<td>${escapeHtml(cellText(row[field]))}</td>`).join('')}</tr>`;
  }).join('');
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function provenanceHtml(spec: AnalyticsArtifactSpec): string {
  const source = spec.provenance?.source_id ?? (spec.kind === 'visualization' ? spec.data?.source_id : undefined);
  const items: [string, unknown][] = [
    ['Source', source], ['Preset', spec.provenance?.preset ?? spec.preset], ['Dashboard', spec.provenance?.dashboard_ref],
  ];
  const shown = items.filter(([, value]) => value != null && value !== '');
  return shown.length ? `<dl>${shown.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join('')}</dl>` : '';
}

function panelHtml(panel: AnalyticsVisualizationSpec, svgMarkup: string | null | undefined, heading: boolean): string {
  // In a canvas the scope note is printed once at the top of the report, not in every panel.
  const parts: string[] = [];
  if (heading) parts.push(`<h2>${escapeHtml(panel.title)}</h2>`, provenanceHtml(panel));
  artifactDisclosures(panel, !heading).forEach((note) => parts.push(`<p class="disclosure">${escapeHtml(note)}</p>`));
  const svg = svgMarkup ? sanitizeSvgMarkup(svgMarkup) : '';
  if (svg) parts.push(`<figure>${svg}</figure>`);
  const comparison = panel.comparison;
  if (comparison) {
    parts.push(`<p class="meta">${escapeHtml(`${comparison.metric}: ${comparison.baseline} (baseline) vs ${comparison.candidate} (candidate)`)}</p>`);
    parts.push(htmlTable(comparisonFields(comparison), comparison.rows as Record<string, unknown>[],
      (row) => (isRegression(comparison, row as AnalyticsComparisonRow) ? 'regression' : '')));
  }
  parts.push(htmlTable(panel.data?.fields || [], panel.data?.rows || []));
  return `<section>${parts.join('')}</section>`;
}

/** Distinct scope and defaulted-filter notes of a canvas's panels, in first-seen order. */
export function canvasScopeNotes(panels: AnalyticsVisualizationSpec[]): string[] {
  return Array.from(new Set(panels.flatMap((panel) => [panel.options?.scope_note, panel.options?.defaulted_filters_note])
    .filter((note): note is string => !!note)));
}

/**
 * Self-contained static HTML report. `svgMarkupByPanel[i]` is the serialised chart for panel i
 * (index 0 for a single visualization); it is sanitised before embedding.
 */
export function buildReportHtml(spec: AnalyticsArtifactSpec, svgMarkupByPanel: (string | null | undefined)[] = [], generatedAt: Date = new Date()): string {
  const panels = artifactPanels(spec);
  const body = panels.map((panel, index) => panelHtml(panel, svgMarkupByPanel[index], spec.kind === 'canvas')).join('');
  return [
    '<!doctype html><html lang="en"><head><meta charset="utf-8">',
    `<meta http-equiv="Content-Security-Policy" content="${REPORT_CSP}">`,
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    `<title>${escapeHtml(spec.title || 'Analytics report')}</title><style>${REPORT_STYLE}</style></head><body>`,
    `<h1>${escapeHtml(spec.title || 'Analytics report')}</h1>`,
    `<p class="meta">Generated ${escapeHtml(generatedAt.toISOString())}</p>`,
    ...(spec.kind === 'canvas' ? grafanaHtml(spec) : []),
    provenanceHtml(spec),
    ...(spec.kind === 'canvas' ? canvasScopeNotes(spec.panels).map((note) => `<p class="disclosure">${escapeHtml(note)}</p>`) : []),
    body,
    '</body></html>',
  ].join('');
}

export function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
