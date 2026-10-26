import { Box, Button, Checkbox, Collapse, FormControl, FormControlLabel, MenuItem, Select, Tooltip, Typography } from '@mui/material';
import { ExpandMore } from '@mui/icons-material';
import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { AppIcon } from '../../constants/icons';
import { StatTiles, primaryButtonSx } from '../common/PageChrome';
import { Chip, EntryList } from './ReleaseEntryRow';
import ReleaseUpgrade from './ReleaseUpgrade';
import {
  buildsBetween,
  countsOf,
  entriesOf,
  featureRows,
  gainText,
  groupByArea,
  mergeUpgrade,
  plainAddsInfo,
  type Build,
} from './releaseNotesParser';
import { TYPOGRAPHY } from '../../constants/typography';

interface Props {
  builds: Build[];
  fromSlug: string;
  toSlug: string;
  onChange: (from: string, to: string) => void;
  installedSlug?: string;
  canRollOut: boolean;
  /** When set, Roll out is disabled and this is the tooltip (the target build has no release tag on the core remote). */
  rollOutBlockedReason?: string;
  components: Record<string, any>;
}

const Card: React.FC<{ title: React.ReactNode; hint?: React.ReactNode; defaultOpen?: boolean; children: React.ReactNode }> = ({
  title,
  hint,
  defaultOpen = false,
  children,
}) => {
  const P = useAgentChatPalette();
  const [open, setOpen] = useState(defaultOpen);
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
        sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 2, py: 1.25, cursor: 'pointer' }}
      >
        <ExpandMore sx={{ fontSize: TYPOGRAPHY.cardTitle.size, color: P.textMuted, transform: open ? 'none' : 'rotate(-90deg)' }} />
        <Typography sx={{ fontWeight: 700 }}>{title}</Typography>
        {hint && <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}>{hint}</Typography>}
      </Box>
      <Collapse in={open} unmountOnExit>
        <Box sx={{ px: 2, pb: 1.5, borderTop: 1, borderColor: P.borderColor }}>{children}</Box>
      </Collapse>
    </Box>
  );
};

const ReleaseCompareView: React.FC<Props> = ({ builds, fromSlug, toSlug, onChange, installedSlug, canRollOut, rollOutBlockedReason, components }) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const navigate = useNavigate();
  const [showShared, setShowShared] = useState(false);
  const [showAllRows, setShowAllRows] = useState(false);

  const from = builds.find((b) => b.slug === fromSlug);
  const to = builds.find((b) => b.slug === toSlug);

  const data = useMemo(() => {
    const passed = buildsBetween(builds, fromSlug, toSlug);
    const rows = featureRows(builds, fromSlug, toSlug);
    const differing = rows.filter((r) => r.inFrom !== r.inTo);
    const sum = passed.reduce(
      (a, b) => {
        const c = countsOf(b);
        return { features: a.features + c.features, improvements: a.improvements + c.improvements, fixes: a.fixes + c.fixes + c.security, migrations: a.migrations + c.migrations };
      },
      { features: 0, improvements: 0, fixes: 0, migrations: 0 },
    );
    const fixes = passed.flatMap((b) => [...entriesOf(b, 'fixes'), ...entriesOf(b, 'list')]);
    const security = passed.flatMap((b) => entriesOf(b, 'security'));
    const improvements = groupByArea(passed.flatMap((b) => entriesOf(b, 'improvements')));
    const gained = differing.map((r) => r.entry);
    return { passed, rows, differing, sum, fixes, security, improvements, gained, upgrade: mergeUpgrade(passed) };
  }, [builds, fromSlug, toSlug]);

  if (!from || !to) return null;

  const rollback = builds.indexOf(from) < builds.indexOf(to); // To is older than From
  const rowsShown = (showShared ? data.rows : data.differing);
  const rowsCut = showAllRows ? rowsShown : rowsShown.slice(0, 8);

  const picker = (label: string, value: string, set: (slug: string) => void) => (
    <FormControl size="small" sx={{ minWidth: 220 }}>
      <Select
        value={value}
        onChange={(e) => set(e.target.value)}
        renderValue={() => (
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size }}>
            {label} · {builds.find((b) => b.slug === value)?.name}
            {value === installedSlug ? ` · ${t('installed')}` : ''}
          </Typography>
        )}
        sx={{ height: 32, bgcolor: 'background.paper' }}
      >
        {builds.map((b) => (
          <MenuItem key={b.slug} value={b.slug} sx={{ fontSize: TYPOGRAPHY.body.size }}>
            {b.title}
            {b.slug === installedSlug ? ` · ${t('installed')}` : ''}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );

  const rollOut = () => {
    const q = new URLSearchParams();
    if (from.number) q.set('from', from.number);
    if (to.number) q.set('to', to.number);
    navigate(`/configuration/platform-update${q.toString() ? `?${q}` : ''}`);
  };

  const { upgrade } = data;
  const tick = (on: boolean) => (
    <Box component="td" sx={{ textAlign: 'center', width: 100, color: on ? P.success : P.textMuted, fontWeight: 700, py: 0.6, borderBottom: 1, borderColor: P.borderColor }}>
      {on ? <AppIcon name="success" /> : '—'}
    </Box>
  );
  const th = { textAlign: 'left' as const, fontWeight: 600, color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, py: 0.6, borderBottom: 1, borderColor: P.borderColor };

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, flexWrap: 'wrap', mb: 2 }}>
        {picker(t('From'), fromSlug, (s) => onChange(s, toSlug))}
        <Box component="span" sx={{ color: P.textMuted }}>→</Box>
        {picker(t('To'), toSlug, (s) => onChange(fromSlug, s))}
      </Box>

      {data.passed.length === 0 ? (
        <Typography sx={{ color: P.textMuted, py: 2 }}>{t('Both picks are the same build — nothing to compare.')}</Typography>
      ) : (
        <>
          <StatTiles
            columns={4}
            tiles={[
              { label: rollback ? t('features lost') : t('new features'), value: data.sum.features },
              { label: rollback ? t('improvements lost') : t('improvements'), value: data.sum.improvements },
              { label: rollback ? t('bug fixes lost') : t('bug fixes'), value: data.sum.fixes },
              { label: t('DB migrations'), value: data.sum.migrations, color: data.sum.migrations ? P.accentText : undefined },
            ]}
          />

          <Card title={t('Features')} hint={t('{count} differ', { count: data.differing.length })} defaultOpen>
            <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse', fontSize: TYPOGRAPHY.body.size, mt: 1 }}>
              <thead>
                <tr>
                  <Box component="th" sx={th}>{t('Feature')}</Box>
                  <Box component="th" sx={{ ...th, display: { xs: 'none', sm: 'table-cell' } }}>{t('Added in')}</Box>
                  <Box component="th" sx={{ ...th, textAlign: 'center' }}>
                    {from.name}
                    {from.slug === installedSlug && <Box component="div" sx={{ color: P.success, fontWeight: 600 }}>{t('installed')}</Box>}
                  </Box>
                  <Box component="th" sx={{ ...th, textAlign: 'center' }}>{to.name}</Box>
                </tr>
              </thead>
              <tbody>
                {rowsCut.map((r, i) => (
                  <Box component="tr" key={i} sx={{ opacity: r.inFrom === r.inTo ? 0.55 : 1 }}>
                    <Box component="td" sx={{ py: 0.6, pr: 1, borderBottom: 1, borderColor: P.borderColor }}>
                      {r.entry.summary.replace(/[*`]/g, '')}
                      {r.entry.migration && <Box component="span" sx={{ ml: 0.75 }}><Chip accent>{t('migration')}</Chip></Box>}
                    </Box>
                    <Box component="td" sx={{ display: { xs: 'none', sm: 'table-cell' }, color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, whiteSpace: 'nowrap', borderBottom: 1, borderColor: P.borderColor }}>
                      {r.addedIn}
                    </Box>
                    {tick(r.inFrom)}
                    {tick(r.inTo)}
                  </Box>
                ))}
              </tbody>
            </Box>
            {rowsShown.length === 0 && <Typography sx={{ color: P.textMuted, py: 1, fontSize: TYPOGRAPHY.body.size }}>{t('No feature differs.')}</Typography>}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap', mt: 0.5 }}>
              {rowsShown.length > 8 && (
                <Box component="button" onClick={() => setShowAllRows((v) => !v)} sx={{ border: 0, background: 'none', color: P.accentText, cursor: 'pointer', fontSize: TYPOGRAPHY.caption.size }}>
                  {showAllRows ? t('Show fewer') : t('Show all {count}', { count: rowsShown.length })}
                </Box>
              )}
              <FormControlLabel
                control={<Checkbox size="small" checked={showShared} onChange={(e) => setShowShared(e.target.checked)} />}
                label={<Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}>{t('also show features both builds have')}</Typography>}
              />
            </Box>
          </Card>

          {plainAddsInfo(data.gained) && (
            <Card title={t('What you gain')} hint={t('in plain words')}>
              <Box component="ul" sx={{ pl: 2.5, my: 1, fontSize: TYPOGRAPHY.body.size }}>
                {data.gained
                  .filter((e) => gainText(e))
                  .map((e, i) => (
                    <li key={i}>{gainText(e)}</li>
                  ))}
              </Box>
            </Card>
          )}

          {data.improvements.length > 0 && (
            <Card title={t('Improvements')} hint={String(data.sum.improvements)}>
              {data.improvements.map((g) => (
                <EntryList key={g.slug} heading={t(g.name)} entries={g.entries} components={components} />
              ))}
            </Card>
          )}

          <Card title={t('Bug fixes')} hint={String(data.fixes.length + data.security.length)}>
            <EntryList heading={null} entries={data.fixes} components={components} limit={10} />
            <EntryList heading={t('Security')} entries={data.security} components={components} limit={10} />
          </Card>

          <Card
            title={t('Upgrade checklist')}
            hint={tn(data.passed.length, 'merged across {count} build, in order', 'merged across {count} builds, in order', { count: data.passed.length })}
            defaultOpen
          >
            <ReleaseUpgrade upgrade={upgrade} canRollOut={false} />
          </Card>

          {canRollOut && (
            <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 2 }}>
              <Tooltip title={rollOutBlockedReason ?? ''}>
                <span>
                  <Button variant="contained" onClick={rollOut} disabled={Boolean(rollOutBlockedReason)} sx={primaryButtonSx(P)}>
                    {t('Roll out this update')} →
                  </Button>
                </span>
              </Tooltip>
            </Box>
          )}
        </>
      )}
    </Box>
  );
};

export default ReleaseCompareView;
