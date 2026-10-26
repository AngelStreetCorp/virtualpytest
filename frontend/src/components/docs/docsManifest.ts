import { DOCS_ITEMS } from '../../config/navItems';
import { stripEmoji } from './docsText';

/**
 * The docs manifest (docs-manifest.json, written by scripts/copy-docs.sh) and the pure helpers the
 * reader chrome shares: nav tree, breadcrumb, previous / next. No React in here.
 */

export interface DocItem {
  title: string;
  path?: string;
  children?: DocItem[];
}

export interface DocSection {
  title: string;
  path: string;
  section: string;
  children?: DocItem[];
}

export interface DocsManifest {
  docs: DocSection[];
}

export interface DocsCrumb {
  title: string;
  path?: string;
}

export interface DocsPageRef {
  title: string;
  path: string;
}

// Fetched manifest, so every consumer paints at once on revisit; it is revalidated in the background.
let cached: DocsManifest | null = null;
let inflight: Promise<DocsManifest> | null = null;

const MANIFEST_URLS = ['/docs/docs-manifest.json', '/docs-manifest.json'];

const cleanItems = (items?: DocItem[]): DocItem[] | undefined =>
  items?.map((it) => ({ ...it, title: stripEmoji(it.title), children: cleanItems(it.children) }));

/**
 * The Docs menu (DOCS_ITEMS) names the sections: its label wins over the manifest's title, so the navbar,
 * the left rail, the breadcrumb and the page pill can never spell a section two ways. Emoji never show.
 */
export const normalizeManifest = (m: DocsManifest): DocsManifest => ({
  docs: m.docs.map((s) => {
    const label = DOCS_ITEMS.find((i) => i.path === (s.section === 'root' ? '/docs' : s.path))?.label;
    return { ...s, title: stripEmoji(label ?? s.title), children: cleanItems(s.children) };
  }),
});

export const getCachedManifest = (): DocsManifest | null => cached;

/** Loads (and caches) the manifest; an empty manifest if no candidate URL returns JSON. */
export const loadDocsManifest = (): Promise<DocsManifest> => {
  if (inflight) return inflight;
  inflight = (async () => {
    for (const url of MANIFEST_URLS) {
      try {
        const res = await fetch(url, { cache: 'no-store' });
        if (!res.ok) continue;
        const parsed = JSON.parse(await res.text()) as DocsManifest;
        if (parsed && Array.isArray(parsed.docs)) {
          cached = normalizeManifest(parsed);
          return cached;
        }
      } catch {
        // try the next candidate URL
      }
    }
    console.error('Failed to load docs manifest from known paths');
    return cached ?? { docs: [] };
  })().finally(() => {
    inflight = null;
  });
  return inflight;
};

/** Every page of a section/subsection with a path, in manifest order. */
const collect = (items: DocItem[] | undefined, out: DocsPageRef[]): void => {
  items?.forEach((it) => {
    if (it.path) out.push({ title: it.title, path: it.path });
    if (it.children) collect(it.children, out);
  });
};

/** Reading order of the whole manifest, used by the Previous / Next footer. Duplicate paths are dropped. */
export const flattenPages = (manifest: DocsManifest): DocsPageRef[] => {
  const out: DocsPageRef[] = [];
  manifest.docs.forEach((s) => {
    // A section with no children (Documentation Home) is itself a page; otherwise its "Overview" child is.
    if (!s.children?.length) out.push({ title: s.title, path: s.path });
    else collect(s.children, out);
  });
  const seen = new Set<string>();
  return out.filter((p) => (seen.has(p.path) ? false : (seen.add(p.path), true)));
};

/** Previous and next page around `path`, or nulls when the page is not in the manifest. */
export const neighbours = (manifest: DocsManifest, path: string): { prev: DocsPageRef | null; next: DocsPageRef | null } => {
  const list = flattenPages(manifest);
  const i = list.findIndex((p) => p.path === path);
  if (i < 0) return { prev: null, next: null };
  return { prev: i > 0 ? list[i - 1] : null, next: i < list.length - 1 ? list[i + 1] : null };
};

/** The section a path belongs to: exact match first, then the longest section prefix (bug reports are not in the manifest). */
export const sectionOf = (manifest: DocsManifest, path: string): DocSection | undefined => {
  const exact = manifest.docs.find((s) => s.path === path || s.children && hasPath(s.children, path));
  if (exact) return exact;
  return manifest.docs.find((s) => s.section !== 'root' && path.startsWith(`${s.path}/`));
};

const hasPath = (items: DocItem[], path: string): boolean =>
  items.some((it) => it.path === path || (it.children ? hasPath(it.children, path) : false));

/**
 * Breadcrumb for a path: Section › [Subsection] › Page. The "Docs" root crumb is added by the caller.
 * `fallbackTitle` names a page that is under a known section but not listed (a bug report).
 */
export const breadcrumbFor = (manifest: DocsManifest, path: string, fallbackTitle = ''): DocsCrumb[] => {
  for (const s of manifest.docs) {
    if (s.path === path && !s.children?.length) return [{ title: s.title }];
    if (!s.children) continue;
    for (const child of s.children) {
      if (child.path === path) {
        // The Overview child is the section itself.
        return path === s.path ? [{ title: s.title }] : [{ title: s.title, path: s.path }, { title: child.title }];
      }
      for (const sub of child.children ?? []) {
        if (sub.path === path) return [{ title: s.title, path: s.path }, { title: child.title }, { title: sub.title }];
      }
    }
  }
  const owner = sectionOf(manifest, path);
  if (owner) return [{ title: owner.title, path: owner.path }, ...(fallbackTitle ? [{ title: fallbackTitle }] : [])];
  return fallbackTitle ? [{ title: fallbackTitle }] : [];
};
