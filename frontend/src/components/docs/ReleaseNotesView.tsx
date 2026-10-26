import {
  Box,
  Button,
  Checkbox,
  Collapse,
  FormControlLabel,
  FormControl,
  IconButton,
  InputAdornment,
  MenuItem,
  Select,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material';
import {
  AutoAwesomeOutlined,
  BugReportOutlined,
  ExpandMore,
  LockOutlined,
  SettingsOutlined,
  PictureAsPdfOutlined,
} from '@mui/icons-material';
import React, { useContext, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { createDocsMarkdownComponents, createInlineDocsMarkdownComponents } from './markdownComponents';
import { exportMarkdownPdf } from './exportMarkdownPdf';
import ReleaseCompareView from './ReleaseCompareView';
import ReleaseUpgrade from './ReleaseUpgrade';
import { findCoreTag, useBundleSources } from '../../hooks/platformUpdate/useBundleSources';
import { Chip, EntryList, urlTransform } from './ReleaseEntryRow';
import {
  AREAS,
  countsOf,
  groupByArea,
  entriesOf,
  entryMatches,
  mergeUpgrade,
  parseReleaseNotes,
  resolveVersionToBuild,
  type Build,
} from './releaseNotesParser';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { AppIcon } from '../../constants/icons';
import { ServerManagerContext } from '../../contexts/ServerManagerContext';
import { useProfile } from '../../hooks/auth/useProfile';
import { useI18n } from '../../i18n/useI18n';
import { segmentedSx, neutralButtonSx } from '../common/PageChrome';
import { TYPOGRAPHY } from '../../constants/typography';

const useIsAdmin = (): boolean => {
  try {
    return useProfile().isAdmin;
  } catch {
    return false; // no AuthProvider (tests, embedded use)
  }
};

const AREA_ICON: Record<string, React.ComponentProps<typeof AppIcon>['name']> = {
  'device-control': 'device',
  monitoring: 'report',
  testing: 'play',
  ai: 'ai',
  integrations: 'link',
  platform: 'settings',
  entertainment: 'star',
};

const AreaHeading: React.FC<{ slug: string; name: string }> = ({ slug, name }) => {
  const { t } = useI18n();
  return (
    <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
      <AppIcon name={AREA_ICON[slug] ?? 'layers'} />
      {t(name)}
    </Box>
  );
};

const SectionHeading: React.FC<{ icon: React.ElementType; label: string }> = ({ icon: Icon, label }) => (
  <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
    <Icon sx={{ fontSize: TYPOGRAPHY.cardTitle.size, color: 'text.secondary' }} aria-hidden />
    {label}
  </Box>
);

/** One of the three parts of a build (Features, Improvements, Bug fixes): own band, own header, collapsible. */
const SectionBlock: React.FC<{
  icon: React.ElementType;
  title: string;
  count: number;
  tone?: 'accent';
  dashed?: boolean;
  defaultOpen?: boolean;
  force?: boolean;
  children: React.ReactNode;
}> = ({ icon, title, count, tone, dashed, defaultOpen = false, force = false, children }) => {
  const P = useAgentChatPalette();
  const [open, setOpen] = useState(defaultOpen);
  if (count === 0) return null;
  const shown = force || open;
  return (
    <Box sx={{ mt: 1.25, border: 1, borderStyle: dashed ? 'dashed' : 'solid', borderColor: P.borderColor, borderRadius: 1.5, overflow: 'hidden' }}>
      <Box
        role="button"
        tabIndex={0}
        aria-expanded={shown}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setOpen((v) => !v);
          }
        }}
        sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.5, py: 0.75, cursor: 'pointer', bgcolor: tone === 'accent' ? `${P.accent}1f` : P.hoverBg }}
      >
        <ExpandMore sx={{ fontSize: TYPOGRAPHY.cardTitle.size, color: P.textMuted, transform: shown ? 'none' : 'rotate(-90deg)' }} />
        <SectionHeading icon={icon} label={title} />
        <Box component="span" sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>{count}</Box>
      </Box>
      <Collapse in={shown} unmountOnExit>
        <Box sx={{ px: 1.5, pb: 1, borderTop: 1, borderColor: P.borderColor }}>{children}</Box>
      </Collapse>
    </Box>
  );
};

const BuildCard: React.FC<{
  build: Build;
  q: string;
  defaultOpen: boolean;
  installed: boolean;
  next: boolean;
  area: string | null;
  showInternal: boolean;
  canRollOut: boolean;
  blockComponents: Record<string, any>;
  inlineComponents: Record<string, any>;
}> = ({ build, q, defaultOpen, installed, next, area, showInternal, canRollOut, blockComponents, inlineComponents }) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const [openState, setOpen] = useState(defaultOpen);
  // Narrowing to one build (picker or link) opens it; the reader can still close it afterwards.
  useEffect(() => {
    if (defaultOpen) setOpen(true);
  }, [defaultOpen]);
  const open = q ? true : openState;

  const counts = countsOf(build);
  const pick = (kind: 'features' | 'improvements' | 'fixes' | 'security' | 'internal' | 'list') =>
    entriesOf(build, kind).filter((e) => entryMatches(e, q) && (!area || kind === 'fixes' || kind === 'security' || kind === 'list' || kind === 'internal' || e.area === area));
  const features = groupByArea(pick('features'));
  const improvements = groupByArea(pick('improvements'));
  const improvementCount = improvements.reduce((n, g) => n + g.entries.length, 0);
  const internal = showInternal ? pick('internal') : [];
  const fixes = [...pick('fixes'), ...pick('list')];
  const security = pick('security');
  const upgrade = build.subsections.filter((s) => s.kind === 'upgrade');
  const others = build.subsections.filter((s) => s.kind === 'other' && s.body.trim());
  const merged = mergeUpgrade([build]);
  return (
    <Box sx={{ border: 1, borderColor: P.borderColor, borderRadius: 2, bgcolor: P.surface, mb: 1.5, overflow: 'hidden' }}>
      <Box
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setOpen((v) => !v);
          }
        }}
        sx={{ display: 'flex', alignItems: 'center', gap: 1.25, px: 2, py: 1.25, flexWrap: 'wrap', cursor: 'pointer' }}
      >
        <ExpandMore sx={{ fontSize: TYPOGRAPHY.cardTitle.size, color: P.textMuted, transform: open ? 'none' : 'rotate(-90deg)' }} />
        <Typography component="h2" sx={{ fontWeight: 700, fontSize: TYPOGRAPHY.navbarItem.size }}>{build.name}</Typography>
        {build.date && <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>{build.date}</Typography>}
        {installed && <Chip accent>{t('installed')}</Chip>}
        {next && <Chip accent>{t('coming')}</Chip>}
        <Box sx={{ ml: 'auto', display: 'flex', gap: 1.75, color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, flexWrap: 'wrap' }}>
          {counts.features > 0 && <span><b>{counts.features}</b> {tn(counts.features, 'feature', 'features')}</span>}
          {counts.improvements > 0 && <span><b>{counts.improvements}</b> {tn(counts.improvements, 'improvement', 'improvements')}</span>}
          {counts.fixes > 0 && <span><b>{counts.fixes}</b> {tn(counts.fixes, 'fix', 'fixes')}</span>}
          {counts.migrations > 0 && <span><b>{counts.migrations}</b> {tn(counts.migrations, 'migration', 'migrations')}</span>}
          {counts.security > 0 && <span><b>{counts.security}</b> {t('security')}</span>}
        </Box>
      </Box>
      <Collapse in={open} unmountOnExit>
        <Box sx={{ px: 2, pb: 1.75, pt: 0.5, borderTop: 1, borderColor: P.borderColor }}>
          <SectionBlock icon={AutoAwesomeOutlined} title={t('Features')} count={features.reduce((n, g) => n + g.entries.length, 0)} tone="accent" defaultOpen force={Boolean(q)}>
            {features.map((g) => (
              <EntryList key={g.slug} heading={<AreaHeading slug={g.slug} name={g.name} />} entries={g.entries} components={inlineComponents} />
            ))}
          </SectionBlock>
          <SectionBlock icon={AutoAwesomeOutlined} title={t('Improvements')} count={improvementCount} force={Boolean(q)}>
            {improvements.map((g) => (
              <EntryList key={g.slug} heading={<AreaHeading slug={g.slug} name={g.name} />} entries={g.entries} components={inlineComponents} />
            ))}
          </SectionBlock>
          <SectionBlock icon={BugReportOutlined} title={fixes.length && !pick('fixes').length ? t('Bugs') : t('Bug fixes')} count={fixes.length} force={Boolean(q)} defaultOpen={features.length + improvementCount === 0}>
            <EntryList heading={null} entries={fixes} components={inlineComponents} limit={10} />
          </SectionBlock>
          <SectionBlock icon={LockOutlined} title={t('Security')} count={security.length} force={Boolean(q)} defaultOpen>
            <EntryList heading={null} entries={security} components={inlineComponents} />
          </SectionBlock>
          <SectionBlock icon={SettingsOutlined} title={t('System')} count={internal.length} dashed defaultOpen>
            <EntryList heading={null} entries={internal} components={inlineComponents} />
          </SectionBlock>
          <EntryList heading={t('Internal')} entries={internal} components={inlineComponents} />
          {others.map((s, i) => (
            <Box key={i} sx={{ mt: 1.5 }}>
              {s.heading && <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.navbarItem.size }}>{s.heading}</Typography>}
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} urlTransform={urlTransform} components={blockComponents}>
                {s.body}
              </ReactMarkdown>
            </Box>
          ))}
          {(upgrade.length > 0 || canRollOut) && <ReleaseUpgrade upgrade={merged} canRollOut={canRollOut} to={build.number} />}
        </Box>
      </Collapse>
    </Box>
  );
};

/**
 * Release notes and the bug tracker: one card per build with counts, one-line rows, a filter, and
 * (release notes only) a Compare mode between two builds with a roll-out button.
 */
const ReleaseNotesView: React.FC<{
  markdown: string;
  getCurrentDocPath: () => string;
  page?: string;
  title?: string;
  /** `bugs` swaps the header link and hides Compare. */
  kind?: 'release_note' | 'bugs';
}> = ({ markdown, getCurrentDocPath, page, title, kind = 'release_note' }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const isAdmin = useIsAdmin();
  const serverCtx = useContext(ServerManagerContext);
  const installedVersion = serverCtx?.serverHostsData?.[0]?.server_info?.deployed_version ?? null;
  const builds = useMemo(() => parseReleaseNotes(markdown), [markdown]);
  const blockComponents = useMemo(() => createDocsMarkdownComponents(getCurrentDocPath, page, P), [getCurrentDocPath, page, P]);
  const inlineComponents = useMemo(() => createInlineDocsMarkdownComponents(getCurrentDocPath, page, P), [getCurrentDocPath, page, P]);
  const [searchParams, setSearchParams] = useSearchParams();

  const installed = useMemo(() => resolveVersionToBuild(installedVersion, builds), [installedVersion, builds]);
  const nextBuild = builds[0]?.unreleased ? builds[0] : undefined;
  const compare = kind === 'release_note' && searchParams.get('view') === 'compare';
  const q = searchParams.get('q') ?? '';

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v); else next.delete(k);
    }
    setSearchParams(next, { replace: true });
  };

  // A ?list= naming nothing is treated like no parameter (a stale link must not hide the page).
  const picked = builds.find((b) => b.slug === searchParams.get('list'));
  const area = AREAS.find((a) => a.slug === searchParams.get('area'))?.slug ?? null;
  const [showInternal, setShowInternal] = useState(false);
  const internalCount = builds.reduce((n, b) => n + entriesOf(b, 'internal').length, 0);
  // A build with no entry at all (only a tag, nothing user-facing) is noise in the list.
  const listed = builds.filter((b) => b.subsections.some((s) => s.entries.length > 0));
  const visible = (picked ? [picked] : listed).filter(
    (b) => !q || b.subsections.some((s) => s.entries.some((e) => entryMatches(e, q))),
  );

  const fromSlug = builds.find((b) => b.slug === searchParams.get('from'))?.slug ?? installed?.slug ?? builds[Math.min(1, builds.length - 1)]?.slug ?? '';
  const toSlug = builds.find((b) => b.slug === searchParams.get('to'))?.slug ?? builds[0]?.slug ?? '';

  // Admin on the compare view only: ask the core remote once which builds are published, so Roll out is not offered for one it cannot provide.
  const bundleSources = useBundleSources();
  const { load: loadBundleSources } = bundleSources;
  useEffect(() => {
    if (compare && isAdmin) void loadBundleSources();
  }, [compare, isAdmin, loadBundleSources]);
  const toNumber = builds.find((b) => b.slug === toSlug)?.number;
  const core = bundleSources.sources?.core.github;
  const rollOutBlockedReason =
    compare && isAdmin && core?.usable && toNumber && !findCoreTag(core.refs, toNumber)
      ? t('Build {number} has no release tag on {remote}. Pick a published build or use a zip.', { number: toNumber, remote: core.remote })
      : undefined;

  const downloadPdf = () => {
    const h1 = title || t('Release Notes');
    const body = compare
      ? `## ${builds.find((b) => b.slug === fromSlug)?.title} → ${builds.find((b) => b.slug === toSlug)?.title}\n\n${markdown}`
      : markdown;
    exportMarkdownPdf(`# ${h1}\n\n${body}`, `VirtualPyTest ${h1} ${new Date().toISOString().slice(0, 10)}`);
  };

  const otherHref = kind === 'bugs' ? '/docs/release_note' : '/docs/bugs';

  return (
    <Box sx={{ fontFamily: 'Inter, "Segoe UI", system-ui, -apple-system, sans-serif' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 1, flexWrap: 'wrap', mb: 1.5 }}>
          <>
    {kind === 'release_note' && (
      <ToggleButtonGroup
        exclusive
        size="small"
        value={compare ? 'compare' : 'builds'}
        onChange={(_, v) => v && update({ view: v === 'compare' ? 'compare' : null, from: null, to: null })}
        sx={segmentedSx(P)}
      >
        <ToggleButton value="builds">{t('Builds')}</ToggleButton>
        <ToggleButton value="compare">{t('Compare')}</ToggleButton>
      </ToggleButtonGroup>
    )}
            <Tooltip title={compare ? t('Download this comparison as PDF') : t('Download the full document as PDF (choose “Save as PDF” in the print dialog)')}>
              <IconButton size="small" onClick={downloadPdf} aria-label={t('Download as PDF')} sx={{ ...(neutralButtonSx(P) as object), borderRadius: 1 }}>
                <PictureAsPdfOutlined fontSize="small" />
              </IconButton>
            </Tooltip>
            <Button
              size="small"
              href={otherHref}
              target="_blank"
              rel="noopener"
              sx={neutralButtonSx(P)}
            >
              {kind === 'bugs' ? t('Release notes') : t('Bugs')}
            </Button>
          </>
      </Box>

      <Box sx={{ display: 'flex', gap: 1.25, alignItems: 'center', flexWrap: 'wrap', mb: 2 }}>
        {!compare && (
          <TextField
            size="small"
            value={q}
            onChange={(e) => update({ q: e.target.value || null })}
            placeholder={t('Filter by text, BUG-, TASK-…')}
            inputProps={{ 'aria-label': t('Filter') }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start"><AppIcon name="search" /></InputAdornment>
              ),
            }}
            sx={{ flex: 1, minWidth: 180, '& .MuiInputBase-root': { height: 32, fontSize: TYPOGRAPHY.body.size } }}
          />
        )}
        {!compare && listed.length > 1 && (
          <FormControl size="small" sx={{ width: 240 }}>
            <Select
              value={picked?.slug ?? ''}
              onChange={(e) => update({ list: e.target.value || null })}
              displayEmpty
              inputProps={{ 'aria-label': t('Build') }}
              renderValue={() => (
                <Typography noWrap sx={{ fontSize: TYPOGRAPHY.body.size }}>{picked?.title ?? t('All builds')}</Typography>
              )}
              sx={{ height: 32, bgcolor: 'background.paper' }}
            >
              <MenuItem value="" sx={{ fontSize: TYPOGRAPHY.body.size }}>{t('All builds')}</MenuItem>
              {listed.map((b) => (
                <MenuItem key={b.slug} value={b.slug} sx={{ fontSize: TYPOGRAPHY.body.size }}>{b.title}</MenuItem>
              ))}
            </Select>
          </FormControl>
        )}
        {!compare && kind === 'release_note' && (
          <FormControl size="small" sx={{ width: 200 }}>
            <Select
              value={area ?? ''}
              onChange={(e) => update({ area: e.target.value || null })}
              displayEmpty
              inputProps={{ 'aria-label': t('Area') }}
              renderValue={() => (
                <Typography noWrap sx={{ fontSize: TYPOGRAPHY.body.size }}>
                  {area ? t(AREAS.find((a) => a.slug === area)?.name ?? '') : t('All areas')}
                </Typography>
              )}
              sx={{ height: 32, bgcolor: 'background.paper' }}
            >
              <MenuItem value="" sx={{ fontSize: TYPOGRAPHY.body.size }}>{t('All areas')}</MenuItem>
              {AREAS.map((a) => (
                <MenuItem key={a.slug} value={a.slug} sx={{ fontSize: TYPOGRAPHY.body.size }}>{t(a.name)}</MenuItem>
              ))}
            </Select>
          </FormControl>
        )}
        {!compare && kind === 'release_note' && isAdmin && (
          <FormControlLabel
            control={<Checkbox size="small" checked={showInternal} onChange={(e) => setShowInternal(e.target.checked)} />}
            label={<Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}>{t('Show system')}{internalCount > 0 && ` (${internalCount})`}</Typography>}
          />
        )}
      </Box>

      {compare ? (
        <ReleaseCompareView
          builds={builds}
          fromSlug={fromSlug}
          toSlug={toSlug}
          onChange={(f, to) => update({ from: f, to })}
          installedSlug={installed?.slug}
          canRollOut={isAdmin}
          rollOutBlockedReason={rollOutBlockedReason}
          components={inlineComponents}
        />
      ) : (
        <>
          {visible.map((b) => (
            <BuildCard
              key={b.slug}
              build={b}
              q={q}
              defaultOpen={b.unreleased || b.slug === installed?.slug || visible.length === 1}
              installed={b.slug === installed?.slug}
              next={b.slug === nextBuild?.slug}
              area={area}
              showInternal={showInternal && isAdmin}
              canRollOut={isAdmin}
              blockComponents={blockComponents}
              inlineComponents={inlineComponents}
            />
          ))}
          {visible.length === 0 && <Typography sx={{ color: P.textMuted, py: 3 }}>{t('Nothing matches this filter.')}</Typography>}
        </>
      )}
    </Box>
  );
};

export default ReleaseNotesView;
