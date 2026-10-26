import { stripEmoji } from './docsText';
import { slugifyHeading } from './markdownComponents';

/**
 * Per-page opt-ins for the docs viewer, written as HTML comments at the top of a markdown file
 * (they render as nothing, and GitHub hides them too):
 *   <!-- toc: h2 -->   force the "On this page" panel (it is automatic from 3 h2 headings; kept for pages with fewer)
 *   <!-- toc: off -->  no "On this page" panel, even with 3 or more h2 headings
 *   <!-- compact -->   body text one step smaller (the same scale as /docs/faq)
 */
export interface DocsPageOptions {
  toc: boolean;
  tocOff: boolean;
  compact: boolean;
}

export interface DocsHeading {
  id: string;
  label: string;
}

export const parseDocsPageOptions = (md: string): DocsPageOptions => {
  // Only the leading comments count, so a sentence that quotes the marker cannot switch it on.
  const lead = md.match(/^(?:\s*<!--[\s\S]*?-->)+/)?.[0] ?? '';
  return {
    toc: /<!--\s*toc:\s*h2\s*-->/i.test(lead),
    tocOff: /<!--\s*toc:\s*off\s*-->/i.test(lead),
    compact: /<!--\s*compact\s*-->/i.test(lead),
  };
};

/** The h2 headings of a markdown document (code fences skipped), with the ids the renderer gives them. */
/** An "On this page" panel appears from this many h2 headings, with no marker needed. */
export const AUTO_TOC_MIN_H2 = 3;

/** Headings for the "On this page" panel, or none when the page opts out or is too short to need one. */
export const tocHeadingsFor = (md: string, options: DocsPageOptions): DocsHeading[] => {
  if (options.tocOff) return [];
  const all = extractH2Headings(md);
  return options.toc || all.length >= AUTO_TOC_MIN_H2 ? all : [];
};

export const extractH2Headings = (md: string): DocsHeading[] => {
  const out: DocsHeading[] = [];
  let fence = false;
  for (const line of md.split('\n')) {
    if (/^\s*(```|~~~)/.test(line)) {
      fence = !fence;
      continue;
    }
    if (fence) continue;
    const m = line.match(/^##\s+(.+?)\s*#*\s*$/);
    if (!m) continue;
    const plain = m[1].replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[`*_]/g, '').trim();
    // The id is the slug of the raw text (it must equal the rendered heading's id, and GitHub's); the label drops emoji.
    out.push({ id: slugifyHeading(plain), label: stripEmoji(plain) });
  }
  return out;
};

/** Open every <details> around `el`, so an anchor inside a closed one can be scrolled to. */
export const openAncestorDetails = (el: Element): void => {
  let d = el.closest('details');
  while (d) {
    d.open = true;
    d = d.parentElement ? d.parentElement.closest('details') : null;
  }
};
