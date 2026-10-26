import { Box, IconButton, Tooltip } from '@mui/material';
import {
  ChevronRight,
  DownloadOutlined,
  LinkOutlined,
  PrintOutlined,
  CheckOutlined,
  CodeOutlined,
  FormatListBulletedOutlined,
  MenuOutlined,
} from '@mui/icons-material';
import React from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import type { DocsCrumb } from './docsManifest';
import { copyText, useFlash } from './DocsReaderParts';
import { exportMarkdownPdf } from './exportMarkdownPdf';
import { neutralButtonSx, toggleSx } from '../common/PageChrome';
import { DOCS_BAR_HEIGHT } from './docsLayout';
import { READER_SIZES, type ReaderSize } from './docsPrefs';

/** Breadcrumb: Docs › Section › Page. The last crumb is the current page and not a link. */
export const DocsBreadcrumb: React.FC<{ crumbs: DocsCrumb[] }> = ({ crumbs }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const all: DocsCrumb[] = [{ title: t('Docs'), path: '/docs/README' }, ...crumbs];
  return (
    <Box
      component="nav"
      aria-label={t('Breadcrumb')}
      sx={{ display: 'flex', alignItems: 'center', gap: 0.25, minWidth: 0, fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}
    >
      {all.map((c, i) => {
        const last = i === all.length - 1;
        return (
          <React.Fragment key={`${c.title}-${i}`}>
            {i > 0 && <ChevronRight sx={{ fontSize: TYPOGRAPHY.navbarItem.size, flex: 'none' }} />}
            {c.path && !last ? (
              <Box component={RouterLink} to={c.path} sx={{ color: P.textMuted, textDecoration: 'none', whiteSpace: 'nowrap', '&:hover': { color: P.accentText } }}>
                {i === 1 ? t(c.title) : c.title}
              </Box>
            ) : (
              <Box
                component="span"
                aria-current={last ? 'page' : undefined}
                sx={{ color: last ? P.textPrimary : P.textMuted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}
              >
                {i === 1 ? t(c.title) : c.title}
              </Box>
            )}
          </React.Fragment>
        );
      })}
    </Box>
  );
};

interface Props {
  /** Raw markdown source, for Download and Print. */
  markdown: string;
  /** The page title, drawn in the bar (empty = none). */
  title: string;
  /** Icon before the title (section homes). */
  icon?: React.ReactNode;
  /** Source file under docs/, e.g. "/get-started/local-dev.md" (the download's file name). */
  mdPath: string;
  readerSize: ReaderSize;
  onReaderSize: (size: ReaderSize) => void;
  /** Special views (release notes, galleries) have no markdown source: only the toggles show. */
  showActions: boolean;
  /** Left toggle: the navigation rail (undefined = not available at this width). */
  navOpen?: boolean;
  onNavToggle?: () => void;
  /** Right toggle: the "On this page" rail. */
  tocOpen?: boolean;
  onTocToggle?: () => void;
  /** The page has no outline: the toggle is replaced by an empty slot of the same width. */
  tocDisabled?: boolean;
  /** Page holds `<div data-technical>` blocks: show the switch. */
  hasTechnical?: boolean;
  showTechnical?: boolean;
  onShowTechnical?: (v: boolean) => void;
}

/**
 * The reader card's header bar: ONE row, sticky under the navbar. Left: the navigation toggle and the section
 * pill. Right: text size, Copy link, Download, Print and the outline toggle. A collapsed rail leaves no strip behind;
 * its toggle lives here, so it stays reachable while the page scrolls.
 */
const DocsPageHeader: React.FC<Props> = ({ markdown, title, icon, mdPath, readerSize, onReaderSize, showActions, navOpen, onNavToggle, tocOpen, onTocToggle, tocDisabled, hasTechnical, showTechnical = false, onShowTechnical }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [copied, flash] = useFlash();

  const download = () => {
    const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(mdPath.split('/').pop() ?? 'document.md') || 'document.md'}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  // Icon-only, neutral role, 30 px square; the tooltip and aria-label carry the words.
  const btn = { ...(neutralButtonSx(P) as object), width: 30, height: 30, borderRadius: 1, flexShrink: 0 } as const;
  const iconSx = { fontSize: TYPOGRAPHY.navbarItem.size } as const;
  const action = (label: string, onClick: () => void, icon: React.ReactNode, disabled = false, expanded?: boolean) => (
    <Tooltip title={label} describeChild>
      {/* span: a disabled button cannot hold the tooltip's listeners */}
      <span>
        <IconButton size="small" aria-label={label} aria-expanded={expanded} onClick={onClick} disabled={disabled} sx={btn}>
          {icon}
        </IconButton>
      </span>
    </Tooltip>
  );

  const toggle = (open: boolean, onToggle: () => void, hide: string, show: string, icon: React.ReactNode, disabled = false) =>
    action(open ? hide : show, onToggle, icon, disabled, open);

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        flexWrap: 'nowrap',
        height: DOCS_BAR_HEIGHT,
        mb: 2.25,
        mx: { xs: -2, md: -3.5 },
        px: 1.5,
        borderBottom: `1px solid ${P.borderColor}`,
        color: P.textMuted,
        fontSize: TYPOGRAPHY.caption.size,
        position: 'sticky',
        // Flush under the navbar (top 0 of the scroll column): a gap above it would let scrolled text show through.
        // The rails keep DOCS_STICKY_TOP; the bar is the card's own header, so it sits against the navbar.
        top: 0,
        zIndex: 2,
        bgcolor: 'background.paper',
      }}
    >
      {onNavToggle && toggle(!!navOpen, onNavToggle, t('Hide navigation'), t('Show navigation'), <MenuOutlined sx={iconSx} />)}
      {title && (
        <Box component="h1" sx={{ m: 0, minWidth: 0, flex: 1, display: 'flex', alignItems: 'center', gap: 1, color: P.textPrimary, fontSize: TYPOGRAPHY.sectionTitle.size, fontWeight: TYPOGRAPHY.sectionTitle.weight, lineHeight: 1.2 }}>
          {icon}
          <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}</Box>
        </Box>
      )}
      <Box sx={{ ml: 'auto', display: 'flex', alignItems: 'center', gap: 0.5 }}>
        {showActions && (<>
        {hasTechnical && onShowTechnical && (
          <>
            <Tooltip title={showTechnical ? t('Hide technical details') : t('Show technical details')} describeChild>
              <IconButton
                size="small"
                aria-label={showTechnical ? t('Hide technical details') : t('Show technical details')}
                aria-pressed={showTechnical}
                onClick={() => onShowTechnical(!showTechnical)}
                sx={{ ...btn, ...(toggleSx(P, showTechnical) as object) }}
              >
                <CodeOutlined sx={iconSx} />
              </IconButton>
            </Tooltip>
            <Box sx={{ width: 6 }} />
          </>
        )}
        <Box role="group" aria-label={t('Text size')} sx={{ display: 'flex', alignItems: 'center' }}>
          {READER_SIZES.map((size) => {
            const on = size === readerSize;
            const name = size === 's' ? t('Text size: Small') : size === 'm' ? t('Text size: Medium') : t('Text size: Large');
            return (
              <Tooltip key={size} title={name} describeChild>
                <Box
                  component="button"
                  type="button"
                  aria-pressed={on}
                  aria-label={name}
                  onClick={() => onReaderSize(size)}
                  sx={{
                    // Fixed slot: the weight change on selection must not move the neighbours.
                    width: 26,
                    height: 30,
                    p: 0,
                    border: 0,
                    borderBottom: '2px solid',
                    borderColor: on ? P.accent : 'transparent',
                    bgcolor: 'transparent',
                    cursor: 'pointer',
                    font: 'inherit',
                    fontSize: TYPOGRAPHY.body.size,
                    textAlign: 'center',
                    fontWeight: on ? 600 : 400,
                    color: on ? P.accentText : P.textSecondary,
                    '&:hover': { color: P.accentText },
                    '&:focus-visible': { outline: `2px solid ${P.accent}`, outlineOffset: -2 },
                  }}
                >
                  {/* i18n-ignore: S / M / L size letters */}
                  {size.toUpperCase()}
                </Box>
              </Tooltip>
            );
          })}
        </Box>
        <Box sx={{ width: 6 }} />
        {action(copied ? t('Copied') : t('Copy link'), async () => { if (await copyText(window.location.href)) flash(); }, copied ? <CheckOutlined sx={iconSx} /> : <LinkOutlined sx={iconSx} />)}
        {action(t('Download'), download, <DownloadOutlined sx={iconSx} />)}
        {action(t('Print'), () => exportMarkdownPdf(markdown, title, showTechnical), <PrintOutlined sx={iconSx} />)}
        </>)}
        {/* A page with no outline has no toggle (never a greyed one). An empty 30 px slot keeps the other icons at the
            same x as on pages that do have it, so nothing jumps between pages. */}
        {onTocToggle && (tocDisabled
          ? <Box aria-hidden sx={{ width: 30, height: 30, flexShrink: 0 }} />
          : toggle(!!tocOpen, onTocToggle, t('Hide outline'), t('Show outline'), <FormatListBulletedOutlined sx={iconSx} />))}
      </Box>
    </Box>
  );
};

export default DocsPageHeader;
