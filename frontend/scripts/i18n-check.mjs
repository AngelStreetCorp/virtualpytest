#!/usr/bin/env node
/**
 * i18n checker (TASK-53). Run from anywhere: `node frontend/scripts/i18n-check.mjs`.
 *
 *  (a) every literal key in t('…') / tn(n,'…','…') / translate('…') / translatePlural(n,'…','…')
 *      (plus `label` / `sectionLabel` properties in KEY_PROPERTY_FILES, translated where rendered)
 *      must exist in locales/fr.json and locales/de.json with the same {placeholders};
 *  (b) files listed in src/i18n/translated-files.txt may not contain raw English JSX text or
 *      user-facing prop literals (opt out with `i18n-ignore` on the line or the line before);
 *  (c) prints the literal count over ALL .tsx files (progress number).
 *
 * Flags: --missing (print missing keys as JSON {key: ""}), --quiet.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = path.join(FRONTEND, 'src');
const LOCALES = path.join(SRC, 'i18n', 'locales');
const LANGS = ['fr', 'de'];
const PROPS = new Set(['label', 'title', 'placeholder', 'helperText', 'aria-label', 'alt', 'tooltip', 'primary', 'secondary', 'headerName']);
// Config files (and features/*/frontend/routes.tsx nav entries) whose `label:` / `sectionLabel:` literals are keys (rendered through t(item.label)).
const KEY_PROPERTY_FILES = new Set([
  'src/config/navItems.tsx',
  'src/components/mobile/MobileMoreMenuItems.tsx',
  'src/components/mobile/MobileBottomNav.tsx',
]);

const args = new Set(process.argv.slice(2));
const quiet = args.has('--quiet');
const log = (...a) => { if (!quiet) console.error(...a); };

const walk = (dir, out = []) => {
  if (!fs.existsSync(dir)) return out;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name === 'dist') continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.(ts|tsx)$/.test(e.name) && !/\.d\.ts$/.test(e.name)) out.push(p);
  }
  return out;
};

const files = [...walk(SRC)];
const featuresDir = path.resolve(FRONTEND, '..', 'features');
if (fs.existsSync(featuresDir)) {
  for (const f of fs.readdirSync(featuresDir)) walk(path.join(featuresDir, f, 'frontend'), files);
}

const rel = (f) => path.relative(FRONTEND, f).split(path.sep).join('/');
const isText = (n) => n && (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n));
const hasLetter = (s) => /[A-Za-z]/.test(s);
const placeholders = (s) => [...new Set([...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]))].sort();

const keys = new Map(); // key -> "file:line"
const pluralKeys = new Set(); // keys used through tn()/translatePlural()
const addKey = (key, where) => { if (!keys.has(key)) keys.set(key, where); };
const literals = []; // {file, line, text}

const parse = (file) => {
  const text = fs.readFileSync(file, 'utf8');
  const kind = file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  return { text, sf: ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind) };
};

const lineOf = (sf, node) => sf.getLineAndCharacterOfPosition(node.getStart(sf)).line;

const collectKeys = (file, sf) => {
  const keyProps = KEY_PROPERTY_FILES.has(rel(file)) || /^\.\.\/features\/[^/]+\/frontend\/routes\.tsx$/.test(rel(file));
  const visit = (node) => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
      const name = node.expression.text;
      const where = `${rel(file)}:${lineOf(sf, node) + 1}`;
      const a = node.arguments;
      if ((name === 't' || name === 'translate') && isText(a[0])) {
        const ctx = a[1] && ts.isObjectLiteralExpression(a[1])
          ? a[1].properties.find((p) => ts.isPropertyAssignment(p) && p.name.getText() === 'context' && isText(p.initializer))
          : undefined;
        if (ctx) addKey(`${a[0].text}#${ctx.initializer.text}`, where);
        else addKey(a[0].text, where);
      } else if ((name === 'tn' || name === 'translatePlural') && isText(a[1]) && isText(a[2])) {
        addKey(a[2].text, where);
        pluralKeys.add(a[2].text);
      }
    }
    if (keyProps && ts.isPropertyAssignment(node) && ['label', 'sectionLabel'].includes(node.name.getText()) && isText(node.initializer)) {
      addKey(node.initializer.text, `${rel(file)}:${lineOf(sf, node) + 1}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
};

const collectLiterals = (file, text, sf) => {
  const lines = text.split('\n');
  const ignored = (line) => lines[line]?.includes('i18n-ignore') || (line > 0 && lines[line - 1]?.includes('i18n-ignore'));
  const push = (node, value, at = node) => {
    const line = lineOf(sf, at);
    literals.push({ file: rel(file), line: line + 1, text: value.trim().replace(/\s+/g, ' ').slice(0, 60), ignored: ignored(line) });
  };
  const visit = (node) => {
    if (ts.isJsxText(node)) {
      const raw = node.text;
      if (hasLetter(raw.replace(/&\w+;/g, ''))) {
        const offset = raw.length - raw.trimStart().length;
        const line = sf.getLineAndCharacterOfPosition(node.getStart(sf) + offset).line;
        literals.push({ file: rel(file), line: line + 1, text: raw.trim().replace(/\s+/g, ' ').slice(0, 60), ignored: ignored(line) });
      }
    } else if (ts.isJsxAttribute(node) && PROPS.has(node.name.getText())) {
      const init = node.initializer;
      if (init && ts.isStringLiteral(init) && hasLetter(init.text)) push(node, init.text);
      else if (init && ts.isJsxExpression(init) && isText(init.expression) && hasLetter(init.expression.text)) push(node, init.expression.text);
    } else if (ts.isJsxExpression(node) && (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent)) && isText(node.expression) && hasLetter(node.expression.text)) {
      push(node, node.expression.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
};

const translatedList = (() => {
  const p = path.join(SRC, 'i18n', 'translated-files.txt');
  if (!fs.existsSync(p)) return [];
  return fs.readFileSync(p, 'utf8').split('\n').map((l) => l.replace(/#.*/, '').trim()).filter(Boolean);
})();
const translatedSet = new Set(translatedList);

const perFileLiterals = new Map();
for (const file of files) {
  const { text, sf } = parse(file);
  collectKeys(file, sf);
  if (file.endsWith('.tsx')) {
    const before = literals.length;
    collectLiterals(file, text, sf);
    perFileLiterals.set(rel(file), literals.slice(before));
  }
}

let errors = 0;
const fail = (msg) => { errors += 1; console.error(`ERROR ${msg}`); };

// (a) catalogs
const catalogs = {};
for (const lang of LANGS) {
  const p = path.join(LOCALES, `${lang}.json`);
  if (!fs.existsSync(p)) { fail(`missing catalog ${rel(p)}`); catalogs[lang] = {}; continue; }
  catalogs[lang] = JSON.parse(fs.readFileSync(p, 'utf8'));
}

const missing = {};
for (const [key, where] of keys) {
  for (const lang of LANGS) {
    const entry = catalogs[lang][key];
    if (entry === undefined || entry === '' ) {
      missing[key] = '';
      fail(`${lang}.json lacks key "${key}" (${where})`);
      continue;
    }
    const want = placeholders(key.replace(/#\w+$/, ''));
    if (typeof entry === 'string') {
      const got = placeholders(entry);
      if (got.join() !== want.join()) fail(`${lang}.json "${key}": placeholders {${got}} differ from source {${want}}`);
    } else {
      if (!pluralKeys.has(key)) fail(`${lang}.json "${key}" is a plural object but the code calls t() (${where}); use tn()`);
      for (const [cat, value] of Object.entries(entry)) {
        const got = placeholders(value);
        const bad = cat === 'other' ? got.join() !== want.join() : got.some((g) => !want.includes(g));
        if (bad) fail(`${lang}.json "${key}" [${cat}]: placeholders {${got}} differ from source {${want}}`);
      }
      if (entry.other === undefined) fail(`${lang}.json "${key}": plural object has no "other"`);
    }
  }
}
for (const lang of LANGS) {
  for (const key of Object.keys(catalogs[lang])) {
    if (!keys.has(key)) log(`warn: ${lang}.json has unused key "${key}"`);
  }
}

// (b) literals in translated files
for (const f of translatedList) {
  if (!fs.existsSync(path.join(FRONTEND, f))) { fail(`translated-files.txt lists a missing file: ${f}`); continue; }
  for (const l of perFileLiterals.get(f) ?? []) {
    if (!l.ignored) fail(`untranslated literal in ${l.file}:${l.line}: "${l.text}"`);
  }
}

// (c) progress
const all = literals.filter((l) => !l.ignored);
const unique = new Set(all.map((l) => l.text)).size;
const covered = all.filter((l) => translatedSet.has(l.file)).length;
console.error(`i18n: ${keys.size} keys; ${all.length} literals in ${files.filter((f) => f.endsWith('.tsx')).length} .tsx files (${unique} unique), ${all.length - covered} still outside translated files; ${translatedList.length} files enforced; ${errors} error(s)`);

if (args.has('--missing')) console.log(JSON.stringify(missing, null, 2));
process.exit(errors ? 1 : 0);
