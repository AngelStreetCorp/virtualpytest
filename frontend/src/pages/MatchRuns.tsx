import {
  Alert,
  Box,
  Card,
  CardContent,
  CircularProgress,
  Collapse,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material';
import React, { useMemo, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';

// ui-ok: table-layout — every table here is a short list (<30 rows), short cells,
// and using `tableLayout: 'fixed'` made columns drop digits when the row count
// changed (see ui-check ratchet for context).  Column widths are not user-resizable
// but the per-tile rhythm in PageChrome already constrains them.

import { StackedBar } from '../components/analytics/Charts';
import { PageTitle, pageSurfaceSx, StatTiles, rateColor, toggleSx } from '../components/common/PageChrome';
import { PhoneCard } from '../components/common/PhoneCard';
import { RunWrongScreen } from '../components/navigation/RunWrongScreen';
import { MatchRunFrame } from '../components/monitoring/MatchRunFrame';
import { LocalizeIntro, LocalizeTabs } from '../components/monitoring/LocalizeTabs';
import { APP_CONFIG } from '../config/constants';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import {
  MatchRun,
  MatchRunDeviceRow,
  MatchRunDistributionRow,
  MatchRunsWindow,
  useDeviceRuns,
  useMatchRuns,
} from '../hooks/pages/useMatchRuns';
import { TYPOGRAPHY } from '../constants/typography';
import { useI18n } from '../i18n/useI18n';

// A trend vs the previous window is only meaningful with at least this many runs there.
const MIN_PREVIOUS_RUNS_FOR_TREND = 20;
const WINDOWS: MatchRunsWindow[] = ['1h', '6h', '24h', '7d'];
const TIME_OPTS: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit', second: '2-digit' };

const score = (n: number | null | undefined, digits = 2): string =>
  n === null || n === undefined ? '—' : Number(n).toFixed(digits);

const pct = (n: number, denom: number): string => {
  if (!denom) return '—';
  return `${((100 * n) / denom).toFixed(1)}%`;
};

const verdictLabels: Record<string, string> = {
  known_node: 'named',
  low_confidence: 'low score',
  no_signal: 'no signal',
  unknown: 'not named',
  overlay: 'overlay',
};

const verdictColor = (v: string, P: ReturnType<typeof useAgentChatPalette>): string => {
  if (v === 'known_node') return P.accent;
  if (v === 'unknown' || v === 'low_confidence') return P.error;
  if (v === 'no_signal') return P.textMuted;
  return P.textSecondary;
};

const MatchRuns: React.FC = () => {
  const P = useAgentChatPalette();
  const { t, tn, formatDate } = useI18n();
  const teamId = APP_CONFIG.DEFAULT_TEAM_ID;
  const theme = useTheme();
  const isPhone = useMediaQuery(theme.breakpoints.down('sm'));
  const [windowSel, setWindowSel] = useState<MatchRunsWindow>('24h');

  const { recent, uncertain, summary, previous, perDevice, distribution, loading, error, lastFetchedAt, lastErrorAt, refetch } =
    useMatchRuns({ teamId: teamId || '', window: windowSel, refreshMs: 10_000 });

  const [picked, setPicked] = useState<{ host: string; device: string | null } | null>(null);
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const [showIdle, setShowIdle] = useState(false);

  const isIdleDevice = (d: MatchRunDeviceRow) => d.total > 0 && d.matched === 0 && d.unknown === d.total;
  const idleCount = perDevice.filter(isIdleDevice).length;
  const visibleDevices = showIdle ? perDevice : perDevice.filter((d) => !isIdleDevice(d));

  const totalRuns = summary?.total ?? recent.length;
  const matchedCount = summary?.matched ?? 0;
  const uncertainCount = summary?.uncertain ?? 0;
  const unknownCount = summary?.unknown_or_low_conf ?? 0;
  const matchRate = totalRuns ? matchedCount / totalRuns : 0;
  const unknownRate = totalRuns ? unknownCount / totalRuns : 0;
  const avgConfidence = summary?.avg_confidence ?? null;

  // Trend: named rate now vs the window of equal length right before.
  const prevTotal = previous?.total ?? 0;
  const prevRate = prevTotal ? (previous?.matched ?? 0) / prevTotal : null;
  const deltaPts = prevRate != null && prevTotal >= MIN_PREVIOUS_RUNS_FOR_TREND && totalRuns ? (matchRate - prevRate) * 100 : null;
  const signed = (n: number) => `${n < 0 ? '−' : '+'}${Math.abs(n).toFixed(1)}`;
  const trendColor = deltaPts == null || Math.abs(deltaPts) < 0.05 ? P.textMuted : deltaPts > 0 ? P.success : P.error;
  const windowLabels: Record<MatchRunsWindow, string> = {
    '1h': t('the last hour'),
    '6h': t('the last 6 h'),
    '24h': t('the last 24 h'),
    '7d': t('the last 7 days'),
  };
  const weakest = visibleDevices
    .filter((d) => d.total >= 5)
    .sort((a, b) => a.matched / a.total - b.matched / b.total || b.total - a.total)[0];
  const trendWords =
    deltaPts == null
      ? ''
      : Math.round(deltaPts) === 0
        ? ` (${t('unchanged')})`
        : ` (${deltaPts > 0 ? t('up {n} pts', { n: Math.round(deltaPts) }) : t('down {n} pts', { n: Math.round(-deltaPts) })})`;
  const summarySentence = !totalRuns
    ? t('No runs in {window}.', { window: windowLabels[windowSel] })
    : `${t('In {window} Localize named the screen in {rate} % of {total} runs', {
        window: windowLabels[windowSel],
        rate: Math.round(matchRate * 100),
        total: totalRuns,
      })}${trendWords}.${
        weakest
          ? ` ${t('Weakest device: {device}, {rate} % of {total}.', {
              device: weakest.device_name ? `${weakest.host_name || '—'} / ${weakest.device_name}` : weakest.host_name || '—',
              rate: Math.round((100 * weakest.matched) / weakest.total),
              total: weakest.total,
            })}`
          : ''
      }`;

  // Close calls: one line per (interface, picked screen, second guess), newest first.
  const closeCallGroups = useMemo(() => {
    const map = new Map<string, { key: string; ui: string; picked: string; second: string; runs: MatchRun[]; last: string; minGap: number | null }>();
    uncertain.forEach((r) => {
      const picked = r.candidates_top_3?.[0]?.label || '—';
      const second = r.candidates_top_3?.[1]?.label || '—';
      const key = `${r.userinterface_name}|${picked}|${second}`;
      const g = map.get(key) || { key, ui: r.userinterface_name, picked, second, runs: [], last: r.started_at, minGap: null };
      g.runs.push(r);
      if (r.started_at > g.last) g.last = r.started_at;
      if (r.runner_up_margin != null && (g.minGap == null || r.runner_up_margin < g.minGap)) g.minGap = r.runner_up_margin;
      map.set(key, g);
    });
    const groups = Array.from(map.values());
    groups.forEach((g) => g.runs.sort((a, b) => (a.started_at < b.started_at ? 1 : -1)));
    return groups.sort((a, b) => (a.last < b.last ? 1 : -1));
  }, [uncertain]);
  const toggleGroup = (key: string) =>
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  // Group distribution rows into timeseries buckets for the stacked bar.
  // `bucket` keys are full ISO timestamps; we render the HH:MM portion so
  // the X axis stays compact (the StackedBar prefers short tick labels).
  const distributionData = useMemo(() => {
    const byBucket = new Map<string, Record<string, number | string>>();
    distribution.forEach((d: MatchRunDistributionRow) => {
      const row = byBucket.get(d.bucket) || { bucket: formatDate(d.bucket, { hour: '2-digit', minute: '2-digit' }) };
      row[d.verdict] = (Number(row[d.verdict]) || 0) + d.count;
      byBucket.set(d.bucket, row);
    });
    return Array.from(byBucket.values());
  }, [distribution, formatDate]);

  return (
    <Box sx={pageSurfaceSx(P)}>
      <PageTitle
        title={t('Localize')}
        subtitle={
          <LocalizeIntro
            answers={t('How often Localize named the screen in real runs, per device. Use it to check Localize works before you test.')}
          />
        }
        right={
          <>
            <ToggleButtonGroup
              value={windowSel}
              exclusive
              size="small"
              onChange={(_, v) => v && setWindowSel(v as MatchRunsWindow)}
              sx={{ '& .MuiToggleButton-root': { color: P.textSecondary, borderColor: P.borderColor } }}
            >
              {WINDOWS.map((w) => (
                <ToggleButton key={w} value={w}>{w}</ToggleButton>
              ))}
            </ToggleButtonGroup>
            <Typography
              variant="caption"
              sx={{ color: P.textMuted, cursor: 'pointer', userSelect: 'none' }}
              onClick={refetch}
            >
              ↻ {t('Refresh')}
            </Typography>
            <LocalizeTabs />
          </>
        }
      />
      <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary, fontWeight: 500, mb: 1 }}>{summarySentence}</Typography>
      <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, mb: 1.5 }}>
        {lastFetchedAt ? t('Updated {time}', { time: formatDate(lastFetchedAt, TIME_OPTS) }) : '…'}
        {lastErrorAt && (
          <Box component="span" sx={{ color: P.error, ml: 1 }}>
            · {t('last refresh failed at {time} (showing prior data)', { time: formatDate(lastErrorAt, TIME_OPTS) })}
          </Box>
        )}
      </Typography>

      {/* Panel 1: live status strip */}
      <StatTiles
        large
        phoneTwoUp
        sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', sm: 'repeat(auto-fill, minmax(220px, 1fr))', lg: 'repeat(6, minmax(0, 1fr))' } }}
        tiles={[
          { label: t('Total runs'), value: totalRuns, extra: t('window {window}', { window: windowSel }), color: P.textPrimary },
          {
            label: t('Named'),
            value: pct(matchedCount, totalRuns),
            color: rateColor(matchRate * 100, P),
            extra: (
              <>
                {tn(totalRuns, '{matched} of {count} run', '{matched} of {count} runs', { matched: matchedCount })}
                {(deltaPts != null || (previous && previous.total < MIN_PREVIOUS_RUNS_FOR_TREND)) && ' · '}
                <Box component="span" sx={{ color: trendColor }}>
                  {deltaPts != null
                    ? t('{delta} pts vs previous {window}', { delta: signed(deltaPts), window: windowSel })
                    : previous && previous.total === 0
                      ? t('no runs in the previous {window}', { window: windowSel })
                      : previous && previous.total < MIN_PREVIOUS_RUNS_FOR_TREND
                        ? tn(previous.total, 'only {count} run in the previous {window}', 'only {count} runs in the previous {window}', { window: windowSel })
                        : ''}
                </Box>
              </>
            ),
            title: t('Runs where Localize named the screen, out of all runs'),
          },
          {
            label: t('Close calls'),
            value: pct(uncertainCount, matchedCount),
            color: uncertainCount > 0 ? P.warning : P.textMuted,
            extra: t('{uncertain} of {matched} named', { uncertain: uncertainCount, matched: matchedCount }),
            title: t('The second guess scored within 5 % of the first: check these screens'),
          },
          {
            label: t('Not named'),
            value: pct(unknownCount, totalRuns),
            color: rateColor(100 - unknownRate * 100, P),
            extra: tn(unknownCount, '{count} run', '{count} runs'),
            title: t('Runs where Localize could not name the screen, or only with a low score'),
          },
          {
            label: t('Active devices'),
            value: summary?.distinct_devices ?? 0,
            extra: tn(summary?.distinct_hosts ?? 0, '{count} host', '{count} hosts'),
          },
          { label: t('Average score'), value: score(avgConfidence), extra: t('named runs only') },
        ]}
      />

      {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
          <CircularProgress size={24} sx={{ color: P.accent }} />
        </Box>
      )}

      {/* Panel 2: verdict distribution */}
      <Card sx={{ mt: 2, bgcolor: P.surface, border: `1px solid ${P.borderColor}` }}>
        <CardContent>
          <Typography variant="h6" sx={{ color: P.textPrimary, mb: 1 }}>{t('Results per hour')}</Typography>
          {distributionData.length === 0 ? (
            <Typography variant="body2" sx={{ color: P.textMuted }}>{t('No runs in this period. Pick a longer one or run a verify.')}</Typography>
          ) : (
            <StackedBar
              data={distributionData as Array<Record<string, unknown>>}
              xKey="bucket"
              series={[
                { key: 'known_node', label: t('named'), color: P.success },
                { key: 'low_confidence', label: t('low score'), color: P.warning },
                { key: 'no_signal', label: t('no signal'), color: P.textMuted },
                { key: 'unknown', label: t('not named'), color: P.error },
                { key: 'overlay', label: t('overlay'), color: P.accent },
              ]}
              height={220}
              shortenDates={false}
            />
          )}
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, mt: 1 }}>
            {t('No signal: black or missing video. Overlay: a popup or banner covered the screen.')}
          </Typography>
        </CardContent>
      </Card>

      {/* Panel 3: per-device heatmap */}
      <Card sx={{ mt: 2, bgcolor: P.surface, border: `1px solid ${P.borderColor}` }}>
        <CardContent>
          <Typography variant="h6" sx={{ color: P.textPrimary, mb: 0.5 }}>{t('Per device')}</Typography>
          {perDevice.length === 0 ? (
            <Typography variant="body2" sx={{ color: P.textMuted }}>{t('No device activity in this period.')}</Typography>
          ) : (
            <>
            {idleCount > 0 && (
              <ToggleButton
                value="idle"
                size="small"
                selected={showIdle}
                onChange={() => setShowIdle(!showIdle)}
                sx={{ ...toggleSx(P, showIdle), textTransform: 'none', mb: 1 }}
              >
                {t('Show devices with nothing named ({n})', { n: idleCount })}
              </ToggleButton>
            )}
            {isPhone ? (
              <Box>
                {visibleDevices.slice(0, 30).map((d: MatchRunDeviceRow) => {
                  const rate = d.total ? d.matched / d.total : 0;
                  return (
                    <PhoneCard
                      key={`${d.host_name}-${d.device_name}`}
                      title={`${d.host_name || '—'} / ${d.device_name || t('(host only)')}`}
                      selected={picked?.host === d.host_name && picked?.device === (d.device_name || null)}
                      onClick={() => setPicked({ host: d.host_name, device: d.device_name || null })}
                    >
                      <Box component="span" sx={{ color: rateColor(rate * 100, P), fontWeight: 600 }}>{pct(d.matched, d.total)}</Box>
                      <span>{tn(d.total, '{count} run', '{count} runs')}</span>
                      <span>{t('Last seen')} {d.last_match_at ? formatDate(d.last_match_at) : '—'}</span>
                    </PhoneCard>
                  );
                })}
              </Box>
            ) : (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ color: P.textMuted }}>{t('Host')}</TableCell>
                    <TableCell sx={{ color: P.textMuted }}>{t('Device')}</TableCell>
                    <TableCell sx={{ color: P.textMuted }}>{t('Named')}</TableCell>
                    <TableCell sx={{ color: P.textMuted }} align="right">{t('Runs')}</TableCell>
                    <TableCell sx={{ color: P.textMuted }} align="right">{t('Named')}</TableCell>
                    <TableCell sx={{ color: P.textMuted }} align="right">{t('Close calls')}</TableCell>
                    <TableCell sx={{ color: P.textMuted }} align="right">{t('Not named')}</TableCell>
                    <TableCell sx={{ color: P.textMuted }}>{t('Last seen')}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {visibleDevices.slice(0, 30).map((d: MatchRunDeviceRow) => {
                    const rate = d.total ? d.matched / d.total : 0;
                    return (
                      <TableRow
                        key={`${d.host_name}-${d.device_name}`}
                        hover
                        sx={{ cursor: 'pointer' }}
                        selected={picked?.host === d.host_name && picked?.device === (d.device_name || null)}
                        onClick={() => setPicked({ host: d.host_name, device: d.device_name || null })}
                      >
                        <TableCell sx={{ color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size }}>{d.host_name || '—'}</TableCell>
                        <TableCell sx={{ color: P.textPrimary, fontSize: TYPOGRAPHY.caption.size }}>{d.device_name || <span style={{ color: P.textMuted }}>{t('(host only)')}</span>}</TableCell>
                        <TableCell>
                          <Stack direction="row" alignItems="center" spacing={1}>
                            <Box
                              title={t('{matched} of {total} named ({rate})', { matched: d.matched, total: d.total, rate: `${(rate * 100).toFixed(1)}%` })}
                              sx={{ width: 160, height: 6, borderRadius: 3, bgcolor: P.hoverBg, border: `1px solid ${P.borderColor}`, overflow: 'hidden' }}
                            >
                              <Box sx={{ width: `${Math.round(rate * 100)}%`, height: '100%', bgcolor: rateColor(rate * 100, P) }} />
                            </Box>
                            <Typography variant="caption" sx={{ color: rateColor(rate * 100, P), fontWeight: 600 }}>
                              {pct(d.matched, d.total)}
                            </Typography>
                          </Stack>
                        </TableCell>
                        <TableCell align="right" sx={{ color: P.textPrimary, fontSize: TYPOGRAPHY.caption.size }}>{d.total}</TableCell>
                        <TableCell align="right" sx={{ color: P.textPrimary, fontSize: TYPOGRAPHY.caption.size }}>{d.matched}</TableCell>
                        <TableCell align="right" sx={{ color: d.uncertain > 0 ? P.warning : P.textMuted, fontSize: TYPOGRAPHY.caption.size }}>{d.uncertain}</TableCell>
                        <TableCell align="right" sx={{ color: d.unknown > 0 ? P.error : P.textMuted, fontSize: TYPOGRAPHY.caption.size }}>{d.unknown}</TableCell>
                        <TableCell sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size }}>
                          {d.last_match_at ? formatDate(d.last_match_at) : '—'}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </TableContainer>
            )}
            {!showIdle && idleCount > 0 && (
              <Typography variant="caption" sx={{ display: 'block', mt: 1, color: P.textMuted }}>
                {t('{n} devices hidden: Localize named nothing on them in this window — usually no references were captured for their app.', { n: idleCount })}
              </Typography>
            )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Panel 4: uncertain hits backlog (top 20, sorted by margin asc) */}
      <Card sx={{ mt: 2, bgcolor: P.surface, border: `1px solid ${P.borderColor}` }}>
        <CardContent>
          <Typography variant="h6" sx={{ color: P.textPrimary, mb: 0.5 }}>{t('Close calls to check')}</Typography>
          <Typography variant="body2" sx={{ color: P.textMuted, mb: 1 }}>
            {t('The second guess scored within 5 % of the first. Open the screenshot; if Localize picked the wrong screen, recapture one of the two screens in the tree editor.')}
          </Typography>
          {isPhone ? (
            <Box>
              {closeCallGroups.slice(0, 20).map((g) => (
                <PhoneCard
                  key={g.key}
                  title={`${g.picked} → ${g.second}`}
                  onClick={() => toggleGroup(g.key)}
                  footer={
                    <Collapse in={openGroups.has(g.key)} unmountOnExit>
                      <Box sx={{ pt: 0.75 }}>
                        {g.runs.map((r) => (
                          <Box key={r.id} sx={{ display: 'flex', gap: 1.5, alignItems: 'center', py: 0.25, flexWrap: 'wrap', fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
                            <span>{formatDate(r.started_at)}</span>
                            <span>{t('Gap')} {score(r.runner_up_margin, 3)}</span>
                            <span onClick={(e) => e.stopPropagation()}><MatchRunFrame frameUrl={r.frame_url} hostName={r.host_name} /></span>
                          </Box>
                        ))}
                      </Box>
                    </Collapse>
                  }
                >
                  <span>{g.ui}</span>
                  <span>{t('seen {n} times, last {time}', { n: g.runs.length, time: formatDate(g.last) })}</span>
                  <Box component="span" sx={{ color: P.error, fontWeight: 600 }}>{t('Smallest gap')} {score(g.minGap, 3)}</Box>
                </PhoneCard>
              ))}
              {!closeCallGroups.length && (
                <Typography variant="body2" sx={{ color: P.textMuted, textAlign: 'center', py: 2 }}>
                  {t('No close calls: every named screen has a clear gap to the second guess.')}
                </Typography>
              )}
            </Box>
          ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ color: P.textMuted }}>{t('Seen')}</TableCell>
                  <TableCell sx={{ color: P.textMuted }}>{t('Interface')}</TableCell>
                  <TableCell sx={{ color: P.textMuted }}>{t('Picked')}</TableCell>
                  <TableCell sx={{ color: P.textMuted }}>{t('Second guess')}</TableCell>
                  <TableCell sx={{ color: P.textMuted }}>{t('Smallest gap')}</TableCell>
                  <TableCell sx={{ color: P.textMuted }}>{t('Screenshot')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {closeCallGroups.slice(0, 20).map((g) => {
                  const isOpen = openGroups.has(g.key);
                  return (
                    <React.Fragment key={g.key}>
                      <TableRow hover sx={{ cursor: 'pointer', '& > td': { borderBottom: isOpen ? 'none' : undefined } }} onClick={() => toggleGroup(g.key)}>
                        <TableCell sx={{ color: P.textPrimary, fontSize: TYPOGRAPHY.caption.size }}>
                          {t('seen {n} times, last {time}', { n: g.runs.length, time: formatDate(g.last) })}
                        </TableCell>
                        <TableCell sx={{ color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size, wordBreak: 'break-word' }}>{g.ui}</TableCell>
                        <TableCell sx={{ color: P.textPrimary, fontSize: TYPOGRAPHY.caption.size }}>{g.picked}</TableCell>
                        <TableCell sx={{ color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size }}>{g.second}</TableCell>
                        <TableCell sx={{ color: P.error, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600 }}>{score(g.minGap, 3)}</TableCell>
                        <TableCell sx={{ fontSize: TYPOGRAPHY.caption.size }}>
                          <MatchRunFrame frameUrl={g.runs[0].frame_url} hostName={g.runs[0].host_name} />
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell colSpan={6} sx={{ py: 0, borderBottom: isOpen ? undefined : 'none' }}>
                          <Collapse in={isOpen} unmountOnExit>
                            <Box sx={{ py: 1, pl: 2 }}>
                              {g.runs.map((r) => (
                                <Box key={r.id} sx={{ display: 'flex', gap: 2, alignItems: 'center', py: 0.25, flexWrap: 'wrap', fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
                                  <span>{formatDate(r.started_at)}</span>
                                  <span>{r.host_name} / {r.device_name || t('(host only)')}</span>
                                  <span>{t('Gap')} {score(r.runner_up_margin, 3)}</span>
                                  <MatchRunFrame frameUrl={r.frame_url} hostName={r.host_name} />
                                </Box>
                              ))}
                            </Box>
                          </Collapse>
                        </TableCell>
                      </TableRow>
                    </React.Fragment>
                  );
                })}
                {!closeCallGroups.length && (
                  <TableRow>
                    <TableCell colSpan={6} sx={{ color: P.textMuted, textAlign: 'center', py: 3 }}>
                      {t('No close calls: every named screen has a clear gap to the second guess.')}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
          )}
        </CardContent>
      </Card>

      {/* Panel 5: recent runs of the picked device */}
      {picked && <DeviceRunsPanel P={P} teamId={teamId || ''} host={picked.host} device={picked.device} onClose={() => setPicked(null)} />}
    </Box>
  );
};

/** The screen a run named, as a link to that node in the tree editor (plain text when none was named). */
const NamedScreen: React.FC<{ r: MatchRun; P: ReturnType<typeof useAgentChatPalette> }> = ({ r, P }) => {
  const label = r.candidates_top_3?.[0]?.label || r.matched_node_id || '—';
  if (r.verdict !== 'known_node' || !r.matched_node_id) return <>{r.verdict === 'known_node' ? label : '—'}</>;
  return (
    <Box
      component={RouterLink}
      to={`/navigation-editor/${encodeURIComponent(r.userinterface_name)}?node=${encodeURIComponent(r.matched_node_id)}`}
      sx={{ color: P.textPrimary, textDecoration: 'underline' }}
    >
      {label}
    </Box>
  );
};

const RESULT_ORDER = ['known_node', 'unknown', 'low_confidence', 'no_signal', 'overlay'];

/** "Recent runs on <host>/<device>": the last 50 runs of one device, filterable by result. */
const DeviceRunsPanel: React.FC<{
  P: ReturnType<typeof useAgentChatPalette>;
  teamId: string;
  host: string;
  device: string | null;
  onClose: () => void;
}> = ({ P, teamId, host, device, onClose }) => {
  const { t, formatDate } = useI18n();
  const theme = useTheme();
  const isPhone = useMediaQuery(theme.breakpoints.down('sm'));
  const filters = useMemo(() => ({ teamId, hostName: host, deviceName: device, limit: 50 }), [teamId, host, device]);
  const { rows, loading, error } = useDeviceRuns(filters);
  const [result, setResult] = useState<string>('all');
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    rows.forEach((r) => {
      c[r.verdict] = (c[r.verdict] || 0) + 1;
    });
    return c;
  }, [rows]);
  const shown = result === 'all' ? rows : rows.filter((r) => r.verdict === result);
  const name = `${host} / ${device || t('(host only)')}`;

  return (
    <Card sx={{ mt: 2, bgcolor: P.surface, border: `1px solid ${P.borderColor}` }}>
      <CardContent>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 1 }}>
          <Typography variant="h6" sx={{ color: P.textPrimary, mb: 0.5 }}>{t('Recent runs on {device}', { device: name })}</Typography>
          <Typography variant="caption" role="button" tabIndex={0} sx={{ color: P.textMuted, cursor: 'pointer', textDecoration: 'underline' }} onClick={onClose}>
            {t('Close')}
          </Typography>
        </Box>
        <Typography variant="body2" sx={{ color: P.textMuted, mb: 1 }}>
          {t('The last 50 runs on this device, newest first, with the three screens Localize scored highest.')}
        </Typography>
        <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mb: 1.5 }}>
          <ToggleButton value="all" size="small" selected={result === 'all'} onChange={() => setResult('all')} sx={{ ...toggleSx(P, result === 'all'), textTransform: 'none' }}>
            {t('All')} ({rows.length})
          </ToggleButton>
          {RESULT_ORDER.filter((v) => counts[v]).map((v) => (
            <ToggleButton key={v} value={v} size="small" selected={result === v} onChange={() => setResult(result === v ? 'all' : v)} sx={{ ...toggleSx(P, result === v), textTransform: 'none' }}>
              {t(verdictLabels[v])} ({counts[v]})
            </ToggleButton>
          ))}
        </Box>
        {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
        {loading && rows.length === 0 && <CircularProgress size={20} sx={{ color: P.accent }} />}
        {!loading && !error && shown.length === 0 && (
          <Typography variant="body2" sx={{ color: P.textMuted }}>{t('No runs for this device yet.')}</Typography>
        )}
        {shown.length > 0 && isPhone && (
          <Box>
            {shown.map((r: MatchRun) => (
              <PhoneCard key={r.id} title={r.verdict === 'known_node' ? (r.candidates_top_3?.[0]?.label || r.matched_node_id || '—') : (verdictLabels[r.verdict] ? t(verdictLabels[r.verdict]) : r.verdict)}>
                <Box component="span" sx={{ color: verdictColor(r.verdict, P), fontWeight: 600 }}>
                  {verdictLabels[r.verdict] ? t(verdictLabels[r.verdict]) : r.verdict}
                  {r.verdict === 'known_node' && r.matched_confidence != null && ` ${score(r.matched_confidence)}`}
                </Box>
                <span>{formatDate(r.started_at)}</span>
                <span>{r.userinterface_name}</span>
                {r.verdict === 'known_node' && r.matched_node_id && <NamedScreen r={r} P={P} />}
                <MatchRunFrame frameUrl={r.frame_url} hostName={r.host_name} />
                {r.has_fingerprint && <RunWrongScreen run={r} teamId={teamId} />}
              </PhoneCard>
            ))}
          </Box>
        )}
        {shown.length > 0 && !isPhone && (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ color: P.textMuted }}>{t('Started')}</TableCell>
                  <TableCell sx={{ color: P.textMuted }}>{t('Interface')}</TableCell>
                  <TableCell sx={{ color: P.textMuted }}>{t('Result')}</TableCell>
                  <TableCell sx={{ color: P.textMuted }}>{t('Screen named')}</TableCell>
                  <TableCell sx={{ color: P.textMuted }}>{t('Top 3 guesses')}</TableCell>
                  <TableCell sx={{ color: P.textMuted }}>{t('Screenshot')}</TableCell>
                  <TableCell />
                </TableRow>
              </TableHead>
              <TableBody>
                {shown.map((r: MatchRun) => (
                  <TableRow key={r.id}>
                    <TableCell sx={{ color: P.textPrimary, fontSize: TYPOGRAPHY.caption.size }}>{formatDate(r.started_at)}</TableCell>
                    <TableCell sx={{ color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size, wordBreak: 'break-word' }}>{r.userinterface_name}</TableCell>
                    <TableCell sx={{ color: verdictColor(r.verdict, P), fontSize: TYPOGRAPHY.caption.size, fontWeight: 600 }}>
                      {verdictLabels[r.verdict] ? t(verdictLabels[r.verdict]) : r.verdict}
                    </TableCell>
                    <TableCell sx={{ color: P.textPrimary, fontSize: TYPOGRAPHY.caption.size }}>
                      <NamedScreen r={r} P={P} />
                      {r.verdict === 'known_node' && r.matched_confidence != null && (
                        <Box component="span" sx={{ ml: 0.75, color: P.textMuted }}>{score(r.matched_confidence)}</Box>
                      )}
                    </TableCell>
                    <TableCell sx={{ fontSize: TYPOGRAPHY.caption.size }}>
                      {r.candidates_top_3?.length ? (
                        r.candidates_top_3.slice(0, 3).map((c) => (
                          <Box key={c.rank} sx={{ color: c.rank === 1 ? P.textPrimary : P.textSecondary }}>
                            {c.label || '—'} <Box component="span" sx={{ color: P.textMuted }}>{score(c.score)}</Box>
                          </Box>
                        ))
                      ) : (
                        <span style={{ color: P.textMuted }}>—</span>
                      )}
                    </TableCell>
                    <TableCell><MatchRunFrame frameUrl={r.frame_url} hostName={r.host_name} /></TableCell>
                    <TableCell>{r.has_fingerprint && <RunWrongScreen run={r} teamId={teamId} />}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </CardContent>
    </Card>
  );
};

export default MatchRuns;
