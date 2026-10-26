/**
 * Report exporters: CSV, print-to-PDF and PNG chart, all built from the payload already
 * on screen so the three formats show the same counts as the page.
 *
 * Safety rules:
 *   - CSV: a cell starting with = + - @ TAB or CR is prefixed with `'` so a spreadsheet
 *     does not evaluate it as a formula; every cell is quoted RFC 4180 style.
 *   - Print: every interpolated value is HTML-escaped; the print document carries no
 *     scripts and is written into a detached window.
 */

export type CsvCell = string | number | boolean | null | undefined;

const FORMULA_PREFIX = /^[=+\-@\t\r]/;

/** Neutralise spreadsheet formulas, then quote. */
export const escapeCsvCell = (value: CsvCell): string => {
  if (value === null || value === undefined) return '""';
  let text = String(value);
  if (FORMULA_PREFIX.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
};

export const buildCsv = (headers: string[], rows: CsvCell[][]): string =>
  [headers, ...rows].map((row) => row.map(escapeCsvCell).join(',')).join('\r\n');

const HTML_ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

export const escapeHtml = (value: CsvCell): string =>
  value === null || value === undefined ? '' : String(value).replace(/[&<>"']/g, (ch) => HTML_ESCAPES[ch]);

export interface PrintSection {
  heading: string;
  headers: string[];
  rows: CsvCell[][];
}

export interface PrintDocument {
  title: string;
  /** key/value lines under the title (counts, window, generated time…). */
  summary: Array<[string, CsvCell]>;
  sections: PrintSection[];
  /** Optional chart image (data: URL from svgElementToPngDataUrl). */
  chartDataUrl?: string | null;
}

/** A self-contained, script-free HTML document for the browser's print / save-as-PDF. */
export const buildPrintHtml = (doc: PrintDocument): string => {
  const summary = doc.summary
    .map(([key, value]) => `<tr><th>${escapeHtml(key)}</th><td>${escapeHtml(value)}</td></tr>`)
    .join('');
  const sections = doc.sections
    .map(
      (section) =>
        `<h2>${escapeHtml(section.heading)}</h2><table><thead><tr>${section.headers
          .map((h) => `<th>${escapeHtml(h)}</th>`)
          .join('')}</tr></thead><tbody>${section.rows
          .map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`)
          .join('')}</tbody></table>`,
    )
    .join('');
  const chart =
    doc.chartDataUrl && doc.chartDataUrl.startsWith('data:image/png;base64,')
      ? `<img alt="chart" src="${escapeHtml(doc.chartDataUrl)}" style="max-width:100%"/>`
      : '';
  return [
    '<!doctype html><html><head><meta charset="utf-8"/>',
    `<title>${escapeHtml(doc.title)}</title>`,
    // ui-ok: no-literal-font-size - standalone exported HTML report, outside the app and its Size picker
    '<style>body{font:12px system-ui,sans-serif;margin:24px;color:#222}h1{font-size:18px}h2{font-size:14px;margin-top:20px}',
    'table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:4px 6px;text-align:left}th{background:#f3f3f3}</style>',
    `</head><body><h1>${escapeHtml(doc.title)}</h1><table>${summary}</table>${chart}${sections}</body></html>`,
  ].join('');
};

export const downloadBlob = (blob: Blob, filename: string): void => {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
};

export const downloadCsv = (filename: string, headers: string[], rows: CsvCell[][]): void =>
  downloadBlob(new Blob([buildCsv(headers, rows)], { type: 'text/csv;charset=utf-8' }), filename);

/** Open the print view in a new window and trigger print (the user saves it as PDF). */
export const openPrintView = (doc: PrintDocument): boolean => {
  const win = window.open('', '_blank');
  if (!win) return false;
  win.opener = null;
  win.document.open();
  win.document.write(buildPrintHtml(doc));
  win.document.close();
  win.focus();
  win.print();
  return true;
};

/** Serialise an SVG element (a rendered recharts chart) to a standalone SVG string. */
export const serializeSvg = (svg: SVGSVGElement): string => {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const rect = svg.getBoundingClientRect();
  const width = Math.max(1, Math.round(rect.width || Number(svg.getAttribute('width')) || 600));
  const height = Math.max(1, Math.round(rect.height || Number(svg.getAttribute('height')) || 300));
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('width', String(width));
  clone.setAttribute('height', String(height));
  return new XMLSerializer().serializeToString(clone);
};

/** Rasterise an SVG element to a PNG data URL on a white background. */
export const svgElementToPngDataUrl = (svg: SVGSVGElement, scale = 2): Promise<string> =>
  new Promise((resolve, reject) => {
    const markup = serializeSvg(svg);
    const width = Number(svg.getAttribute('width')) || Math.round(svg.getBoundingClientRect().width) || 600;
    const height = Number(svg.getAttribute('height')) || Math.round(svg.getBoundingClientRect().height) || 300;
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = width * scale;
      canvas.height = height * scale;
      const context = canvas.getContext('2d');
      if (!context) {
        reject(new Error('Canvas is not available'));
        return;
      }
      context.fillStyle = '#ffffff';
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.scale(scale, scale);
      context.drawImage(image, 0, 0, width, height);
      resolve(canvas.toDataURL('image/png'));
    };
    image.onerror = () => reject(new Error('Chart could not be rendered as an image'));
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
  });

/** The largest SVG inside the element marked `data-export-chart="<id>"`. */
export const findChartSvg = (root: ParentNode, exportId: string): SVGSVGElement | null => {
  const container = root.querySelector(`[data-export-chart="${CSS.escape(exportId)}"]`);
  if (!container) return null;
  const svgs = Array.from(container.querySelectorAll('svg')) as SVGSVGElement[];
  return svgs.sort(
    (a, b) =>
      b.getBoundingClientRect().width * b.getBoundingClientRect().height -
      a.getBoundingClientRect().width * a.getBoundingClientRect().height,
  )[0] ?? null;
};

export const downloadChartPng = async (exportId: string, filename: string): Promise<boolean> => {
  const svg = findChartSvg(document, exportId);
  if (!svg) return false;
  downloadBlob(dataUrlToBlob(await svgElementToPngDataUrl(svg)), filename);
  return true;
};

export const dataUrlToBlob = (dataUrl: string): Blob => {
  const [header, data] = dataUrl.split(',', 2);
  const mime = /data:([^;]+)/.exec(header)?.[1] ?? 'application/octet-stream';
  const binary = atob(data ?? '');
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
};

/** Safe file stem from a title. */
export const fileStem = (title: string): string =>
  title
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 80) || 'report';
