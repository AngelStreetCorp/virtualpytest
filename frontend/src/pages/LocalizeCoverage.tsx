/**
 * Monitoring → Localize coverage (TASK-107 goal 3): per userinterface, how much of the tree Localize
 * can name — screen nodes with a pixel fingerprint, with a device identity (android activity / web
 * URL), the live node, how old the fingerprints are, and the active "Wrong screen?" corrections.
 * Reads GET /server/navigation/localize/coverage (the MCP `localize_coverage` tool reads the same).
 */
import { Alert, Box, Card, Collapse, Skeleton, MenuItem, Table, TableBody, TableCell, TableHead, TableRow, TextField, ToggleButton, ToggleButtonGroup, Typography, useMediaQuery, useTheme } from '@mui/material';
import React, { useEffect, useMemo, useState } from 'react';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';

import { PageTitle, StatTiles, pageSurfaceSx, rateColor, segmentedSx, toggleSx } from '../components/common/PageChrome';
import { TableRowsSkeleton } from '../components/common/ReportSkeleton';
import { PhoneCard } from '../components/common/PhoneCard';
import { LocalizeIntro, LocalizeTabs } from '../components/monitoring/LocalizeTabs';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { useI18n } from '../i18n/useI18n';
import { api } from '../utils/apiClient';
import { isTestInterface } from '../utils/localizeTestInterface';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { getCached, setCached } from '../utils/pageCache';
import { TYPOGRAPHY } from '../constants/typography';

export interface CoverageRow {
  userinterface_id: string;
  userinterface_name: string;
  models: string[];
  screens: number;
  fingerprinted: number;
  fingerprinted_pct: number;
  identity: number;
  identity_pct: number;
  live_node: { node_id: string; label: string } | null;
  fingerprint_age_days: { newest: number; median: number; oldest: number } | null;
  missing: string[];
  corrections: number;
  screens_to_fix?: ScreenToFix[];
}

export interface ScreenToFix {
  node_id: string;
  tree_id: string | null;
  label: string;
  reasons: Array<'no_reference' | 'no_identity' | 'old_reference'>;
  age_days: number | null;
}

type View = 'all' | 'todo' | 'ready';
type Status = 'ready' | 'partial' | 'none';
const CACHE_KEY = 'localize-coverage';
const MISSING_SHOWN = 6; // about three lines in the Still to do column

const statusOf = (r: CoverageRow): Status => (r.fingerprinted >= r.screens ? 'ready' : r.fingerprinted === 0 ? 'none' : 'partial');

const LocalizeCoverage: React.FC = () => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const theme = useTheme();
  const isPhone = useMediaQuery(theme.breakpoints.down('sm'));
  const [rows, setRows] = useState<CoverageRow[] | null>(() => getCached<CoverageRow[]>(CACHE_KEY));
  const [loading, setLoading] = useState(!getCached<CoverageRow[]>(CACHE_KEY));
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>('all');
  const [query, setQuery] = useState('');
  const [model, setModel] = useState('');
  const [params, setParams] = useSearchParams();
  const showTests = params.get('tests') === '1';
  const setShowTests = (on: boolean) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (on) next.set('tests', '1');
        else next.delete('tests');
        return next;
      },
      { replace: true },
    );
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggleOpen = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  useEffect(() => {
    let alive = true;
    api
      .get<{ success: boolean; userinterfaces: CoverageRow[]; error?: string }>(buildServerUrl('/server/navigation/localize/coverage'))
      .then((res) => {
        if (!alive) return;
        if (!res?.success) throw new Error(res?.error || 'request failed');
        setRows(res.userinterfaces || []);
        setCached(CACHE_KEY, res.userinterfaces || []);
      })
      .catch((e) => alive && setError(String(e?.message || e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const withScreens = useMemo(() => (rows || []).filter((r) => r.screens > 0), [rows]);
  const testCount = withScreens.filter((r) => isTestInterface(r.userinterface_name)).length;
  const all = useMemo(() => (showTests ? withScreens : withScreens.filter((r) => !isTestInterface(r.userinterface_name))), [withScreens, showTests]);
  const models = useMemo(() => Array.from(new Set(all.flatMap((r) => r.models))).sort(), [all]);
  // Worst first: the interfaces with the most unnamed screens lead the list.
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return all
      .filter((r) => (view === 'all' ? true : view === 'ready' ? statusOf(r) === 'ready' : statusOf(r) !== 'ready'))
      .filter((r) => !model || r.models.includes(model))
      .filter((r) => !q || r.userinterface_name.toLowerCase().includes(q))
      .sort((a, b) => b.screens - b.fingerprinted - (a.screens - a.fingerprinted) || a.userinterface_name.localeCompare(b.userinterface_name));
  }, [all, view, query, model]);

  const screens = all.reduce((n, r) => n + r.screens, 0);
  const covered = all.reduce((n, r) => n + r.fingerprinted, 0);
  const coveredPct = screens ? Math.round((1000 * covered) / screens) / 10 : 0;
  const readyCount = all.filter((r) => statusOf(r) === 'ready').length;
  const todoCount = all.length - readyCount;
  const ages = all.map((r) => r.fingerprint_age_days?.oldest).filter((d): d is number => d != null);
  const oldest = ages.length ? Math.max(...ages) : undefined;

  const toggleExpanded = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const age = (d?: number) => (d == null ? '—' : d < 1 ? t('today') : t('{n} d', { n: Math.round(d) }));
  const reasonLabel = (reason: ScreenToFix['reasons'][number], days: number | null) =>
    reason === 'no_reference'
      ? t('No reference')
      : reason === 'no_identity'
        ? t('No device identity')
        : t('Old reference ({n} d)', { n: Math.round(days ?? 0) });
  const statusLabel: Record<Status, string> = { ready: t('Ready'), partial: t('Partly taught'), none: t('Not started') };
  const statusColor: Record<Status, string> = { ready: P.success, partial: P.warning, none: P.error };

  // The table shell and its header, shared by the live table and the loading placeholder, so the
  // loading state reserves the real column widths and nothing shifts when rows arrive.
  const coverageTable = (body: React.ReactNode) => (
    <>
      <Table size="small" sx={{ tableLayout: 'fixed' }}>
      <colgroup>
        <col style={{ width: 230 }} />
        <col style={{ width: 130 }} />
        <col style={{ width: 130 }} />
        <col />
        <col style={{ width: 150 }} />
        <col style={{ width: 100 }} />
      </colgroup>
      <TableHead>
        <TableRow>
          <TableCell>{t('Interface')}</TableCell>
          <TableCell>{t('Status')}</TableCell>
          <TableCell align="right" title={t('Screens with a reference / all screens')}>{t('Taught')}</TableCell>
          <TableCell>{t('Still to do')}</TableCell>
          <TableCell align="right" title={t('Age of the newest / oldest reference on this app; over 90 days may be out of date')}>{t('Reference age')}</TableCell>
          <TableCell align="right" title={t("Times a user marked Localize wrong on this app ('Wrong screen?')")}>{t('Corrections')}</TableCell>
        </TableRow>
        </TableHead>
        <TableBody>{body}</TableBody>
      </Table>
    </>
  );

  return (
    <Box sx={pageSurfaceSx(P)}>
      <PageTitle
        title={t('Localize')}
        subtitle={
          <LocalizeIntro
            answers={t('For each app, how many of its screens Localize has a reference for, and which are still missing. Use it to know what to capture next.')}
          />
        }
        right={<LocalizeTabs />}
      />
      <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary, fontWeight: 500, mb: 1.5 }}>
        {all.length === 0
          ? t('No navigation tree has screen nodes yet.')
          : todoCount === 0
            ? t('All {total} apps are fully taught.', { total: all.length })
            : `${t('{ready} of {total} apps are fully taught;', { ready: readyCount, total: all.length })} ${tn(
                screens - covered,
                '{screens} screen still needs a reference.',
                '{screens} screens still need a reference.',
                { screens: screens - covered },
              )}`}
      </Typography>
      <StatTiles
        centered
        columns={4}
        tiles={[
          {
            label: t('Screens taught'),
            value: `${coveredPct}%`,
            extra: `${covered}/${screens}`,
            color: rateColor(coveredPct, P),
            title: t('Screens with a saved reference, over all screens of all apps'),
          },
          {
            label: t('Interfaces ready'),
            // The total continues the count ("10 / 34"), so it is part of the value: an
            // `extra` is a second figure and gets a separator (BUG-0816).
            value: (
              <>
                {readyCount}
                <Box component="span" sx={{ fontSize: TYPOGRAPHY.caption.size, fontWeight: 400, color: P.textMuted }}>
                  {' / '}{all.length}
                </Box>
              </>
            ),
            color: readyCount === all.length ? P.success : undefined,
            active: view === 'ready',
            onClick: () => setView(view === 'ready' ? 'all' : 'ready'),
            title: t('Every screen has a reference. Click to filter.'),
          },
          {
            label: t('Interfaces to finish'),
            value: todoCount,
            color: todoCount ? P.warning : P.success,
            active: view === 'todo',
            onClick: () => setView(view === 'todo' ? 'all' : 'todo'),
            title: t('At least one screen has no reference. Click to filter.'),
          },
          {
            label: t('Oldest reference'),
            value: age(oldest),
            title: t('Old references may no longer match after an app update'),
          },
        ]}
      />
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center', mb: 1.5 }}>
        <TextField size="small" placeholder={t('Search interface')} value={query} onChange={(e) => setQuery(e.target.value)} sx={{ minWidth: 220 }} />
        <TextField select size="small" value={model} onChange={(e) => setModel(e.target.value)} sx={{ minWidth: 160 }} SelectProps={{ displayEmpty: true }}>
          <MenuItem value="">{t('All device models')}</MenuItem>
          {models.map((m) => (
            <MenuItem key={m} value={m}>{m}</MenuItem>
          ))}
        </TextField>
        <ToggleButtonGroup size="small" exclusive value={view} onChange={(_, v) => v && setView(v)} sx={segmentedSx(P)}>
          <ToggleButton value="all">{t('All')}</ToggleButton>
          <ToggleButton value="todo">{t('To finish')}</ToggleButton>
          <ToggleButton value="ready">{t('Ready')}</ToggleButton>
        </ToggleButtonGroup>
        {testCount > 0 && (
          <ToggleButton
            value="tests"
            size="small"
            selected={showTests}
            onChange={() => setShowTests(!showTests)}
            sx={{ ...toggleSx(P, showTests), textTransform: 'none' }}
          >
            {t('Show test interfaces ({n})', { n: testCount })}
          </ToggleButton>
        )}
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
          {shown.length} / {all.length}
        </Typography>
      </Box>
      {error && <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert>}
      <Card>
        {loading && !rows ? (
          /* Reserve the layout this page is about to fill: a phone shows a card per app, a
             desktop the six-column table with its real header. A bare spinner reserved
             neither. */
          isPhone ? (
            <Box sx={{ p: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
              {[0, 1, 2, 3, 4].map((i) => (
                <Box key={i} sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 2, p: 1.25 }}>
                  <Skeleton variant="text" width={`${72 - i * 6}%`} height={16} animation="wave" />
                  <Skeleton variant="text" width="46%" height={13} animation="wave" sx={{ mt: 0.5 }} />
                </Box>
              ))}
            </Box>
          ) : (
            coverageTable(
              <TableRowsSkeleton rows={8} widths={['76%', '72%', '58%', '62%', '68%', '58%']} rowHeight={42} />,
            )
          )
        ) : shown.length === 0 ? (
          <Typography sx={{ p: 2, fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}>
            {all.length ? t('No interface matches these filters.') : t('No navigation tree has screen nodes yet.')}
          </Typography>
        ) : isPhone ? (
          <Box sx={{ p: 1 }}>
            {shown.map((r) => {
              const st = statusOf(r);
              const todo = r.screens - r.fingerprinted;
              const fix = r.screens_to_fix || [];
              return (
                <PhoneCard
                  key={r.userinterface_id}
                  title={<Box component="span" sx={{ fontFamily: 'monospace' }}>{r.userinterface_name}</Box>}
                  onClick={fix.length ? () => toggleOpen(r.userinterface_id) : undefined}
                  footer={
                    fix.length > 0 ? (
                      <Collapse in={open.has(r.userinterface_id)} unmountOnExit>
                        <Box sx={{ pt: 0.75 }}>
                          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, mb: 0.5 }}>
                            {t('Screens to fix ({n}). Open one in the tree editor.', { n: fix.length })}
                          </Typography>
                          {fix.map((f) => (
                            <Box key={`${f.tree_id}-${f.node_id}`} sx={{ py: 0.25 }}>
                              <Box
                                component={RouterLink}
                                to={`/navigation-editor/${encodeURIComponent(r.userinterface_name)}?node=${encodeURIComponent(f.node_id)}`}
                                onClick={(e: React.MouseEvent) => e.stopPropagation()}
                                sx={{ color: P.textPrimary, textDecoration: 'underline', fontFamily: 'monospace', fontSize: TYPOGRAPHY.body.size, overflowWrap: 'anywhere' }}
                              >
                                {f.label}
                              </Box>
                              <Box component="span" sx={{ ml: 1, fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
                                {f.reasons.map((x) => reasonLabel(x, f.age_days)).join(' · ')}
                              </Box>
                            </Box>
                          ))}
                        </Box>
                      </Collapse>
                    ) : undefined
                  }
                >
                  <Box component="span" sx={{ color: statusColor[st], fontWeight: 600 }}>{statusLabel[st]}</Box>
                  <span>
                    {t('Taught')} <Box component="span" sx={{ color: rateColor(r.fingerprinted_pct, P), fontWeight: 600 }}>{r.fingerprinted}/{r.screens}</Box>
                  </span>
                  {todo > 0 && <span>{todo} {todo === 1 ? t('screen to capture') : t('screens to capture')}</span>}
                </PhoneCard>
              );
            })}
          </Box>
        ) : coverageTable(
            shown.map((r) => {
                const st = statusOf(r);
                const todo = r.screens - r.fingerprinted;
                const fix = r.screens_to_fix || [];
                const isOpen = open.has(r.userinterface_id);
                return (
                  <React.Fragment key={r.userinterface_id}>
                  <TableRow
                    hover={fix.length > 0}
                    onClick={fix.length ? () => toggleOpen(r.userinterface_id) : undefined}
                    sx={{ cursor: fix.length ? 'pointer' : 'default', '& > td': { borderBottom: isOpen ? 'none' : undefined } }}
                  >
                    <TableCell sx={{ wordBreak: 'break-word', verticalAlign: 'top' }}>
                      <Box sx={{ fontFamily: 'monospace', fontSize: TYPOGRAPHY.body.size }}>{r.userinterface_name}</Box>
                      {r.models.length > 0 && (
                        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                          {r.models.map((m) => (
                            <Box
                              key={m}
                              component="span"
                              sx={{ px: 0.75, borderRadius: 1, border: `1px solid ${P.borderColor}`, fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}
                            >
                              {m}
                            </Box>
                          ))}
                        </Box>
                      )}
                    </TableCell>
                    <TableCell>
                      <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75, color: statusColor[st], fontWeight: 600 }}>
                        <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: statusColor[st] }} />
                        {statusLabel[st]}
                      </Box>
                    </TableCell>
                    <TableCell align="right">
                      <Box component="span" sx={{ color: rateColor(r.fingerprinted_pct, P), fontWeight: 600 }}>{r.fingerprinted_pct}%</Box>
                      <Box component="span" sx={{ ml: 0.75, fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{r.fingerprinted}/{r.screens}</Box>
                    </TableCell>
                    <TableCell sx={{ wordBreak: 'break-word', verticalAlign: 'top', color: todo ? P.textPrimary : P.textMuted }}>
                      {todo ? (
                        <>
                          {`${todo} ${todo === 1 ? t('screen to capture') : t('screens to capture')}: ${(expanded.has(r.userinterface_id) ? r.missing : r.missing.slice(0, MISSING_SHOWN)).join(', ')}`}
                          {r.missing.length > MISSING_SHOWN && (
                            <Box
                              component="span"
                              role="button"
                              tabIndex={0}
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleExpanded(r.userinterface_id);
                              }}
                              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && toggleExpanded(r.userinterface_id)}
                              sx={{ ml: 0.75, cursor: 'pointer', color: P.textMuted, textDecoration: 'underline' }}
                            >
                              {expanded.has(r.userinterface_id) ? t('Show less') : t('+{n} more', { n: r.missing.length - MISSING_SHOWN })}
                            </Box>
                          )}
                        </>
                      ) : (
                        '—'
                      )}
                    </TableCell>
                    <TableCell align="right" sx={{ color: P.textSecondary }}>
                      {r.fingerprint_age_days ? `${age(r.fingerprint_age_days.median)} / ${age(r.fingerprint_age_days.oldest)}` : '—'}
                    </TableCell>
                    <TableCell align="right" sx={{ color: r.corrections ? P.textPrimary : P.textMuted }}>{r.corrections}</TableCell>
                  </TableRow>
                  {fix.length > 0 && (
                    <TableRow>
                      <TableCell colSpan={6} sx={{ py: 0, borderBottom: isOpen ? undefined : 'none' }}>
                        <Collapse in={isOpen} unmountOnExit>
                          <Box sx={{ py: 1, pl: 2 }}>
                            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, mb: 0.5 }}>
                              {t('Screens to fix ({n}). Open one in the tree editor.', { n: fix.length })}
                            </Typography>
                            {fix.map((f) => (
                              <Box key={`${f.tree_id}-${f.node_id}`} sx={{ display: 'flex', gap: 1.5, alignItems: 'baseline', py: 0.25, flexWrap: 'wrap' }}>
                                <Box
                                  component={RouterLink}
                                  to={`/navigation-editor/${encodeURIComponent(r.userinterface_name)}?node=${encodeURIComponent(f.node_id)}`}
                                  sx={{ color: P.textPrimary, textDecoration: 'underline', fontFamily: 'monospace', fontSize: TYPOGRAPHY.body.size }}
                                >
                                  {f.label}
                                </Box>
                                <Box component="span" sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
                                  {f.reasons.map((x) => reasonLabel(x, f.age_days)).join(' · ')}
                                </Box>
                              </Box>
                            ))}
                          </Box>
                        </Collapse>
                      </TableCell>
                    </TableRow>
                  )}
                  </React.Fragment>
                );
              }),
          )}
      </Card>
    </Box>
  );
};

export default LocalizeCoverage;
