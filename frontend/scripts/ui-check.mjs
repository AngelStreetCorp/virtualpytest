#!/usr/bin/env node
/**
 * UI rules checker (TASK-59). `node frontend/scripts/ui-check.mjs` (wired into `npm run lint`).
 * Rules: docs/agent/platform/UI_STYLE.md section 10.
 *
 *  table-layout  a file that renders an MUI <Table> must fix its column widths (`tableLayout`,
 *                <colgroup>, or the resizable-columns hook) so rows don't re-flow when data changes.
 *  page-colour   src/pages/** may not hold a hex colour literal or `primary.main` (use the palette).
 *
 * Ratchet: existing violations are listed in scripts/ui-check-baseline.json and tolerated; a NEW
 * violation (or a count that grows) fails. Fix a file, then run with --update to shrink the baseline.
 * Opt out one table with `ui-ok: table-layout` in the file (say why in the comment).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = path.join(FRONTEND, 'src');
const BASELINE = path.join(FRONTEND, 'scripts', 'ui-check-baseline.json');
const update = process.argv.includes('--update');

const walk = (dir, out = []) => {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name === 'dist') continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.tsx$/.test(e.name)) out.push(p);
  }
  return out;
};

const found = {}; // "rule file" -> count
for (const f of walk(SRC)) {
  const rel = path.relative(FRONTEND, f).split(path.sep).join('/');
  const s = fs.readFileSync(f, 'utf8');
  if (/<Table[\s>]/.test(s) && !/tableLayout|<colgroup|useResizableColumns|resizeCols|ui-ok: table-layout/.test(s)) {
    found[`table-layout ${rel}`] = 1;
  }
  if (rel.startsWith('src/pages/')) {
    const n = (s.match(/['"`]#[0-9a-fA-F]{3,8}['"`]|primary\.main/g) || []).length;
    if (n) found[`page-colour ${rel}`] = n;
  }
}

if (update) {
  fs.writeFileSync(BASELINE, JSON.stringify(found, Object.keys(found).sort(), 2) + '\n');
  console.log(`baseline written: ${Object.keys(found).length} entries`);
  process.exit(0);
}

const base = JSON.parse(fs.readFileSync(BASELINE, 'utf8'));
const bad = Object.entries(found).filter(([k, n]) => n > (base[k] ?? 0));
for (const [k, n] of bad) console.error(`ui-check: ${k} (${n}${base[k] ? `, was ${base[k]}` : ''}) — see UI_STYLE.md section 10`);
const stale = Object.keys(base).filter((k) => !(k in found));
if (stale.length) console.error(`ui-check: ${stale.length} baseline entries are fixed — run \`node scripts/ui-check.mjs --update\``);
process.exit(bad.length ? 1 : 0);
