/**
 * In-house i18n (TASK-53). Keys ARE the English source text, so English has no catalog file;
 * fr/de are lazy JSON chunks in ./locales. Storage key and `?lang=` are shared with
 * virtualpytest.com and the HTML test reports (TASK-52), so they switch together.
 */

export const LANGUAGES = [
  { code: 'en', short: 'EN', name: 'English' },
  { code: 'fr', short: 'FR', name: 'Français' },
  { code: 'de', short: 'DE', name: 'Deutsch' },
] as const;

export type Language = (typeof LANGUAGES)[number]['code'];

export const LANGUAGE_STORAGE_KEY = 'virtualpytest:language';

type PluralValue = string | Record<string, string>;
type Catalog = Record<string, PluralValue>;
type Vars = Record<string, string | number>;

const INTL_LOCALES: Record<Language, string> = { en: 'en-GB', fr: 'fr-FR', de: 'de-DE' };

const isLanguage = (code: unknown): code is Language =>
  typeof code === 'string' && LANGUAGES.some((l) => l.code === code);

const readStorage = (): string | null => {
  try {
    return window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
  } catch {
    return null;
  }
};

const writeStorage = (code: Language): void => {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, code);
  } catch {
    // storage blocked (private window, sandbox) — the choice just won't persist
  }
};

const detectLanguage = (): Language => {
  try {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get('lang');
    if (fromUrl !== null) {
      // Applied once and stored; dropped from the address bar so a bookmark or a reload does not
      // override a later choice made in the picker.
      params.delete('lang');
      const query = params.toString();
      window.history.replaceState(window.history.state, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`);
    }
    if (isLanguage(fromUrl)) {
      writeStorage(fromUrl);
      return fromUrl;
    }
  } catch {
    // ignore malformed location
  }
  const stored = readStorage();
  if (isLanguage(stored)) return stored;
  try {
    const prefix = (navigator.language || '').slice(0, 2).toLowerCase();
    if (isLanguage(prefix)) return prefix;
  } catch {
    // no navigator
  }
  return 'en';
};

let current: Language = detectLanguage();
let catalog: Catalog = {};
let pluralRules = new Intl.PluralRules(INTL_LOCALES[current]);
const listeners = new Set<() => void>();

const loadCatalog = async (code: Language): Promise<Catalog> => {
  if (code === 'fr') return (await import('./locales/fr.json')).default as Catalog;
  if (code === 'de') return (await import('./locales/de.json')).default as Catalog;
  return {};
};

const applyDocumentLang = (code: Language) => {
  if (typeof document !== 'undefined') document.documentElement.lang = code;
};

export const initI18n = async (): Promise<void> => {
  try {
    catalog = await loadCatalog(current);
  } catch (error) {
    console.error('Failed to load language catalog, falling back to English:', error);
    catalog = {};
  }
  pluralRules = new Intl.PluralRules(INTL_LOCALES[current]);
  applyDocumentLang(current);
};

export const getLanguage = (): Language => current;

export const subscribe = (fn: () => void): (() => void) => {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
};

export const setLanguage = async (code: Language): Promise<void> => {
  if (!isLanguage(code) || code === current) return;
  let next: Catalog = {};
  try {
    next = await loadCatalog(code);
  } catch (error) {
    console.error('Failed to load language catalog:', error);
  }
  current = code;
  catalog = next;
  pluralRules = new Intl.PluralRules(INTL_LOCALES[code]);
  writeStorage(code);
  applyDocumentLang(code);
  listeners.forEach((fn) => fn());
};

const interpolate = (text: string, vars?: Vars): string =>
  vars ? text.replace(/\{(\w+)\}/g, (match, name) => (name in vars ? String(vars[name]) : match)) : text;

export const translate = (key: string, vars?: Vars & { context?: string }): string => {
  let text: string | undefined;
  if (vars?.context !== undefined) {
    const hit = catalog[`${key}#${vars.context}`];
    if (typeof hit === 'string') text = hit;
  }
  if (text === undefined) {
    const hit = catalog[key];
    text = typeof hit === 'string' ? hit : key;
  }
  return interpolate(text, vars);
};

export const translatePlural = (count: number, one: string, other: string, vars?: Vars): string => {
  const merged = { count, ...vars };
  const entry = catalog[other];
  if (entry === undefined) return interpolate(count === 1 ? one : other, merged);
  if (typeof entry === 'string') return interpolate(entry, merged);
  const category = pluralRules.select(count);
  return interpolate(entry[category] ?? entry.other ?? other, merged);
};

export const getIntlLocale = (): string => INTL_LOCALES[current];

export const formatDate = (date: Date | number | string, opts?: Intl.DateTimeFormatOptions): string =>
  new Date(date).toLocaleString(INTL_LOCALES[current], opts);

export const formatNumber = (n: number, opts?: Intl.NumberFormatOptions): string =>
  n.toLocaleString(INTL_LOCALES[current], opts);

/**
 * Sets `#lang=<current>` so an HTML report (TASK-52) opens in the app's language. A fragment,
 * not a query param: report links are presigned URLs and an extra query param breaks the signature.
 */
export const withLang = (url: string): string => {
  const hashAt = url.indexOf('#');
  const base = hashAt >= 0 ? url.slice(0, hashAt) : url;
  const params = new URLSearchParams(hashAt >= 0 ? url.slice(hashAt + 1) : '');
  params.set('lang', current);
  return `${base}#${params.toString()}`;
};
