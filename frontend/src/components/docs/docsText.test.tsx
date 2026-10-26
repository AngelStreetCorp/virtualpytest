// @vitest-environment jsdom
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';

import { DOCS_ITEMS } from '../../config/navItems';
import DocsNav, { buildRailRows, flattenSection } from './DocsNav';
import { docsMeasure } from './docsLayout';
import { DEFAULT_READER_SIZE, readReaderSize } from './docsPrefs';
import { docsTypeScale } from './docsTypeScale';
import { extractH2Headings } from './docsPageOptions';
import { normalizeManifest, type DocsManifest } from './docsManifest';
import { hasEmoji, stripEmoji, stripEmojiNode } from './docsText';

describe('no emoji in docs chrome and outline', () => {
  it('strips leading and inner emoji, variation selectors and keycaps, keeps text and (c)(R)(TM)', () => {
    expect(stripEmoji('🚀 Get Started')).toBe('Get Started');
    expect(stripEmoji('📖️ Main Sections')).toBe('Main Sections');
    expect(stripEmoji('1️⃣ First step ✅')).toBe('First step');
    expect(stripEmoji('👨‍👩‍👧 Family')).toBe('Family');
    expect(stripEmoji('Acme™ © 2026 ®')).toBe('Acme™ © 2026 ®');
    expect(hasEmoji('plain text')).toBe(false);
  });
  it('strips text nodes of a React tree', () => {
    const out = stripEmojiNode(['🚀 ', 'Get ', 'Started']);
    expect(Array.isArray(out) ? out.join('') : out).toBe('Get Started');
  });
  it('keeps the heading id but gives the On this page panel plain labels', () => {
    const h = extractH2Headings('# T\n\n## 🚀 Get Started\n\n## 📖 Main Sections');
    expect(h.map((x) => x.label)).toEqual(['Get Started', 'Main Sections']);
    expect(h.every((x) => !hasEmoji(x.label))).toBe(true);
    expect(h[0].id).toBe('-get-started'); // GitHub-compatible slug of the raw heading, equal to the rendered id
  });
  it('the search index script writes no emoji', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'docs-idx-'));
    fs.mkdirSync(path.join(dir, 'get-started'));
    fs.writeFileSync(path.join(dir, 'docs-manifest.json'), JSON.stringify({ docs: [{ title: 'Get Started', path: '/docs/get-started', section: 'get-started' }] }));
    fs.writeFileSync(path.join(dir, 'get-started', 'README.md'), '# 🚀 Get Started\n\n## 📖 Main Sections\n\nBody ✅ text.\n');
    execFileSync('node', [path.resolve(__dirname, '../../../scripts/gen-docs-search-index.mjs'), dir]);
    const idx = JSON.parse(fs.readFileSync(path.join(dir, 'docs-search-index.json'), 'utf8'));
    const e = idx.pages[0];
    expect([e.t, ...e.h, e.b].some(hasEmoji)).toBe(false);
    expect(e.t).toBe('Get Started');
    expect(e.h).toEqual(['Main Sections']);
  });
});

const manifest: DocsManifest = {
  docs: [
    { title: 'Documentation Home', path: '/docs/README', section: 'root' },
    { title: 'Getting Started', path: '/docs/get-started', section: 'get-started', children: [{ title: '🚀 Overview', path: '/docs/get-started' }, { title: 'Docker', path: '/docs/get-started/docker' }] },
    { title: 'Technical Docs', path: '/docs/technical', section: 'technical', children: [
      { title: 'Overview', path: '/docs/technical' },
      { title: 'AI', children: [{ title: 'Providers', path: '/docs/technical/ai/providers' }, { title: 'Deep', children: [{ title: 'Nested', path: '/docs/technical/ai/deep/nested' }] }] },
    ] },
    { title: 'MCP Tools', path: '/docs/mcp', section: 'mcp', children: [{ title: 'Overview', path: '/docs/mcp' }, { title: 'Tools', path: '/docs/mcp/tools' }] },
    { title: 'Bugs', path: '/docs/bugs', section: 'bugs', children: [{ title: 'Overview', path: '/docs/bugs' }] },
  ],
};

describe('docs left rail follows the navbar Docs menu', () => {
  const m = normalizeManifest(manifest);
  it('uses DOCS_ITEMS order, labels and icon elements, extras last', () => {
    const rows = buildRailRows(m);
    const menu = DOCS_ITEMS.filter((i) => i.path?.startsWith('/docs'));
    expect(rows.slice(0, menu.length).map((r) => r.label)).toEqual(menu.map((i) => i.label));
    rows.slice(0, menu.length).forEach((r, i) => expect(r.icon).toBe(menu[i].icon));
    expect(rows[rows.length - 1].label).toBe('MCP Tools');
    expect(menu[0].label).toBe('Home');
    expect(menu[1].label).toBe('Get Started');
  });
  it('normalizes manifest titles to the menu labels', () => {
    expect(m.docs[0].title).toBe('Home');
    expect(m.docs[1].title).toBe('Get Started');
    expect(m.docs[1].children?.[0].title).toBe('Overview');
  });
  it('flattens to two levels: groups are labels, never folders', () => {
    const e = flattenSection(m.docs[2].children);
    expect(e.map((x) => `${x.kind}:${x.title}`)).toEqual(['page:Overview', 'group:AI', 'page:Providers', 'group:Deep', 'page:Nested']);
  });
  it('renders no emoji and only the current section open', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter><DocsNav manifest={manifest} currentPath="/docs/get-started/docker" /></MemoryRouter>,
    );
    expect(hasEmoji(html.replace(/<[^>]*>/g, ' '))).toBe(false);
    expect(html).toContain('>Docker<');
    expect(html).not.toContain('>Providers<'); // Technical stays collapsed
  });
});

describe('reader type scale', () => {
  it('derives from the app scale and multiplies', () => {
    const base = docsTypeScale();
    expect(base.h1).toBe('1.5rem');
    expect(base.body).toBe('0.875rem');
    expect(docsTypeScale(false, 1.15).h1).toBe('1.725rem');
    expect(docsTypeScale(true, 1).body).toBe('0.7875rem');
  });
});

describe('reading measure', () => {
  it('is one rem width of about 100 characters of body text and follows the reader size', () => {
    expect(docsMeasure(0.875)).toBe('48.13rem');
    expect(parseFloat(docsMeasure(parseFloat(docsTypeScale(false, 1.15).body)))).toBeGreaterThan(parseFloat(docsMeasure(0.875)));
  });
});

describe('reader size default', () => {
  it('is S without a stored choice, and a stored choice wins', () => {
    localStorage.removeItem('virtualpytest:docs:readerSize');
    expect(DEFAULT_READER_SIZE).toBe('s');
    expect(readReaderSize()).toBe('s');
    localStorage.setItem('virtualpytest:docs:readerSize', 'l');
    expect(readReaderSize()).toBe('l');
    localStorage.removeItem('virtualpytest:docs:readerSize');
  });
});
