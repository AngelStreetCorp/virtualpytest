#!/usr/bin/env node
/**
 * UI rules checker (TASK-59). `node frontend/scripts/ui-check.mjs` (wired into `npm run lint`).
 * Rules: docs/agent/platform/UI_STYLE.md section 10.
 *
 *  table-layout       an MUI <Table> must fix column widths (`tableLayout`, <colgroup>, or
 *                     the resizable-columns hook) so rows don't re-flow when data changes.
 *  page-colour        src/pages/** may not hold a hex colour literal or `primary.main` (use the
 *                     palette).
 *  no-literal-font-size  (TASK-100) every `sx={{ fontSize: <literal> }}`, px `font-size`/`font:`/
 *                     `line-height` in CSS or template strings, `ctx.font = '12px'` and `fontSize={N}`
 *                     on a component must read from
 *                     `constants/typography.ts` (`TYPOGRAPHY.<role>.size`). New code may use the
 *                     `// ui-ok: no-literal-font-size — <why>` opt-out for one-offs like the 404
 *                     page's 6 rem display number.
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
    else if (/\.(tsx?|css)$/.test(e.name) && !/\.d\.ts$/.test(e.name)) out.push(p);
  }
  return out;
};

// Hex colour literals (3, 4, 6 or 8 hex digits) used inside a string, plus the raw
// `primary.main` token. Theme colour tokens live as #rrggbb hex codes — that's why they are
// page-flavoured violations but ignored by MUI's normal palette. Numeric literals:
const HEX_RX = /['"`]#[0-9a-fA-F]{3,8}['"`]/g;
const PRIMARY_MAIN_RX = /\bprimary\.main\b/g;
// `fontSize: <something-literal>` — matches numbers (12, 0.875rem-style strings) but skips
// `fontSize: 'inherit'`, `fontSize: TYPOGRAPHY.…`, and `fontSize: FONT_SIZE_SCALE.…`. The
// user may opt-out one row per file with `// ui-ok: no-literal-font-size`.
//   - numeric form:  fontSize: 12        /  fontSize: 11.5
//   - string form:    fontSize: '0.75rem' / fontSize: "12px"
const FONT_SIZE_NUMERIC_RX = /(?:^|[\s,({])fontSize:\s*(?:\d+(?:\.\d+)?)(?=\s*[,}\s])/g;
const FONT_SIZE_STRING_RX  = /(?:^|[\s,({])fontSize:\s*['"`](?!inherit\b)[^'"`]+['"`]/g;

// JSX prop form on MUI components: `<Typography fontSize={13}>` is px and escapes the Size picker.
// SVG <text>/recharts axes (viewBox units) are not matched: only Typography / Box / Chip.
const FONT_SIZE_PROP_RX = /<[A-Z]\w*\b[^>]*?\bfontSize=\{\d+(?:\.\d+)?\}/gs;

// TASK-100 G7: every other way to write a px text size (the Size picker moves rem only).
//   css / template strings:  font-size: 12px   font: 12px system-ui   line-height: 20px
//   style objects:            lineHeight: '24px'   (fontSize: '12px' / `${n}px` is FONT_SIZE_STRING_RX)
//   canvas:                   ctx.font = '12px sans-serif'
const PX_TEXT_RXS = [
  /font-size:\s*-?\d+(?:\.\d+)?px/g,
  /(?:^|[^-\w])font:\s*['"`]?[^;'"`\n]*?\d+(?:\.\d+)?px/g,
  /line-height:\s*\d+(?:\.\d+)?px/g,
  /lineHeight:\s*['"`]\d+(?:\.\d+)?px['"`]/g,
  /\.font\s*=\s*['"`][^'"`]*\d+px/g,
];

const found = {}; // "rule file" -> count
for (const f of walk(SRC)) {
  const rel = path.relative(FRONTEND, f).split(path.sep).join('/');
  const s = fs.readFileSync(f, 'utf8');

  if (/<Table[\s>]/.test(s) && !/tableLayout|<colgroup|useResizableColumns|resizeCols|ui-ok: table-layout/.test(s)) {
    found[`table-layout ${rel}`] = 1;
  }
  if (rel.startsWith('src/pages/')) {
    const n = ((s.match(HEX_RX) || []).length + (s.match(PRIMARY_MAIN_RX) || []).length);
    if (n) found[`page-colour ${rel}`] = n;
  }
  // Skip the constants file itself (it OWNS the literal sizes) and the typography test file.
  if (!rel.endsWith('ui-check.mjs') && !rel.endsWith('no-literal-font-size-allow.json')) {
    // The marker opts out its own line and, when it is alone on a `//` comment line, the line below.
    const lines = s.split('\n');
    const stripped = lines
      .map((l, i) => (/ui-ok: no-literal-font-size/.test(l) || (i > 0 && /^\s*\/\/.*ui-ok: no-literal-font-size/.test(lines[i - 1]) ? '' : l)))
      .join('\n');
    const numeric  = (stripped.match(FONT_SIZE_NUMERIC_RX) || []).length;
    const string   = (stripped.match(FONT_SIZE_STRING_RX) || []).length;
    const prop      = (stripped.match(FONT_SIZE_PROP_RX) || []).length;
    const px       = PX_TEXT_RXS.reduce((n, rx) => n + (stripped.match(rx) || []).length, 0);
    // fontSize: '12px' is already counted by FONT_SIZE_STRING_RX; do not double count it.
    const total    = numeric + string + prop + px;
    if (total) found[`no-literal-font-size ${rel}`] = total;
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
