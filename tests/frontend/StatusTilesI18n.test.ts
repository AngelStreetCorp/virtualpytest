/**
 * The Status page tiles in French and German (BUG-0785).
 *
 * The four summary tiles (Services healthy, Server CPU, Server RAM, Server disk) were raw
 * English literals while the rest of the page was translated — the page looked half broken.
 * The labels already existed in the catalogues (the dashboard's system cards use the very
 * same keys), and `src/pages/Status.tsx` is now listed in `translated-files.txt`, so the CI
 * i18n check refuses a raw English literal in that page from now on.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(__dirname, '../../frontend');
const read = (...p: string[]) => fs.readFileSync(path.join(FRONTEND, ...p), 'utf8');
const catalogue = (lang: 'fr' | 'de') => JSON.parse(read('src/i18n/locales', `${lang}.json`));

describe('the Status page (BUG-0785)', () => {
  it('is a page the i18n check enforces', () => {
    const enforced = read('src/i18n/translated-files.txt').split('\n').map((l) => l.trim());
    expect(enforced).toContain('src/pages/Status.tsx');
  });

  it('has a translation for every tile label', () => {
    const keys = ['Services healthy', 'Server CPU', 'Server RAM', 'Server disk'];
    for (const lang of ['fr', 'de'] as const) {
      const c = catalogue(lang);
      for (const key of keys) {
        expect(typeof c[key], `${lang}.json is missing "${key}"`).toBe('string');
        // A stub that repeats the English key is not a translation.
        expect(c[key] === key, `${lang}.json leaves "${key}" in English`).toBe(false);
      }
    }
  });

  it('has a translation for the strings the page header shows', () => {
    const keys = ['System Status', 'Last checked: {time}', 'Refresh now'];
    for (const lang of ['fr', 'de'] as const) {
      const c = catalogue(lang);
      for (const key of keys) {
        expect(typeof c[key], `${lang}.json is missing "${key}"`).toBe('string');
        expect(c[key] === key, `${lang}.json leaves "${key}" in English`).toBe(false);
      }
    }
  });
});
