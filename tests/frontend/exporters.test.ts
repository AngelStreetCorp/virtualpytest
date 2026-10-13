import { describe, expect, it } from 'vitest';

import {
  buildCsv,
  buildPrintHtml,
  escapeCsvCell,
  escapeHtml,
  fileStem,
} from '../../frontend/src/components/reports/exporters';

describe('escapeCsvCell', () => {
  it.each([
    ['=SUM(A1:A2)', `"'=SUM(A1:A2)"`],
    ['+1+1', `"'+1+1"`],
    ['-2+3', `"'-2+3"`],
    ['@cmd', `"'@cmd"`],
    ['\tlead tab', `"'\tlead tab"`],
    ['\rlead cr', `"'\rlead cr"`],
  ])('neutralises the formula prefix of %j', (input, expected) => {
    expect(escapeCsvCell(input)).toBe(expected);
  });

  it('quotes plain values and doubles embedded quotes', () => {
    expect(escapeCsvCell('plain')).toBe('"plain"');
    expect(escapeCsvCell('say "hi", ok')).toBe('"say ""hi"", ok"');
  });

  it('renders null and undefined as an empty quoted cell', () => {
    expect(escapeCsvCell(null)).toBe('""');
    expect(escapeCsvCell(undefined)).toBe('""');
  });

  it('keeps numbers and booleans as text (a negative number is still neutralised)', () => {
    expect(escapeCsvCell(42)).toBe('"42"');
    expect(escapeCsvCell(false)).toBe('"false"');
    expect(escapeCsvCell(-5)).toBe(`"'-5"`);
  });
});

describe('buildCsv', () => {
  it('joins the header and rows with CRLF and escapes every cell', () => {
    const csv = buildCsv(['Test', 'Status'], [
      ['=HYPERLINK("x")', 'failed'],
      ['ok', null],
    ]);
    expect(csv).toBe(`"Test","Status"\r\n"'=HYPERLINK(""x"")","failed"\r\n"ok",""`);
  });
});

describe('escapeHtml', () => {
  it('escapes markup characters', () => {
    expect(escapeHtml(`<img src=x onerror="alert('1')">&`)).toBe(
      '&lt;img src=x onerror=&quot;alert(&#39;1&#39;)&quot;&gt;&amp;',
    );
    expect(escapeHtml(null)).toBe('');
  });
});

describe('buildPrintHtml', () => {
  const doc = {
    title: '<script>alert(1)</script>Run',
    summary: [['Status', '<b>failed</b>']] as Array<[string, string]>,
    sections: [{ heading: 'Rows', headers: ['Test'], rows: [['<svg onload=alert(1)>']] }],
  };

  it('escapes the title, summary and cells and contains no script tag', () => {
    const html = buildPrintHtml(doc);
    expect(html).not.toMatch(/<script/i);
    expect(html).not.toContain('<svg onload');
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;Run');
    expect(html).toContain('&lt;b&gt;failed&lt;/b&gt;');
  });

  it('embeds only PNG data URLs as the chart image', () => {
    expect(buildPrintHtml({ ...doc, chartDataUrl: 'data:image/png;base64,AAAA' })).toContain(
      'src="data:image/png;base64,AAAA"',
    );
    const rejected = buildPrintHtml({ ...doc, chartDataUrl: 'javascript:alert(1)' });
    expect(rejected).not.toContain('javascript:');
    expect(rejected).not.toContain('<img');
  });
});

describe('fileStem', () => {
  it('reduces a title to a safe file name', () => {
    expect(fileStem('  Nightly run: 4/33 failed!  ')).toBe('Nightly_run_4_33_failed');
    expect(fileStem('***')).toBe('report');
  });
});
