import { Box, IconButton, InputBase, Tooltip } from '@mui/material';
import { ArticleOutlined, ChevronLeft, ExpandMore, HubOutlined, SearchOutlined } from '@mui/icons-material';
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { DOCS_ITEMS } from '../../config/navItems';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import type { DocItem, DocSection, DocsManifest } from './docsManifest';
import { stripEmoji } from './docsText';

/** A line of a section: a page link, or a small muted group label (never a nested folder). */
export type RailEntry = { kind: 'page'; title: string; path: string } | { kind: 'group'; title: string };

/** Icons for manifest sections the Docs menu does not list (they go last), in the same outlined style. */
const EXTRA_ICONS: Record<string, React.ElementType> = { mcp: HubOutlined };

/**
 * The rail is two levels: section, then page. A third level (Technical's AI, Architecture ...) is
 * flattened into the section: its pages sit directly under it, behind a muted group label.
 */
export const flattenSection = (items: DocItem[] | undefined): RailEntry[] => {
  const out: RailEntry[] = [];
  const walk = (list: DocItem[]) =>
    list.forEach((it) => {
      if (it.path) out.push({ kind: 'page', title: stripEmoji(it.title), path: it.path });
      else if (it.children?.length) {
        out.push({ kind: 'group', title: stripEmoji(it.title) });
        walk(it.children);
      }
    });
  walk(items ?? []);
  // A group with no page under it (all filtered out) is noise.
  return out.filter((e, i) => e.kind === 'page' || (out[i + 1] && out[i + 1].kind === 'page'));
};

interface RailRow {
  slug: string;
  label: string;
  icon: React.ReactElement;
  /** Where the row links. */
  to: string;
  section?: DocSection;
  /** The label comes from the Docs menu (translated); false for a manifest-only section. */
  fromMenu: boolean;
}

/** Rows in Docs-menu order (labels and icons from DOCS_ITEMS), then manifest sections the menu lacks. */
export const buildRailRows = (manifest: DocsManifest): RailRow[] => {
  const rows: RailRow[] = [];
  const used = new Set<string>();
  DOCS_ITEMS.forEach((item) => {
    if (!item.path || !item.path.startsWith('/docs') || !React.isValidElement(item.icon)) return;
    const slug = item.path === '/docs' ? 'root' : item.path.slice('/docs/'.length);
    const section = manifest.docs.find((s) => s.section === slug);
    if (section) used.add(slug);
    rows.push({ slug, label: item.label, icon: item.icon as React.ReactElement, to: item.path, section, fromMenu: true });
  });
  manifest.docs.forEach((s) => {
    if (used.has(s.section)) return;
    const Icon = EXTRA_ICONS[s.section] ?? ArticleOutlined;
    rows.push({ slug: s.section, label: stripEmoji(s.title), icon: <Icon />, to: s.path, section: s, fromMenu: false });
  });
  return rows;
};

const containsPath = (items: DocItem[], path: string): boolean =>
  items.some((it) => it.path === path || (it.children ? containsPath(it.children, path) : false));

interface DocsNavProps {
  manifest: DocsManifest;
  currentPath: string;
  /** Called after a link is followed (the mobile drawer closes itself with it). */
  onNavigate?: () => void;
  /** Collapse the rail to its thin strip (desktop only). */
  onCollapse?: () => void;
  /** The rail stays mounted while collapsed (display: none); its list scroll offset is put back when it shows again. */
  visible?: boolean;
}

/**
 * Persistent left rail for /docs. Order, labels and icons come from the navbar's Docs menu (DOCS_ITEMS);
 * the manifest only supplies each section's pages. Only the section of the current page starts open.
 */
const DocsNav: React.FC<DocsNavProps> = ({ manifest, currentPath, onNavigate, onCollapse, visible = true }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [filter, setFilter] = useState('');
  const rootRef = useRef<HTMLElement | null>(null);
  const savedScroll = useRef(0);
  const q = filter.trim().toLowerCase();
  // Menu labels are keys (the navbar translates them the same way); manifest-only sections are data.
  const rowLabel = (row: RailRow): string => (row.fromMenu ? t(row.label) : row.label);
  const rows = useMemo(() => buildRailRows(manifest), [manifest]);

  // The section the reader is in. Bug reports are not in the manifest, so fall back to the path prefix.
  const activeSlug = useMemo(
    () =>
      rows.find((r) => r.section && (r.section.path === currentPath || (r.section.children && containsPath(r.section.children, currentPath))))?.slug ??
      rows.find((r) => r.slug !== 'root' && r.section && currentPath.startsWith(`${r.section.path}/`))?.slug,
    [rows, currentPath],
  );

  // Only the current section starts open. Moving to another section opens it and collapses the rest;
  // a click opens one section at a time too.
  const [opened, setOpened] = useState<Set<string>>(() => new Set(activeSlug ? [activeSlug] : []));
  useEffect(() => {
    if (!activeSlug) return;
    // One section open at a time: showing a page collapses the others.
    setOpened((prev) => (prev.size === 1 && prev.has(activeSlug) ? prev : new Set([activeSlug])));
  }, [activeSlug]);

  useLayoutEffect(() => {
    if (visible && rootRef.current) rootRef.current.scrollTop = savedScroll.current;
  }, [visible]);

  // Keep the current row visible inside the rail without scrolling the page itself.
  useEffect(() => {
    const root = rootRef.current;
    const cur = root?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!root || !cur) return;
    const top = cur.offsetTop - root.offsetTop;
    if (top < root.scrollTop || top > root.scrollTop + root.clientHeight - 40) root.scrollTop = Math.max(0, top - 80);
  }, [currentPath, manifest, opened.size]);

  const rowSx = (on: boolean, depth: number) => ({
    display: 'flex',
    alignItems: 'center',
    gap: 0.75,
    pl: 1.25 + depth * 1.5,
    pr: 1,
    py: 0.5,
    borderRadius: 1,
    // Selection changes colour and the rule only, never weight or size, so nothing shifts (UI_STYLE S5).
    borderLeft: '2px solid',
    borderColor: on ? P.accent : 'transparent',
    bgcolor: on ? P.hoverBg : 'transparent',
    color: on ? P.accentText : P.textSecondary,
    fontSize: TYPOGRAPHY.body.size,
    textDecoration: 'none',
    cursor: 'pointer',
    lineHeight: 1.35,
    '&:hover': { bgcolor: P.hoverBg },
    '&:focus-visible': { outline: `2px solid ${P.accent}`, outlineOffset: -2 },
  });

  const icon = (row: RailRow) =>
    React.cloneElement(row.icon as React.ReactElement<{ sx?: object }>, { sx: { fontSize: TYPOGRAPHY.navbarItem.size, flex: 'none' } });

  const renderRow = (row: RailRow): React.ReactNode => {
    const section = row.section;
    const entries = flattenSection(section?.children);
    const pages = entries.filter((e): e is Extract<RailEntry, { kind: 'page' }> => e.kind === 'page');
    const rowPath = section?.path ?? row.to;
    const labelMatch = !!q && rowLabel(row).toLowerCase().includes(q);
    const isActive = activeSlug === row.slug;
    const single = pages.length <= 1 && (!pages[0] || pages[0].path === section?.path);

    if (single) {
      if (q && !labelMatch) return null;
      return (
        <Box
          key={row.slug}
          component={RouterLink}
          to={row.to}
          onClick={onNavigate}
          aria-current={rowPath === currentPath ? 'page' : undefined}
          sx={{ ...rowSx(rowPath === currentPath || isActive, 0), mt: 0.5, fontWeight: 600, color: rowPath === currentPath || isActive ? P.accentText : P.textPrimary }}
        >
          {icon(row)}
          <Box component="span" sx={{ minWidth: 0 }}>{rowLabel(row)}</Box>
        </Box>
      );
    }

    let shown = entries;
    if (q && !labelMatch) {
      const keep = entries.filter((e) => e.kind === 'page' && e.title.toLowerCase().includes(q));
      // A group label stays only when the page right under it does.
      shown = entries.filter((e, i) => (e.kind === 'page' ? keep.includes(e) : keep.includes(entries[i + 1])));
      if (!shown.some((e) => e.kind === 'page')) return null;
    }
    // While filtering every section with a hit is open; otherwise the reader's own toggles rule.
    const open = q ? true : opened.has(row.slug);
    const panelId = `docs-nav-${row.slug}`;
    return (
      <Box key={row.slug} sx={{ mt: 0.5 }}>
        <Box
          component="button"
          type="button"
          onClick={() =>
            setOpened((prev) => {
              return prev.has(row.slug) ? new Set<string>() : new Set([row.slug]);
            })
          }
          aria-expanded={open}
          aria-controls={panelId}
          sx={{
            ...rowSx(false, 0),
            width: '100%',
            border: 0,
            borderLeft: '2px solid transparent',
            font: 'inherit',
            fontSize: TYPOGRAPHY.body.size,
            textAlign: 'left',
            fontWeight: 600,
            color: isActive ? P.accentText : P.textPrimary,
          }}
        >
          {icon(row)}
          <Box component="span" sx={{ flex: 1, minWidth: 0 }}>{rowLabel(row)}</Box>
          <ExpandMore
            sx={{ fontSize: TYPOGRAPHY.navbarItem.size, flex: 'none', color: P.textMuted, transform: open ? 'none' : 'rotate(-90deg)' }}
          />
        </Box>
        {open && (
          <Box id={panelId}>
            {shown.map((e, i) =>
              e.kind === 'group' ? (
                <Box key={`g-${i}`} sx={{ pl: 1.25 + 1.5, pr: 1, pt: 0.75, pb: 0.25, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, color: P.textMuted }}>
                  {e.title}
                </Box>
              ) : (
                <Box
                  key={e.path}
                  component={RouterLink}
                  to={e.path}
                  onClick={onNavigate}
                  aria-current={e.path === currentPath ? 'page' : undefined}
                  sx={rowSx(e.path === currentPath, 1)}
                >
                  <Box component="span" sx={{ minWidth: 0, overflowWrap: 'anywhere' }}>{e.title}</Box>
                </Box>
              ),
            )}
          </Box>
        )}
      </Box>
    );
  };

  const rendered = rows.map(renderRow).filter(Boolean);

  return (
    <Box component="nav" aria-label={t('Documentation')} sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 1 }}>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 0.75,
            flex: 1,
            minWidth: 0,
            px: 1,
            height: 32,
            border: `1px solid ${P.borderColor}`,
            borderRadius: 2,
            bgcolor: P.inputBg,
            color: P.textMuted,
            '&:focus-within': { borderColor: P.accent },
          }}
        >
          <SearchOutlined sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
          <InputBase
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t('Filter documents…')}
            inputProps={{ 'aria-label': t('Filter documents…') }}
            sx={{ flex: 1, fontSize: TYPOGRAPHY.body.size, color: P.textPrimary }}
          />
        </Box>
        {onCollapse && (
          <Tooltip title={t('Hide navigation')}>
            <IconButton size="small" onClick={onCollapse} aria-label={t('Hide navigation')} sx={{ color: P.textSecondary, flex: 'none' }}>
              <ChevronLeft fontSize="small" />
            </IconButton>
          </Tooltip>
        )}
      </Box>
      <Box ref={rootRef} onScroll={(e) => { if (visible) savedScroll.current = e.currentTarget.scrollTop; }} sx={{ flex: 1, minHeight: 0, overflowY: 'auto', pb: 2 }}>
        {rendered.length ? rendered : (
          <Box sx={{ px: 1.5, py: 1, color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>{t('No document matches')}</Box>
        )}
      </Box>
    </Box>
  );
};

export default DocsNav;
