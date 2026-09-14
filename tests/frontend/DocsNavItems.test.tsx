import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { DOCS_ITEMS } from '../../frontend/src/config/navItems';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DOCS = path.resolve(__dirname, '../../frontend/public/docs');

// Docs menu entries that are NOT markdown: they have their own React route in App.tsx
// (/docs/api → ApiDocumentation, /docs/security → SecurityReports) and never fetch a .md.
const NON_MARKDOWN_DOCS_ROUTES = ['/docs/api', '/docs/security'];

describe('Docs menu', () => {
  // BUG-0081: copy-docs.sh stopped publishing docs/bugs/ but the menu kept its "Bugs"
  // entry, so the item led to a page that could only ever error — the markdown 404s and
  // the SPA fallback hands the viewer index.html. A menu item whose section is not in
  // the published copy is always that bug.
  it('only links to sections that are actually published under public/docs', () => {
    const markdownItems = DOCS_ITEMS.filter(
      (item) =>
        item.path?.startsWith('/docs/') &&
        !item.external &&
        !NON_MARKDOWN_DOCS_ROUTES.includes(item.path),
    );

    // Guards against the check silently passing on an empty or moved menu.
    expect(markdownItems.length).toBeGreaterThan(5);

    const missing = markdownItems.filter(
      (item) => !fs.existsSync(path.join(PUBLIC_DOCS, item.path!.replace('/docs/', ''), 'README.md')),
    );

    expect(
      missing.map((item) => `${item.label} → ${item.path}`),
      'Docs menu items with no published README.md (add them to copy-docs.sh or drop the menu item)',
    ).toEqual([]);
  });
});
