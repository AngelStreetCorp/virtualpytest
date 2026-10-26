#!/usr/bin/env node
/**
 * Button role checker (TASK-102 G13). Run: `cd frontend && node scripts/button_role_check.mjs`.
 *
 * Buttons take their colour from their ROLE (docs/agent/platform/UI_STYLE.md "Button roles"):
 * primaryButtonSx / toggleSx / selectedSx / neutralButtonSx / dangerButtonSx from PageChrome.
 * This flags, on Button / IconButton / ToggleButton / Fab opening tags:
 *   - color="success" | "error" | "info" | "warning" | "secondary"  (also color={...} holding one of them)
 *   - an sx colour set to P.success / P.error / P.warning
 * Allowed on purpose (a fixed status control): list the file in scripts/button-role-allow.json
 * with a reason; its count is the number of tolerated hits.
 *
 * Fails when ANY file in src has more hits than its allow-list count (the sweep is finished).
 * Flags: --quiet (no per-file report).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = path.join(FRONTEND, 'src');
const ALLOW_FILE = path.join(FRONTEND, 'scripts', 'button-role-allow.json');
const ALLOW = fs.existsSync(ALLOW_FILE) ? JSON.parse(fs.readFileSync(ALLOW_FILE, 'utf8')) : { files: {} };

const TAG = /<(Button|IconButton|ToggleButton|Fab)\b/g;
const BAD_COLOR = /\bcolor=(?:"|\{\s*['"]?)?(success|error|info|warning|secondary)\b/;
const BAD_SX = /\bcolor:\s*(?:[^,}]*\?\s*)?P\.(success|error|warning)\b/;

/** Text of the JSX opening tag starting at `start` (up to the closing `>` outside braces/strings). */
const openingTag = (src, start) => {
  let depth = 0, quote = null;
  for (let i = start; i < src.length; i++) {
    const c = src[i];
    if (quote) { if (c === quote) quote = null; continue; }
    if (c === '"' || c === "'" || c === '`') { quote = c; continue; }
    if (c === '{') depth++;
    else if (c === '}') depth--;
    else if (c === '>' && depth === 0 && src[i - 1] !== '=') return src.slice(start, i + 1);
  }
  return src.slice(start, start + 600);
};

const walk = (dir, out = []) => {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const f = path.join(dir, e.name);
    if (e.isDirectory()) walk(f, out);
    else if (/\.tsx$/.test(e.name) && !/\.test\.tsx$/.test(e.name)) out.push(f);
  }
  return out;
};

const counts = {};
for (const file of walk(SRC)) {
  const src = fs.readFileSync(file, 'utf8');
  const rel = path.relative(FRONTEND, file);
  for (const m of src.matchAll(TAG)) {
    const tag = openingTag(src, m.index);
    if (BAD_COLOR.test(tag) || BAD_SX.test(tag)) counts[rel] = (counts[rel] || 0) + 1;
  }
}

const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]);
const total = rows.reduce((n, [, c]) => n + c, 0);
if (!process.argv.includes('--quiet') && total) {
  console.log(`button_role_check: ${total} control(s) in ${rows.length} file(s)`);
  rows.forEach(([f, c]) => console.log(`  ${String(c).padStart(3)}  ${f}`));
}

let bad = 0;
for (const [rel, n] of rows) {
  const allowed = (ALLOW.files || {})[rel] || 0;
  if (n > allowed) {
    bad += 1;
    console.error(`${rel}: ${n} control(s) use a status/secondary colour (allowed ${allowed}); use primaryButtonSx / toggleSx / neutralButtonSx / dangerButtonSx from PageChrome`);
  }
}
if (bad) process.exit(1);
console.log('button_role_check: ok (all of src)');
