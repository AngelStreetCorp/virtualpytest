#!/usr/bin/env node
/**
 * Status check (TASK-102 G15/G13). Run: `cd frontend && node scripts/status_check.mjs [--enforce]`.
 *
 * "Running is never green" (docs/agent/platform/UI_STYLE.md): flags `severity={<cond> ? 'success' ...}`
 * whose condition mentions executing|running|loading|pending|progress (a success box shown for work
 * still in flight). MUI info/success colours are themed in ThemeContext, so they are not scanned.
 * Reports by default; --enforce fails when a file in ENFORCED has a hit.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ENFORCED = ['src/components/navigation/Navigation_NodeGotoPanel.tsx'];
const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const RULE = /severity=\{[^}]*(executing|running|loading|pending|progress)[^}]*\?\s*'success'/i;

const walk = (d, out = []) => {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const f = path.join(d, e.name);
    if (e.isDirectory()) walk(f, out);
    else if (/\.tsx$/.test(e.name)) out.push(f);
  }
  return out;
};

let failed = 0;
for (const f of walk(path.join(FRONTEND, 'src'))) {
  const rel = path.relative(FRONTEND, f);
  fs.readFileSync(f, 'utf8').split('\n').forEach((line, i) => {
    if (!RULE.test(line)) return;
    console.log(`${rel}:${i + 1}: success shown for a running state`);
    if (process.argv.includes('--enforce') && ENFORCED.includes(rel)) failed++;
  });
}
console.log(failed ? `status_check: ${failed} violation(s)` : 'status_check: ok');
process.exit(failed ? 1 : 0);
