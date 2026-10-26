#!/usr/bin/env node
/**
 * Notify check (TASK-145, contract #43). Run: `cd frontend && node scripts/notify_check.mjs`.
 *
 * Every error the user can act on goes through the notification system (docs/agent/platform/NOTIFICATIONS.md):
 * `useToast().showError / showWarning` (recorded as an `action` notification) or `notify({...})`.
 * Fails (exit 1) on a bare react-hot-toast call that raises a toast (`toast.error`, `toast.success`, `toast.loading`,
 * `toast.custom`, `toast.promise`, `toast(`) anywhere in src outside contexts/ToastContext.tsx.
 * `toast.dismiss` is fine: it only closes a toast.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');
const OWNER = 'contexts/ToastContext.tsx';
const BARE = /\btoast(\.(error|success|loading|custom|promise)\b|\s*\()/;

const walk = (dir, out = []) => {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const f = path.join(dir, e.name);
    if (e.isDirectory()) walk(f, out);
    else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.(ts|tsx)$/.test(e.name)) out.push(f);
  }
  return out;
};

let bad = 0;
for (const file of walk(SRC)) {
  const rel = path.relative(SRC, file).split(path.sep).join('/');
  if (rel === OWNER) continue;
  const src = fs.readFileSync(file, 'utf8');
  if (!/from\s+['"]react-hot-toast['"]/.test(src)) continue;
  src.split('\n').forEach((line, i) => {
    if (/^\s*(\/\/|\*)/.test(line)) return;
    if (BARE.test(line.replace(/\btoast\.dismiss\b/g, ''))) {
      console.error(`notify_check: ${rel}:${i + 1} bare toast call; use useToast().showError / notify() (contract #43)`);
      bad++;
    }
  });
}
if (bad) process.exit(1);
console.log('notify_check: ok');
