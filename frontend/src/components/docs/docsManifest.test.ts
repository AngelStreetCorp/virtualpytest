// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { breadcrumbFor, flattenPages, neighbours, type DocsManifest } from './docsManifest';
import { highlightParts, searchDocs, type SearchEntry } from './docsSearchIndex';

const manifest: DocsManifest = {
  docs: [
    { title: 'Home', path: '/docs/README', section: 'root' },
    {
      title: 'Get Started',
      path: '/docs/get-started',
      section: 'get-started',
      children: [
        { title: 'Overview', path: '/docs/get-started' },
        { title: 'Docker', path: '/docs/get-started/docker' },
      ],
    },
    {
      title: 'Technical Docs',
      path: '/docs/technical',
      section: 'technical',
      children: [{ title: 'AI', children: [{ title: 'Providers', path: '/docs/technical/ai/providers' }] }],
    },
    { title: 'Bugs', path: '/docs/bugs', section: 'bugs', children: [{ title: 'Overview', path: '/docs/bugs' }] },
  ],
};

describe('docs manifest helpers', () => {
  it('flattens in reading order without duplicates', () => {
    expect(flattenPages(manifest).map((p) => p.path)).toEqual([
      '/docs/README',
      '/docs/get-started',
      '/docs/get-started/docker',
      '/docs/technical/ai/providers',
      '/docs/bugs',
    ]);
  });
  it('finds neighbours across sections', () => {
    const n = neighbours(manifest, '/docs/get-started/docker');
    expect(n.prev?.path).toBe('/docs/get-started');
    expect(n.next?.path).toBe('/docs/technical/ai/providers');
    expect(neighbours(manifest, '/docs/bugs/BUG-0001')).toEqual({ prev: null, next: null });
  });
  it('builds breadcrumbs', () => {
    expect(breadcrumbFor(manifest, '/docs/get-started').map((c) => c.title)).toEqual(['Get Started']);
    expect(breadcrumbFor(manifest, '/docs/get-started/docker').map((c) => c.title)).toEqual(['Get Started', 'Docker']);
    expect(breadcrumbFor(manifest, '/docs/technical/ai/providers').map((c) => c.title)).toEqual(['Technical Docs', 'AI', 'Providers']);
    expect(breadcrumbFor(manifest, '/docs/bugs/BUG-0001', 'BUG-0001').map((c) => c.title)).toEqual(['Bugs', 'BUG-0001']);
  });
});

describe('docs search', () => {
  const index: SearchEntry[] = [
    { t: 'Appium remote', s: 'User Guide', p: '/docs/user-guide/appium', h: ['Setup'], b: 'Configure the Appium server URL in the device form.' },
    { t: 'Mobile phone setup', s: 'Get Started', p: '/docs/get-started/hardware', h: ['Phones'], b: 'Plug in the phone; Appium is optional.' },
    { t: 'Docker', s: 'Get Started', p: '/docs/get-started/docker', h: [], b: 'Run the stack in containers.' },
  ];
  it('ranks a title hit above a body hit and drops non-matches', () => {
    const hits = searchDocs(index, 'appium');
    expect(hits.map((h) => h.entry.p)).toEqual(['/docs/user-guide/appium', '/docs/get-started/hardware']);
    expect(hits[0].snippet.toLowerCase()).toContain('appium');
  });
  it('needs every word to match', () => {
    expect(searchDocs(index, 'appium docker')).toEqual([]);
    expect(searchDocs(index, '')).toEqual([]);
  });
  it('splits text into highlighted parts', () => {
    expect(highlightParts('Use Appium here', ['appium'])).toEqual([
      { text: 'Use ', hit: false },
      { text: 'Appium', hit: true },
      { text: ' here', hit: false },
    ]);
  });
});
