import type {
  AnalyticsCanvasSpec,
  AnalyticsComparison,
  AnalyticsVisualizationSpec,
} from '../../frontend/src/components/agent-chat/AnalyticsArtifactViewer';
import {
  artifactDisclosures,
  artifactFilename,
  artifactToCsv,
  artifactToJson,
  buildReportHtml,
  csvCell,
  isRegression,
  REPORT_CSP,
  sanitizeSvgMarkup,
  serializeSvg,
  svgToPngBlob,
} from '../../frontend/src/components/agent-chat/analyticsExport';

function viz(overrides: Partial<AnalyticsVisualizationSpec> = {}): AnalyticsVisualizationSpec {
  const rows = overrides.data?.rows ?? [{ device: 'stb-1', pass_rate: 97.5 }, { device: 'stb-2', pass_rate: null }];
  return {
    schema: 'vpt-artifact/v1', kind: 'visualization', title: 'Pass rate', mark: 'bar',
    data: { model: 'analytics-tabular-v1', source_id: 'script_results', fields: ['device', 'pass_rate'], rows, row_count: rows.length, truncated: false },
    encoding: { x: 'device', y: 'pass_rate', series: null, tooltip: ['pass_rate'] },
    options: { legend: false, missing: 'gap', max_categories: 40, max_series: 12, fallback_applied: null, unit: '%' },
    ...overrides,
  };
}

const comparison: AnalyticsComparison = {
  model: 'analytics-comparison-v1', align_by: 'kpi_name', series_field: 'variant', metric: 'avg_ms',
  baseline: 'v1', candidate: 'v2', sample_metric: 'sample_count', direction: 'lower_is_better',
  rows: [
    { kpi_name: 'Home', baseline: 100, candidate: 120, delta: 20, percent_delta: 20, baseline_samples: 5, candidate_samples: 6, missing: null },
    { kpi_name: 'Guide', baseline: 100, candidate: 90, delta: -10, percent_delta: -10, baseline_samples: 4, candidate_samples: 4, missing: null },
    { kpi_name: 'VOD', baseline: null, candidate: 80, delta: null, percent_delta: null, baseline_samples: 0, candidate_samples: 3, missing: 'baseline' },
  ],
};

describe('csvCell', () => {
  it('quotes per RFC 4180', () => {
    expect(csvCell('a,b')).toBe('"a,b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell('line1\nline2')).toBe('"line1\nline2"');
    expect(csvCell(null)).toBe('');
    expect(csvCell(undefined)).toBe('');
    expect(csvCell('plain')).toBe('plain');
  });

  it('neutralises formula injection but never alters numbers or plain numeric strings', () => {
    expect(csvCell('=1+1')).toBe("'=1+1");
    expect(csvCell('+cmd')).toBe("'+cmd");
    expect(csvCell('@SUM(A1)')).toBe("'@SUM(A1)");
    expect(csvCell('-2+3')).toBe("'-2+3");
    expect(csvCell('\tx')).toBe("'\tx");
    expect(csvCell('\rx')).toBe("\"'\rx\"");
    expect(csvCell('=HYPERLINK("http://x","y")')).toBe('"\'=HYPERLINK(""http://x"",""y"")"');
    expect(csvCell(-5)).toBe('-5');
    expect(csvCell(-0.25)).toBe('-0.25');
    // Decision: a string that is a plain numeric literal is not a formula, so it is kept as-is.
    expect(csvCell('-5')).toBe('-5');
    expect(csvCell('+1.5e3')).toBe('+1.5e3');
  });
});

describe('artifactToCsv', () => {
  it('exports data rows with CRLF line endings and empty missing values', () => {
    expect(artifactToCsv(viz())).toBe('device,pass_rate\r\nstb-1,97.5\r\nstb-2,\r\n');
  });

  it('exports comparison rows when present', () => {
    const csv = artifactToCsv(viz({ comparison }));
    const lines = csv.trim().split('\r\n');
    expect(lines[0]).toBe('kpi_name,baseline,candidate,delta,percent_delta,baseline_samples,candidate_samples,missing');
    expect(lines[1]).toBe('Home,100,120,20,20,5,6,');
    expect(lines[2]).toBe('Guide,100,90,-10,-10,4,4,');
    expect(lines[3]).toBe('VOD,,80,,,0,3,baseline');
  });

  it('writes one titled section per canvas panel', () => {
    const canvas: AnalyticsCanvasSpec = {
      schema: 'vpt-artifact/v1', kind: 'canvas', title: 'Overview', layout: { columns: 2 },
      panels: [viz({ title: 'Pass rate' }), viz({ title: 'Duration\ntrend' })],
    };
    const csv = artifactToCsv(canvas);
    const sections = csv.trim().split('\r\n\r\n');
    expect(sections).toHaveLength(2);
    expect(sections[0].startsWith('# Pass rate\r\ndevice,pass_rate')).toBe(true);
    expect(sections[1].startsWith('# Duration trend\r\n')).toBe(true);
  });
});

describe('artifactToJson', () => {
  it('serialises data only for a visualization', () => {
    const parsed = JSON.parse(artifactToJson(viz({ comparison, provenance: { source_id: 'kpi', preset: 'kpi_radar' } })));
    expect(Object.keys(parsed).sort()).toEqual(['comparison', 'data', 'kind', 'mark', 'provenance', 'schema', 'title']);
    expect(parsed.schema).toBe('vpt-artifact/v1');
    expect(parsed.mark).toBe('bar');
    expect(parsed.data.rows[1].pass_rate).toBeNull();
    expect(parsed.comparison.rows).toHaveLength(3);
  });

  it('serialises panels for a canvas', () => {
    const canvas: AnalyticsCanvasSpec = { schema: 'vpt-artifact/v1', kind: 'canvas', title: 'Overview', layout: { columns: 1 }, panels: [viz()] };
    const parsed = JSON.parse(artifactToJson(canvas));
    expect(parsed.kind).toBe('canvas');
    expect(parsed.panels).toHaveLength(1);
    expect(parsed.panels[0].data.fields).toEqual(['device', 'pass_rate']);
    expect(parsed.panels[0].comparison).toBeNull();
  });
});

describe('disclosures and regressions', () => {
  it('reports fallback and truncation', () => {
    const spec = viz({ options: { ...viz().options, fallback_applied: 'bar', fallback_reason: 'radar needs 3-20 categories' } });
    spec.data.truncated = true;
    expect(artifactDisclosures(spec)).toEqual(['Shown as bar instead of the requested chart: radar needs 3-20 categories', 'Showing first 2 rows']);
  });

  it('reports a radar top-N reduction with the omitted categories', () => {
    const spec = viz({ options: { ...viz().options, category_overflow: { kept: 20, omitted: 2, ranked_by: 'sample_count', omitted_categories: ['Guide', 'Zap'] } } });
    expect(artifactDisclosures(spec)).toEqual(['Showing the 20 categories with the most sample count; 2 omitted: Guide, Zap']);
  });

  it('respects direction and threshold', () => {
    expect(isRegression(comparison, comparison.rows[0])).toBe(true);
    expect(isRegression(comparison, comparison.rows[1])).toBe(false);
    expect(isRegression(comparison, comparison.rows[2])).toBe(false);
    const higher = { ...comparison, direction: 'higher_is_better' as const };
    expect(isRegression(higher, comparison.rows[0])).toBe(false);
    expect(isRegression(higher, comparison.rows[1])).toBe(true);
    expect(isRegression({ ...comparison, regression_over_percent: 25 }, comparison.rows[0])).toBe(false);
  });

  it('builds filenames from the title slug', () => {
    expect(artifactFilename('KPI: v1 vs v2 / stb_tv', 'csv')).toBe('kpi-v1-vs-v2-stb-tv.csv');
    expect(artifactFilename('', 'json')).toBe('analytics.json');
  });
});

describe('sanitizeSvgMarkup', () => {
  it('strips script, on* handlers, javascript: hrefs and foreignObject', () => {
    const dirty = '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" onload="alert(1)">'
      + '<script>alert(2)</script><foreignObject><div>x</div></foreignObject>'
      + '<a href="javascript:alert(3)"><text>link</text></a><a xlink:href=" java\tscript:alert(4)"><text>l2</text></a>'
      + '<set attributeName="href" to="javascript:alert(5)"/>'
      + '<rect onclick="alert(6)" width="10" height="10" fill="#5470c6"/><use href="#ok"/></svg>';
    const clean = sanitizeSvgMarkup(dirty);
    expect(clean).not.toMatch(/script/i);
    expect(clean).not.toMatch(/onload|onclick/i);
    expect(clean).not.toMatch(/foreignObject/);
    expect(clean).not.toMatch(/<set/);
    expect(clean).toContain('<rect');
    expect(clean).toContain('fill="#5470c6"');
    expect(clean).toContain('href="#ok"');
    expect(clean).toContain('link');
  });

  it('rejects markup that is not SVG', () => {
    expect(sanitizeSvgMarkup('<html><script>x</script></html>')).toBe('');
    expect(sanitizeSvgMarkup('<svg><unclosed></svg>')).toBe('');
  });
});

describe('buildReportHtml', () => {
  it('escapes every value, has a CSP and no script', () => {
    const spec = viz({
      title: 'Report <b>bold</b>',
      data: { model: 'analytics-tabular-v1', source_id: 'x', fields: ['device', 'pass_rate'], rows: [{ device: '<img src=x onerror=alert(1)>', pass_rate: 1 }], row_count: 1, truncated: true },
      provenance: { source_id: 'script_results', preset: 'pass"rate', dashboard_ref: 'script-results.json' },
      comparison,
    });
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><script>alert(1)</script><rect width="10" height="10" onmouseover="x()"/></svg>';
    const html = buildReportHtml(spec, [svg], new Date('2026-10-03T10:00:00Z'));
    expect(html).toContain(`<meta http-equiv="Content-Security-Policy" content="${REPORT_CSP}">`);
    expect(REPORT_CSP).toBe("default-src 'none'; img-src data:; style-src 'unsafe-inline'");
    expect(html).not.toMatch(/<script/i);
    expect(html).not.toMatch(/onmouseover/i);
    expect(html).not.toContain('<img');
    expect(html).toContain('&lt;img src=x onerror=alert(1)&gt;');
    expect(html).toContain('<title>Report &lt;b&gt;bold&lt;/b&gt;</title>');
    expect(html).toContain('Generated 2026-10-03T10:00:00.000Z');
    expect(html).toContain('script_results');
    expect(html).toContain('pass&quot;rate');
    expect(html).toContain('script-results.json');
    expect(html).toContain('Showing first 1 rows');
    expect(html).toContain('<figure><svg');
    expect(html).toContain('<tr class="regression">');
    expect(html).toContain('<td>—</td>');
  });

  it('renders one section per canvas panel', () => {
    const canvas: AnalyticsCanvasSpec = {
      schema: 'vpt-artifact/v1', kind: 'canvas', title: 'Overview', layout: { columns: 2 },
      panels: [viz({ title: 'A' }), viz({ title: 'B', mark: 'table' })],
    };
    const html = buildReportHtml(canvas, ['<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>', null]);
    expect(html.match(/<section>/g)).toHaveLength(2);
    expect(html.match(/<figure>/g)).toHaveLength(1);
    expect(html).toContain('<h2>A</h2>');
    expect(html).toContain('<h2>B</h2>');
  });
});

describe('serializeSvg / svgToPngBlob', () => {
  it('produces a standalone SVG with namespace and size', () => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', '320');
    svg.setAttribute('height', '200');
    svg.appendChild(document.createElementNS('http://www.w3.org/2000/svg', 'rect'));
    const out = serializeSvg(svg);
    expect(out).toContain('xmlns="http://www.w3.org/2000/svg"');
    expect(out).toContain('width="320"');
    expect(out).toContain('height="200"');
    expect(out).toContain('viewBox="0 0 320 200"');
  });

  it('rejects cleanly when canvas is unavailable', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    await expect(svgToPngBlob('<svg xmlns="http://www.w3.org/2000/svg"/>', 10, 10)).rejects.toThrow('Canvas is not available');
  });
});

describe('buildReportHtml Grafana link', () => {
  const panel = viz({ title: 'P' });
  const canvas = (grafana: AnalyticsCanvasSpec['grafana']): AnalyticsCanvasSpec => ({
    schema: 'vpt-artifact/v1', kind: 'canvas', title: 'C', layout: { columns: 2 }, panels: [panel, panel], grafana,
  });

  it('includes the escaped link and expiry for a canvas with a draft', () => {
    (window as any).__VPT_CONFIG__ = { VITE_GRAFANA_URL: 'https://g.test/grafana' };
    const html = buildReportHtml(canvas({ path: '/grafana/d/atlas-draft-1?var-workspace=a&b', uid: 'u', expires_at: '2026-10-06T12:00:00+00:00', reused: false }));
    expect(html).toContain('<a href="https://g.test/grafana/d/atlas-draft-1?var-workspace=a&amp;b" rel="noopener noreferrer">Open in Grafana</a>');
    expect(html).toContain('draft · expires');
    delete (window as any).__VPT_CONFIG__;
  });

  it('omits it when absent or not an http(s)/grafana link', () => {
    expect(buildReportHtml(canvas(undefined))).not.toContain('Open in Grafana');
    expect(buildReportHtml(canvas({ path: 'javascript:alert(1)', uid: 'u', expires_at: null, reused: false }))).not.toContain('Open in Grafana');
  });
});
