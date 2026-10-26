import { Box, Drawer, IconButton, Typography, useMediaQuery, useTheme } from '@mui/material';
import { MenuOutlined, SearchOutlined } from '@mui/icons-material';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useLocation } from 'react-router-dom';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import DocsNav from '../components/docs/DocsNav';
import DocsOnThisPage from '../components/docs/DocsOnThisPage';
import DocsPageHeader, { DocsBreadcrumb } from '../components/docs/DocsPageHeader';
import DocsSkeleton from '../components/docs/DocsSkeleton';
import DocsPager from '../components/docs/DocsPager';
import DocsSearch, { searchShortcutLabel } from '../components/docs/DocsSearch';
import {
  breadcrumbFor,
  getCachedManifest,
  loadDocsManifest,
  neighbours,
  type DocsManifest,
} from '../components/docs/docsManifest';
import { docsMeasure, docsRailStickySx } from '../components/docs/docsLayout';
import { docsTypeScale } from '../components/docs/docsTypeScale';
import { READER_FACTOR, readReaderSize, useBoolPref, writePref, type ReaderSize } from '../components/docs/docsPrefs';
import { openAncestorDetails, parseDocsPageOptions, tocHeadingsFor } from '../components/docs/docsPageOptions';
import { createDocsMarkdownComponents, hasTechnicalBlock } from '../components/docs/markdownComponents';
import ReleaseNotesView from '../components/docs/ReleaseNotesView';
import IntegrationsGridView from '../components/docs/IntegrationsGridView';
import ScreenshotGallery from '../components/docs/ScreenshotGallery';
import SecurityReportsView from '../components/docs/SecurityReportsView';
import ApiDocsView from '../components/docs/ApiDocsView';
import VideoShowcase from '../components/docs/VideoShowcase';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { docsSectionIcon } from '../config/navItems';
import { TYPOGRAPHY } from '../constants/typography';
import { useI18n } from '../i18n/useI18n';

// Fetched markdown by path, so revisiting a page paints at once; it is revalidated in the background.
const mdCache = new Map<string, string>();

// Meta/process H2 sections that are useful for contributors editing the file in-repo
// but are noise for the in-app reader. Keyed by route `section`, stripped before render
// so the page shows only the shipped changelog / the bug index.
const STRIP_SECTIONS: Record<string, string[]> = {
  bugs: ['How to log a bug'],
  // The grid at the top of /docs/integrations is these two lists, so rendering them
  // again below it would say everything twice. The README keeps them for GitHub.
  integrations: ['Available Integrations', 'Planned'],
};

// Sections rendered one step down the docs type scale. /docs/faq is the only one: its
// answers are long paragraphs wrapped around tables, and at the normal body size comparing
// two answers meant a lot of scrolling. One section, so the release notes, the technical
// docs and every other section keep their current size.
const COMPACT_SECTIONS = new Set(['faq']);

/**
 * Remove the configured H2 sections (heading through to the next H1/H2 heading) from a
 * markdown document. Any horizontal rule / trailing lines that belonged to the stripped
 * section are dropped with it. Unknown sections are left untouched.
 */
const stripMetaSections = (md: string, section?: string): string => {
  const titles = section ? STRIP_SECTIONS[section] : undefined;
  if (!titles || titles.length === 0) return md;
  const wanted = titles.map((t) => t.toLowerCase());

  const out: string[] = [];
  let skipping = false;
  for (const line of md.split('\n')) {
    const heading = line.match(/^(#{1,2})\s+(.*)$/);
    if (heading) {
      const title = heading[2].trim().toLowerCase();
      // Starting a stripped section begins skipping; any other H1/H2 ends it.
      skipping = wanted.includes(title);
      if (skipping) continue;
    }
    if (!skipping) out.push(line);
  }
  return out.join('\n');
};

/**
 * Simple Documentation Viewer - Renders markdown files from /docs
 */
const Documentation: React.FC = () => {
  const P = useAgentChatPalette();
  const theme = useTheme();
  const { t } = useI18n();
  const wide = useMediaQuery(theme.breakpoints.up('md'));
  const [manifest, setManifest] = useState<DocsManifest>(getCachedManifest() ?? { docs: [] });
  const [drawer, setDrawer] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  // Rails default open on wide screens; a collapse is remembered. The reader size is S / M / L (docsPrefs.ts).
  const [navOpen, setNavOpen] = useBoolPref('navOpen', true);
  const [tocOpen, setTocOpen] = useBoolPref('tocOpen', true);
  const [showTechnical, setShowTechnical] = useBoolPref('showTechnical', false);
  const [readerSize, setReaderSizeState] = useState<ReaderSize>(readReaderSize);
  const setReaderSize = (v: ReaderSize) => {
    setReaderSizeState(v);
    writePref('readerSize', v);
  };
  // One persistent route for every /docs/* page (App.tsx): the splat is split here, so the rails, the
  // header and the card are never remounted by a page change, only their content changes.
  const splat = useParams()['*'] ?? '';
  const seg = splat.split('/').filter(Boolean);
  const section = seg[0] ?? 'README';
  const subsection = seg.length >= 3 ? seg[1] : undefined;
  const category = seg.length >= 4 ? seg[2] : undefined;
  const page = seg.length >= 2 ? seg[Math.min(seg.length, 4) - 1] : 'README';
  const [fetched, setFetched] = useState<{ path: string; text: string } | null>(null);
  const [errState, setErrState] = useState<{ path: string; msg: string } | null>(null);

  // Compute current path for navigator
  const getCurrentDocPath = (): string => {
    if (category && page !== 'README') {
      return `/docs/${section}/${subsection}/${category}/${page}`;
    } else if (category) {
      return `/docs/${section}/${subsection}/${category}`;
    } else if (subsection && page !== 'README') {
      return `/docs/${section}/${subsection}/${page}`;
    } else if (subsection) {
      return `/docs/${section}/${subsection}`;
    } else if (section !== 'README' && page === 'README') {
      return `/docs/${section}`;
    } else if (page !== 'README') {
      return `/docs/${section}/${page}`;
    }
    return `/docs/${section}`;
  };

  // Source file under docs/, e.g. "/get-started/local-dev.md" (also the "Edit on GitHub" target).
  const mdPath = ((): string => {
    if (section === 'README' && !subsection && !category) return '/README.md';
    if (category && page !== 'README') return `/${section}/${subsection}/${category}/${page}.md`;
    if (category) return `/${section}/${subsection}/${category}/README.md`;
    if (subsection && page !== 'README') return `/${section}/${subsection}/${page}.md`;
    if (subsection) return `/${section}/${subsection}/README.md`;
    if (page === 'README') return `/${section}/README.md`;
    return `/${section}/${page}.md`;
  })();

  useEffect(() => {
    let alive = true;
    void loadDocsManifest().then((m) => {
      if (alive) setManifest(m);
    });
    return () => { alive = false; };
  }, []);

  const fullPath = `/docs${mdPath}`;
  // What the reader shows for THIS path: the fetched text, else the cache (instant revisit), else nothing yet.
  // The security dashboard is an authenticated API view with no public markdown file: nothing to fetch.
  const noMarkdown = section === 'security' && !subsection && !category && page === 'README';
  const raw: string | undefined = noMarkdown ? `# ${t('Security Reports')}` : fetched?.path === fullPath ? fetched.text : mdCache.get(fullPath);
  const error = errState?.path === fullPath && raw === undefined ? errState.msg : '';
  // Loading is a boolean, never "the data is empty": the skeleton shows only while this page is on its way.
  const loading = raw === undefined && !error;
  const markdown = useMemo(() => (raw === undefined ? '' : stripMetaSections(raw, section)), [raw, section]);

  useEffect(() => {
    if (noMarkdown) return;
    let alive = true;
    const run = async () => {
      try {
        const response = await fetch(fullPath);
        if (!response.ok) throw new Error(`Documentation not found: ${fullPath}`);
        const text = await response.text();
        const lower = text.trimStart().toLowerCase();
        if (lower.startsWith('<!doctype') || lower.startsWith('<html')) {
          throw new Error(`Invalid documentation response (received HTML instead of Markdown): ${fullPath}`);
        }
        const had = mdCache.get(fullPath);
        mdCache.set(fullPath, text);
        // A revisit already showed the cached text; only a changed file repaints.
        if (alive && text !== had) setFetched({ path: fullPath, text });
      } catch (err) {
        console.error('Error loading documentation:', err);
        if (alive) setErrState({ path: fullPath, msg: err instanceof Error ? err.message : t('Failed to load documentation') });
      }
    };
    void run();
    return () => { alive = false; };
  }, [fullPath, noMarkdown]);

  // Deep links (#step-0): the markdown arrives after the browser's own hash scroll has already run
  // (and on a new tab it ran against an empty page), so scroll to the anchor once the content is rendered.
  const { hash } = useLocation();
  useEffect(() => {
    if (!hash || !markdown) return;
    let id = hash.slice(1);
    try { id = decodeURIComponent(id); } catch { /* keep raw */ }
    const el = document.getElementById(id) ?? document.getElementsByName(id)[0];
    if (!el) return;
    openAncestorDetails(el); // an anchor inside a closed <details> is open before the scroll
    el.style.scrollMarginTop = '80px'; // clear the fixed top bar
    el.scrollIntoView({ behavior: 'auto', block: 'start' });
  }, [hash, markdown]);

  // The file's first H1 is the page title: the header bar shows it, so it is cut from the body and not shown twice.
  const isSectionHome = !subsection && !category && page === 'README' && section !== 'README';
  const h1 = markdown.match(/^#\s+(.+)$/m);
  const sectionTitle = h1 ? h1[1].trim() : '';
  const body = h1 ? markdown.replace(h1[0], '').replace(/^\s*\n/, '') : markdown;
  const currentPath = getCurrentDocPath();
  // Purpose-built views draw their own header; every other page is plain markdown with the reader chrome.
  const isSpecialView =
    !subsection && !category && page === 'README' && ['release_note', 'bugs', 'integrations', 'videos', 'screenshots', 'security', 'api'].includes(section);
  // Page options at the top of the markdown file (see docsPageOptions.ts): "On this page" panel, compact text.
  const pageOptions = parseDocsPageOptions(markdown);
  // The panel is automatic from 3 h2 headings; a purpose-built view keeps its own layout.
  const computedToc = isSpecialView && !pageOptions.toc ? [] : tocHeadingsFor(body, pageOptions);
  // While the next page loads the outline keeps its previous rows, so the right panel does not blink out and in.
  const lastToc = useRef(computedToc);
  if (!loading) lastToc.current = computedToc;
  const tocHeadings = loading ? lastToc.current : computedToc;
  const sectionIcon = isSectionHome ? docsSectionIcon(section) : null;

  const pageH1 = markdown.match(/^#\s+(.+)$/m)?.[1]?.replace(/[`*_]/g, '').trim() ?? '';
  const crumbs = useMemo(() => breadcrumbFor(manifest, currentPath, pageH1.split(' — ')[0]), [manifest, currentPath, pageH1]);
  const { prev, next } = useMemo(() => neighbours(manifest, currentPath), [manifest, currentPath]);
  // The page's own H1 is its title: a last crumb that repeats it is dropped, so no page shows its title twice.
  const pageTitle = pageH1 || crumbs[crumbs.length - 1]?.title || t('Documentation');

  // A new page starts at the top (a deep link keeps its own scroll, handled above).
  // The app scrolls inside one column, not the window: find that column from the page root.
  const rootRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (hash) return;
    let el: HTMLElement | null = rootRef.current;
    while (el && !/(auto|scroll)/.test(getComputedStyle(el).overflowY)) el = el.parentElement;
    (el ?? document.scrollingElement)?.scrollTo(0, 0);
  }, [currentPath, hash]);

  // Cmd/Ctrl+K and "/" open the search; "/" is left alone while typing in a field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setSearchOpen(true);
        return;
      }
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return;
      e.preventDefault();
      setSearchOpen(true);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const navDrawer = <DocsNav manifest={manifest} currentPath={currentPath} onNavigate={() => setDrawer(false)} />;
  const navRail = <DocsNav manifest={manifest} currentPath={currentPath} onCollapse={() => setNavOpen(false)} visible={navOpen} />;
  const showToc = tocHeadings.length > 0;
  const lgUp = useMediaQuery(theme.breakpoints.up('lg'));
  // A collapsed rail leaves the grid altogether (no strip): the card takes the full width. Its toggle is in the
  // card's header bar. The outline column stays reserved while it is open, even on a page without headings.
  const navCol = navOpen ? '250px ' : '';
  const tocCol = tocOpen ? ' 210px' : '';
  const measure = docsMeasure(parseFloat(docsTypeScale(COMPACT_SECTIONS.has(section) || pageOptions.compact, READER_FACTOR[readerSize]).body));
  // Collapsed rail => the card is wider than the measure => centre the text column.
  const centered = !navOpen || (lgUp && !tocOpen);

  const reader = error ? (
    <Box sx={{ p: 3, bgcolor: 'error.dark', borderRadius: 1, border: 1, borderColor: 'error.main' }}>
      <Typography variant="h6" color="error.light">
        {t('Error Loading Documentation')}
      </Typography>
      <Typography variant="body2" sx={{ mt: 1, color: 'error.light' }}>
        {error}
      </Typography>
    </Box>
  ) : (
    <>
      {loading ? <DocsSkeleton /> : (
        <>
      {(section === 'release_note' || section === 'bugs') && !subsection && !category && page === 'README' ? (
        <ReleaseNotesView kind={section as 'release_note' | 'bugs'} title={sectionTitle} markdown={body} getCurrentDocPath={getCurrentDocPath} page={page} />
      ) : section === 'integrations' && !subsection && !category && page === 'README' ? (
        <IntegrationsGridView markdown={body} getCurrentDocPath={getCurrentDocPath} page={page} />
      ) : section === 'security' && !subsection && !category && page === 'README' ? (
        <SecurityReportsView />
      ) : section === 'api' && !subsection && !category && page === 'README' ? (
        <ApiDocsView />
      ) : section === 'videos' && !subsection && !category && page === 'README' ? (
        <VideoShowcase />
      ) : section === 'screenshots' && !subsection && !category && page === 'README' ? (
        <ScreenshotGallery />
      ) : (
        <>
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeRaw]}
            // Allow inline base64 images (data:image/...); keep the default XSS guard for everything else.
            urlTransform={(url) => (url.startsWith('data:image/') ? url : defaultUrlTransform(url))}
            components={createDocsMarkdownComponents(getCurrentDocPath, page, P, COMPACT_SECTIONS.has(section) || pageOptions.compact, READER_FACTOR[readerSize], showTechnical)}
          >
            {body}
          </ReactMarkdown>
          {!loading && <DocsPager prev={prev} next={next} mdPath={mdPath} />}
        </>
      )}
        </>
      )}
    </>
  );

  return (
    <Box ref={rootRef} sx={{ pt: 0, px: { xs: 1.5, md: 3 }, pb: 0, width: '100%', maxWidth: '1480px', mx: 'auto', minHeight: '80vh' }}>
      {/* Top row: drawer button (narrow), breadcrumb, search */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5, minHeight: 36 }}>
        {!wide && (
          <IconButton size="small" onClick={() => setDrawer(true)} aria-label={t('Open documentation menu')} sx={{ color: P.textSecondary }}>
            <MenuOutlined />
          </IconButton>
        )}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <DocsBreadcrumb crumbs={crumbs.length && crumbs[crumbs.length - 1].title.trim().toLowerCase() === pageH1.toLowerCase() ? crumbs.slice(0, -1) : crumbs} />
        </Box>
        <Box
          component="button"
          type="button"
          onClick={() => setSearchOpen(true)}
          aria-label={t('Search documentation')}
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            flex: 'none',
            width: { xs: 36, sm: 300 },
            height: 34,
            px: 1.25,
            justifyContent: { xs: 'center', sm: 'flex-start' },
            border: `1px solid ${P.borderColor}`,
            borderRadius: 2,
            bgcolor: P.surface,
            color: P.textMuted,
            fontSize: TYPOGRAPHY.body.size,
            font: 'inherit',
            cursor: 'pointer',
            '&:hover': { borderColor: P.accent },
            '&:focus-visible': { outline: `2px solid ${P.accent}` },
          }}
        >
          <SearchOutlined sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
          <Box component="span" sx={{ display: { xs: 'none', sm: 'inline' }, flex: 1, textAlign: 'left' }}>{t('Search docs…')}</Box>
          <Box component="kbd" sx={{ display: { xs: 'none', sm: 'inline' }, border: `1px solid ${P.borderColor}`, borderRadius: 1, px: 0.6, fontSize: TYPOGRAPHY.caption.size, fontFamily: 'inherit' }}>
            {searchShortcutLabel()}
          </Box>
        </Box>
      </Box>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: `${navCol}minmax(0, 1fr)`, lg: `${navCol}minmax(0, 1fr)${tocCol}` },
          gap: 2.5,
          alignItems: 'start',
        }}
      >
        {wide && (
          <Box component="aside" sx={{ ...docsRailStickySx, display: navOpen ? 'flex' : 'none', flexDirection: 'column' }}>
            {navRail}
          </Box>
        )}
        <Box
          sx={{
            px: { xs: 2, md: 3.5 },
            pt: 0,
            pb: { xs: 2, md: 3.5 },
            // The bottom gap lives on the card (not the page padding): a sticky rail may only descend to the end of
            // its grid row, so at the end of a long page it stops 16 px above the footer instead of being pushed up
            // under the navbar. 24 px = what the rail needs below the card (docsLayout.ts).
            mb: 3,
            minHeight: '70vh',
            minWidth: 0,
            backgroundColor: 'background.paper',
            borderRadius: 2,
            border: 1,
            borderColor: 'divider',
          }}
        >
          <DocsPageHeader
            markdown={raw ?? ''}
            title={pageTitle}
            icon={sectionIcon ? React.cloneElement(sectionIcon, { /* ui-ok: no-literal-font-size — MUI SvgIcon enum */ fontSize: 'medium', color: 'primary' }) : undefined}
            mdPath={mdPath}
            readerSize={readerSize}
            onReaderSize={setReaderSize}
            showActions={!isSpecialView && !error}
            navOpen={navOpen}
            onNavToggle={wide ? () => setNavOpen(!navOpen) : undefined}
            tocOpen={tocOpen}
            onTocToggle={lgUp ? () => setTocOpen(!tocOpen) : undefined}
            tocDisabled={!showToc}
            hasTechnical={hasTechnicalBlock(raw ?? '')}
            showTechnical={showTechnical}
            onShowTechnical={setShowTechnical}
          />
          <Box
            sx={{
              width: '100%',
              minWidth: 0,
              // Body text keeps a reading measure; code, tables and images use the card's full width.
              // The second selector is the body of a `<div data-technical>` block (DocsTechnicalBlock wraps it in one more box).
              '& > :is(p, ul, ol, h1, h2, h3, h4, blockquote, hr, details), & > div > :is(p, ul, ol, blockquote)': {
                maxWidth: measure,
                marginInline: centered ? 'auto' : 0,
              },
            }}
          >
            {reader}
          </Box>
        </Box>
        {/* The outline column is reserved on wide screens even when a page has no headings: nothing shifts. */}
        {showToc && !error ? (
          <DocsOnThisPage headings={tocHeadings} open={tocOpen} onToggle={() => setTocOpen(!tocOpen)} />
        ) : (
          lgUp && tocOpen && <Box aria-hidden />
        )}
      </Box>

      {!wide && (
        <Drawer
          open={drawer}
          onClose={() => setDrawer(false)}
          PaperProps={{ sx: { width: 'min(320px, 86vw)', p: 1.5, pt: 2 } }}
        >
          {navDrawer}
        </Drawer>
      )}
      <DocsSearch open={searchOpen} onClose={() => setSearchOpen(false)} />
    </Box>
  );
};

export default Documentation;
