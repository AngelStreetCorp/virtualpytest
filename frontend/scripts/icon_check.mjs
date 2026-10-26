#!/usr/bin/env node
/**
 * Icon check (TASK-102 G15). Run: `cd frontend && node scripts/icon_check.mjs [--quiet]`.
 *
 * One icon palette (src/constants/icons.tsx, docs/agent/platform/UI_STYLE.md "Icons"): no emoji or
 * pictograph in UI code. Scans src .ts/.tsx for emoji / dingbat / symbol code points outside comments
 * and console./logger lines, and reports the count per file.
 * Allowed on purpose: list the path (or a dir ending in /) in scripts/icon-allow.json with a reason.
 * Enforced on ALL of src (like button_role_check): exits 1 when any file outside the allow-list has a hit.
 * Arrows (U+2190-21FF, e.g. a "from → to" label) are text, not pictographs, and are not matched.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = path.join(FRONTEND, 'src');
const ALLOW = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'scripts', 'icon-allow.json'), 'utf8')).files ?? {};

// Extended_Pictographic (emoji), misc symbols + dingbats (check marks, crosses, warning), misc technical
// (timers, hourglass), variation selector. Arrows / geometric shapes (remote keys) are not matched.
const PICTO = /(?![\u2190-\u21FF])[\p{Extended_Pictographic}⌀-⏿☀-➿⭐-⭕️]/u;
const LOG = /\b(console\.\w+|logger\.\w+|log\.(debug|info|warn|error))\s*\(/;

const walk = (dir, out = []) => {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const f = path.join(dir, e.name);
    if (e.isDirectory()) walk(f, out);
    else if (/\.(ts|tsx)$/.test(e.name)) out.push(f);
  }
  return out;
};

const isAllowed = (rel) => Object.keys(ALLOW).some((k) => (k.endsWith('/') ? rel.startsWith(k) : rel === k));

/** Count lines with a pictograph, ignoring comments and console/logger lines. */
const countHits = (src) => {
  let hits = 0, inBlock = false;
  for (let line of src.split('\n')) {
    if (inBlock) {
      const end = line.indexOf('*/');
      if (end < 0) continue;
      line = line.slice(end + 2);
      inBlock = false;
    }
    line = line.replace(/\/\*.*?\*\//g, '');
    const open = line.indexOf('/*');
    if (open >= 0) { line = line.slice(0, open); inBlock = true; }
    line = line.replace(/(^|\s)\/\/.*$/, '$1');
    if (!PICTO.test(line) || LOG.test(line)) continue;
    hits++;
  }
  return hits;
};

const quiet = process.argv.includes('--quiet');
const rows = [];
for (const f of walk(SRC)) {
  const rel = path.relative(FRONTEND, f).split(path.sep).join('/');
  if (isAllowed(rel)) continue;
  const n = countHits(fs.readFileSync(f, 'utf8'));
  if (n) rows.push([rel, n]);
}
rows.sort((a, b) => b[1] - a[1]);
if (!quiet) for (const [rel, n] of rows) console.log(`${String(n).padStart(4)}  ${rel}`);
console.log(`icon_check: ${rows.reduce((s, r) => s + r[1], 0)} pictograph lines in ${rows.length} files`);
if (rows.length) {
  console.error(`icon_check: FAIL — ${rows.length} file(s) hold pictographs (use <AppIcon>/<StatusText>, or allow-list with a reason)`);
  process.exit(1);
}
console.log('icon_check: ok (all of src)');
