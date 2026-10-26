/**
 * Client-side docs search (TASK-124). The index (docs-search-index.json, built by
 * scripts/gen-docs-search-index.mjs next to docs-manifest.json) is fetched on first use; a tiny
 * scorer ranks it. No dependency, no server call. If the index is missing the manifest titles are
 * searched instead, so the box never goes dead.
 */
import { flattenPages, loadDocsManifest, sectionOf } from './docsManifest';

export interface SearchEntry {
  /** title */
  t: string;
  /** section title */
  s: string;
  /** route path */
  p: string;
  /** H2 headings */
  h: string[];
  /** plain-text body excerpt */
  b: string;
}

export interface SearchHit {
  entry: SearchEntry;
  score: number;
  /** ~200 chars around the first body match (or the start of the page) */
  snippet: string;
  /** the H2 the query matched, if the title did not */
  heading?: string;
}

export interface TextPart {
  text: string;
  hit: boolean;
}

let indexPromise: Promise<SearchEntry[]> | null = null;

const INDEX_URLS = ['/docs/docs-search-index.json', '/docs-search-index.json'];

/** Loads the index once; falls back to manifest titles. */
export const loadSearchIndex = (): Promise<SearchEntry[]> => {
  if (indexPromise) return indexPromise;
  indexPromise = (async () => {
    for (const url of INDEX_URLS) {
      try {
        const res = await fetch(url);
        if (!res.ok) continue;
        const parsed = JSON.parse(await res.text()) as { pages?: SearchEntry[] };
        if (parsed && Array.isArray(parsed.pages)) return parsed.pages;
      } catch {
        // try the next candidate URL
      }
    }
    const manifest = await loadDocsManifest();
    return flattenPages(manifest).map((p) => ({
      t: p.title,
      s: sectionOf(manifest, p.path)?.title ?? '',
      p: p.path,
      h: [],
      b: '',
    }));
  })();
  // A failed load must not be cached forever.
  indexPromise.then((r) => { if (r.length === 0) indexPromise = null; }, () => { indexPromise = null; });
  return indexPromise;
};

/** Lower-cased query words; empty for a blank query. */
export const queryTokens = (query: string): string[] =>
  query.toLowerCase().split(/\s+/).map((w) => w.trim()).filter(Boolean);

const SNIPPET_CHARS = 200;

/** Window of `text` around the first token match (the start of the text when nothing matches). */
export const makeSnippet = (text: string, tokens: string[]): string => {
  if (!text) return '';
  const lower = text.toLowerCase();
  let at = -1;
  for (const tok of tokens) {
    const i = lower.indexOf(tok);
    if (i >= 0 && (at < 0 || i < at)) at = i;
  }
  if (at < 0) return text.slice(0, SNIPPET_CHARS) + (text.length > SNIPPET_CHARS ? '…' : '');
  const start = Math.max(0, at - 60);
  const end = Math.min(text.length, start + SNIPPET_CHARS);
  return (start > 0 ? '…' : '') + text.slice(start, end) + (end < text.length ? '…' : '');
};

/** Splits `text` into plain and matching parts, for highlighting. */
export const highlightParts = (text: string, tokens: string[]): TextPart[] => {
  if (!tokens.length || !text) return [{ text, hit: false }];
  const escaped = tokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).sort((a, b) => b.length - a.length);
  const re = new RegExp(`(${escaped.join('|')})`, 'gi');
  // split() with one capture group puts the matches at the odd indices.
  return text
    .split(re)
    .map((p, i) => ({ text: p, hit: i % 2 === 1 }))
    .filter((p) => p.text !== '');
};

const countUpTo = (hay: string, needle: string, cap: number): number => {
  let n = 0;
  let from = 0;
  while (n < cap) {
    const i = hay.indexOf(needle, from);
    if (i < 0) break;
    n += 1;
    from = i + needle.length;
  }
  return n;
};

const wordStart = (hay: string, needle: string): boolean => new RegExp(`(^|[^\\p{L}\\p{N}])${needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'u').test(hay);

/**
 * Ranks the index for a query. Every word must match somewhere (title, section, a heading or the
 * body excerpt). Title beats heading beats body; a title that starts with the query wins ties.
 */
export const searchDocs = (index: SearchEntry[], query: string, limit = 30): SearchHit[] => {
  const tokens = queryTokens(query);
  if (!tokens.length) return [];
  const hits: SearchHit[] = [];
  for (const entry of index) {
    const title = entry.t.toLowerCase();
    const section = entry.s.toLowerCase();
    const body = entry.b.toLowerCase();
    const headings = entry.h.map((h) => h.toLowerCase());
    let score = 0;
    let matchedHeading: string | undefined;
    let ok = true;
    for (const tok of tokens) {
      let s = 0;
      if (title.includes(tok)) s += wordStart(title, tok) ? 12 : 8;
      const hi = headings.findIndex((h) => h.includes(tok));
      if (hi >= 0) {
        s += 5;
        if (!title.includes(tok)) matchedHeading ??= entry.h[hi];
      }
      if (section.includes(tok)) s += 2;
      const n = countUpTo(body, tok, 3);
      if (n) s += n;
      if (s === 0) { ok = false; break; }
      score += s;
    }
    if (!ok) continue;
    if (title.startsWith(tokens.join(' '))) score += 10;
    hits.push({ entry, score, snippet: makeSnippet(entry.b, tokens), heading: matchedHeading });
  }
  hits.sort((a, b) => b.score - a.score || a.entry.t.localeCompare(b.entry.t));
  return hits.slice(0, limit);
};
