#!/usr/bin/env node
/**
 * One-shot font-literal sweep (TASK-100 PR-B). Walks every .tsx file under src/ (skipping
 * constants/, scripts/, i18n/, ui-check.mjs), replaces literal `fontSize: <number>` /
 * `fontSize: '<n>rem'` / `fontSize: '<n>px'` values with `fontSize: TYPOGRAPHY.<role>.size`.
 * The role is chosen by the px value (UI_STYLE.md §10a). Imports `TYPOGRAPHY` from
 * `constants/typography` when not already imported.
 *
 * Usage:
 *   node frontend/scripts/sweep-fontsize.mjs --dry-run    # measure, do not write
 *   node frontend/scripts/sweep-fontsize.mjs              # write migrations
 *   node frontend/scripts/sweep-fontsize.mjs --update     # also rerun ui-check --update
 *
 * Opt out a literal with `// ui-ok: no-literal-font-size — <why>` on the line above.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execSync } from 'node:child_process';

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = path.join(FRONTEND, 'src');

const args = process.argv.slice(2);
const dryRun = args.includes('--dry-run');
const updateBaseline = args.includes('--update');

const ROLE_FOR_PX = (px) => {
  if (px <= 11)   return 'microMeta';
  if (px <= 12.5) return 'caption';
  if (px <= 14)   return 'body';
  if (px <= 16)   return 'navbarItem';
  if (px <= 18)   return 'cardTitle';
  if (px <= 20)   return 'pageSubtitle';
  if (px <= 24)   return 'pageTitle';
  if (px <= 32)   return 'kpiValue';
  return 'displayKpi';
};

const valueToPx = (raw) => {
  if (/^\d+(\.\d+)?$/.test(raw)) return parseFloat(raw);
  const rem = /^([\d.]+)rem$/.exec(raw);
  if (rem) return parseFloat(rem[1]) * 16;
  const px = /^([\d.]+)px$/.exec(raw);
  if (px) return parseFloat(px[1]);
  return NaN;
};

const walk = (dir, out = []) => {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name === 'dist') continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.tsx$/.test(e.name)) out.push(p);
  }
  return out;
};

const typographyImportFor = (filePath) => {
  const typographyAbs = path.join(SRC, 'constants', 'typography');
  let rel = path.relative(path.dirname(filePath), typographyAbs);
  if (!rel.startsWith('.')) rel = './' + rel;
  rel = rel.split(path.sep).join('/');
  return `import { TYPOGRAPHY } from '${rel}';`;
};

const hasTypographyImport = (text) =>
  /import\s*\{[^}]*\bTYPOGRAPHY\b[^}]*\}\s*from\s+['"][^'"]*constants\/typography['"]/.test(text);

/** Scan `src` and rewrite each `fontSize: <literal>` match to `fontSize: TYPOGRAPHY.<role>.size`. */
const sweep = (src) => {
  const rxNum = /(^|[\s,({])fontSize:\s*(\d+(?:\.\d+)?)(?=\s*[,}\s])/g;
  const rxStr = /(^|[\s,({])fontSize:\s*(['"`])(\d+(?:\.\d+)?)(rem|px)?\2(?=\s*[,}\s])/g;
  const matches = [];
  let m;
  while ((m = rxNum.exec(src))) matches.push({ m, kind: 'num' });
  while ((m = rxStr.exec(src))) matches.push({ m, kind: 'str' });
  if (!matches.length) return { changed: 0, out: src };
  matches.sort((a, b) => a.m.index - b.m.index);
  const lines = src.split('\n');
  let out = '';
  let cursor = 0;
  let changed = 0;
  for (const { m, kind } of matches) {
    const px = kind === 'num' ? valueToPx(m[2]) : valueToPx(`${m[3]}${m[4] || ''}`);
    if (!Number.isFinite(px)) continue;
    const lead = m[1];
    const whole = m[0];
    const start = m.index;
    const ln = src.slice(0, start).split('\n').length - 1;
    const above = lines[ln - 1] || '';
    if (/ui-ok:\s*no-literal-font-size/.test(above)) continue;
    const role = ROLE_FOR_PX(px);
    out += src.slice(cursor, start) + `${lead}fontSize: TYPOGRAPHY.${role}.size`;
    cursor = start + whole.length;
    changed++;
  }
  out += src.slice(cursor);
  return { changed, out };
};

const insertImport = (text, importLine) => {
  const lines = text.split('\n');
  // Find the line of the last fully closed `import ...;` at the top of the file, while
  // skipping a leading `'use client';` / `'use server';` directive (must stay at the very
  // top of a Next.js client component) and JS doc-comments.
  let insertAfter = -1;
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i].trim();
    if (l === '' || l.startsWith('//')) continue;
    if (l.startsWith('/*') || l.startsWith('*')) {
      // skip a doc-block: advance until we close it
      let j = i;
      while (j < lines.length && !lines[j].includes('*/')) j++;
      i = j;
      continue;
    }
    if (l === "'use client';" || l === "'use server';" || l === '"use client";' || l === '"use server";') {
      // Directive — must stay at top. Skip past and keep looking for the first import.
      continue;
    }
    if (l.startsWith('import ') || l.startsWith('import{')) {
      insertAfter = i;
      if (l.endsWith(';')) continue;
      // multi-line import — find the closing `};`
      let j = i;
      while (j < lines.length && !lines[j].includes(';')) j++;
      insertAfter = j;
      i = j;
      continue;
    }
    // First non-import, non-blank, non-comment, non-directive line — stop.
    break;
  }
  if (insertAfter < 0) return importLine + '\n\n' + text;
  // Insert AFTER any directive that precedes the imports — directives must stay at the top.
  // Walk back: if the line just above `insertAfter` is a `'use client';` directive, push
  // the new import BELOW the directive's successor (which is the first import).
  // (We already ensure directives precede the new line by the search above.)
  lines.splice(insertAfter + 1, 0, importLine);
  return lines.join('\n');
};

const files = walk(SRC).filter((f) => {
  if (f.includes(`${path.sep}constants${path.sep}`)) return false;
  if (f.includes(`${path.sep}scripts${path.sep}`)) return false;
  if (f.includes(`${path.sep}i18n${path.sep}`)) return false;
  if (f.endsWith('ui-check.mjs')) return false;
  return true;
});

let totalChanges = 0;
let touchedFiles = 0;
const samples = [];
for (const f of files) {
  const text = fs.readFileSync(f, 'utf8');
  const { out: next, changed } = sweep(text);
  if (!changed) continue;
  let finalText = next;
  if (!hasTypographyImport(next)) {
    const importLine = typographyImportFor(f);
    finalText = insertImport(next, importLine);
  }
  if (!dryRun) fs.writeFileSync(f, finalText);
  totalChanges += changed;
  touchedFiles++;
  if (samples.length < 8) samples.push(path.relative(FRONTEND, f));
}

console.log(`files touched: ${touchedFiles}`);
console.log(`total literal -> TYPOGRAPHY replacements: ${totalChanges}`);
console.log(`samples: ${samples.join(', ')}`);
if (dryRun) console.log('--dry-run: no files were written.');

if (updateBaseline && !dryRun) {
  try {
    execSync('node scripts/ui-check.mjs --update', { cwd: FRONTEND, stdio: 'inherit' });
  } catch (e) {
    console.error('ui-check --update failed:', e.message);
  }
}
