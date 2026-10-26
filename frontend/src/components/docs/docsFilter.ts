/**
 * Small helpers shared by the docs pages that filter by category and keep their state in the URL hash
 * (VideoShowcase: #c=<cat>&v=<id>, ScreenshotGallery: #c=<cat>&s=<id>).
 */

/** Reads one `#key=value` / `&key=value` hash parameter, or null. `pattern` is the regex source of the value. */
export const readHashParam = (key: string, pattern = '[\\w-]+'): string | null => {
  const m = new RegExp(`[#&]${key}=(${pattern})`).exec(window.location.hash);
  return m ? m[1] : null;
};

/** Writes the hash with replaceState: shareable, but no history entry per click. Empty values are left out. */
export const writeHashParams = (params: Array<[string, string | null]>): void => {
  const hash = params
    .filter(([, v]) => v)
    .map(([k, v]) => `${k}=${v}`)
    .join('&');
  window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${hash ? '#' + hash : ''}`);
};

/** Alphabetical, case/accent-insensitive, numbers in natural order (returns a copy). */
export const sortAlphabetical = <T,>(items: T[], title: (item: T) => string): T[] =>
  [...items].sort((a, b) => title(a).localeCompare(title(b), undefined, { sensitivity: 'base', numeric: true }));
