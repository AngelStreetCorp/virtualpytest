import { useCallback, useState } from 'react';

/** Reader preferences kept in localStorage (never required: every access is guarded). */
const KEY = 'virtualpytest:docs:';

export const readPref = (name: string): string | null => {
  try {
    return localStorage.getItem(KEY + name);
  } catch {
    return null;
  }
};

export const writePref = (name: string, value: string): void => {
  try {
    localStorage.setItem(KEY + name, value);
  } catch {
    /* storage unavailable: the choice lasts until the page closes */
  }
};

/** A boolean pref (rail open / closed) with a default and a setter that persists. */
export const useBoolPref = (name: string, fallback: boolean): [boolean, (v: boolean) => void] => {
  const [value, setValue] = useState<boolean>(() => {
    const raw = readPref(name);
    return raw === null ? fallback : raw === '1';
  });
  const set = useCallback((v: boolean) => {
    setValue(v);
    writePref(name, v ? '1' : '0');
  }, [name]);
  return [value, set];
};

/** Reader text size: S = 0.9x, M = 1x, L = 1.15x of the docs type scale. */
export const READER_SIZES = ['s', 'm', 'l'] as const;
export type ReaderSize = (typeof READER_SIZES)[number];
/** A visitor with no stored choice reads at S (0.9x); a stored choice wins. */
export const DEFAULT_READER_SIZE: ReaderSize = 's';
export const READER_FACTOR: Record<ReaderSize, number> = { s: 0.9, m: 1, l: 1.15 };

export const readReaderSize = (): ReaderSize => {
  const raw = readPref('readerSize');
  return (READER_SIZES as readonly string[]).includes(raw ?? '') ? (raw as ReaderSize) : DEFAULT_READER_SIZE;
};
