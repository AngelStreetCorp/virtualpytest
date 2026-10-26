#!/usr/bin/env node
// Writes docs-search-index.json next to docs-manifest.json (TASK-124).
// Usage: node scripts/gen-docs-search-index.mjs <published-docs-dir>
// Called by copy-docs.sh on the staging dir, so the index always matches the markdown that ships.
//
// One entry per published page:
//   t  title (first H1, else the file name)      s  section title (from the manifest)
//   p  route path (/docs/...)
//   h  H2 headings                               b  plain-text body excerpt (searched, snippets come from it)
// The client (components/docs/docsSearchIndex.ts) scores it; nothing here needs a server or a new dependency.
import fs from 'node:fs';
import path from 'node:path';

const DOCS_DIR = process.argv[2] || process.env.DOCS_OUT;
if (!DOCS_DIR || !fs.existsSync(DOCS_DIR)) {
  console.error('gen-docs-search-index: docs dir not found:', DOCS_DIR);
  process.exit(1);
}

// Bug reports are 450+ near-identical pages; a shorter excerpt keeps the index small.
const BODY_CHARS = 1200;
const BODY_CHARS_BUGS = 400;

let sectionTitles = {};
try {
  const manifest = JSON.parse(fs.readFileSync(path.join(DOCS_DIR, 'docs-manifest.json'), 'utf8'));
  for (const s of manifest.docs) sectionTitles[s.section] = s.title;
} catch {
  /* titles fall back to the folder name */
}

// No emoji in the index (UI_STYLE.md "Docs reader"); same pattern as src/components/docs/docsText.ts.
const EMOJI = /(?:[0-9#*]\uFE0F?\u20E3|(?![\u00A9\u00AE\u2122])\p{Extended_Pictographic}|\p{Regional_Indicator}|\uFE0F|\u200D|\u20E3)+/gu;
const stripEmoji = (t) => t.replace(EMOJI, '').replace(/\s{2,}/g, ' ').trim();

const toTitle = (name) =>
  name.replace(/\.md$/, '').replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

const stripMarkdown = (md) =>
  md
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/^(```|~~~).*$/gm, ' ')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/<[^>]+>/g, ' ')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/^\s*\d+\.\s+/gm, '')
    .replace(/[|`*_>]/g, ' ')
    .replace(/^[-=\s:]{3,}$/gm, ' ')
    .replace(/\s+/g, ' ')
    .trim();

const walk = (dir, out = []) => {
  for (const name of fs.readdirSync(dir).sort()) {
    if (name.startsWith('.') || name === 'openapi' || name === 'images') continue;
    const full = path.join(dir, name);
    if (fs.statSync(full).isDirectory()) walk(full, out);
    else if (name.endsWith('.md')) out.push(full);
  }
  return out;
};

const entries = [];
for (const file of walk(DOCS_DIR)) {
  const rel = path.relative(DOCS_DIR, file).split(path.sep).join('/');
  const parts = rel.replace(/\.md$/, '').split('/');
  const isReadme = parts[parts.length - 1] === 'README';
  // Same routes the manifest uses: a README is its folder, nested READMEs are not routable.
  if (isReadme && parts.length > 2) continue;
  const routeParts = isReadme ? parts.slice(0, -1) : parts;
  const route = routeParts.length ? '/docs/' + routeParts.join('/') : '/docs/README';
  const section = parts.length > 1 ? parts[0] : 'root';

  const raw = fs.readFileSync(file, 'utf8');
  const h1 = raw.match(/^#\s+(.+)$/m);
  const title = stripEmoji(h1 ? h1[1] : toTitle(parts[parts.length - 1] === 'README' ? parts[parts.length - 2] || 'Documentation' : parts[parts.length - 1]))
    .replace(/[`*_]/g, '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .trim();

  const h2 = [];
  let fence = false;
  for (const line of raw.split('\n')) {
    if (/^\s*(```|~~~)/.test(line)) { fence = !fence; continue; }
    if (fence) continue;
    const m = line.match(/^##\s+(.+?)\s*#*\s*$/);
    if (m) h2.push(stripEmoji(m[1].replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[`*_]/g, '')));
  }

  // Drop the H1 from the excerpt: it is already the title.
  const text = stripEmoji(stripMarkdown(raw.replace(/^#\s+.+$/m, '')));
  entries.push({
    t: title,
    s: sectionTitles[section] || toTitle(section),
    p: route,
    h: h2.slice(0, 40),
    b: text.slice(0, section === 'bugs' ? BODY_CHARS_BUGS : BODY_CHARS),
  });
}

fs.writeFileSync(path.join(DOCS_DIR, 'docs-search-index.json'), JSON.stringify({ v: 1, pages: entries }));
console.log('Generated docs-search-index.json with ' + entries.length + ' pages');
