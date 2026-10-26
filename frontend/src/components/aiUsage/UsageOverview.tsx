/**
 * AI usage, level 1 (TASK-147): four tiles (Spend, Calls, Failing now, Wasted), calls or spend over time, then the
 * calls by provider and by feature / user / host (Calls, Cost or Failed). A row opens its group; Spend opens the budgets.
 * On the 30-day view (daily rollup, no parse / truncation data) the fourth tile is Failed, and a run of days that
 * are almost all failures at many times the usual volume is named as an incident (the October no-credit storm).
 */
import { Box, Link, ToggleButton, ToggleButtonGroup } from '@mui/material';
import React, { useState } from 'react';

import { segmentedSx } from '../common/PageChrome';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { formatDate } from '../../i18n';
import { useI18n } from '../../i18n/useI18n';

import { UsageQuery, UsageReport, fetchAiUsage, fetchBenchmarks } from './api';
import { StackedBars } from './charts';
import { fmtCost, fmtCount, fmtPct, fmtTime } from './format';
import { categoryLabel } from './labels';
import { featureQuality, profileQuality } from './quality';
import { Metric, MetricSwitch, ShareItem, ShareList, TileRow, UsageCard, UsageTile, costView, deltaText } from './usageParts';
import { useAiLoad } from './useAiLoad';

export type GroupDim = 'feature' | 'user' | 'host';

export interface OverviewNav {
  provider: (endpoint: string) => void;
  group: (dim: GroupDim, key: string) => void;
  view: (view: 'budget' | 'training') => void;
}

interface Props {
  report: UsageReport;
  /** The same period grouped by provider: the cost of each provider. */
  byProvider: UsageReport | null;
  query: UsageQuery;
  nav: OverviewNav;
  onExport: () => void;
}

/** Days that are almost all failures at many times the usual volume: an incident, not the usual waste. */
export const incidentSlots = (calls: number[], failed: number[]): number[] => {
  const sorted = [...calls].filter((v) => v > 0).sort((a, b) => a - b);
  const median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;
  return calls.map((v, i) => (median && v >= 5 * median && (failed[i] ?? 0) / v >= 0.9 ? i : -1)).filter((i) => i >= 0);
};

export const UsageOverview: React.FC<Props> = ({ report, byProvider, query, nav, onExport }) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const [metric, setMetric] = useState<Metric>('calls');
  const [dim, setDim] = useState<GroupDim>('feature');
  const [chartSpend, setChartSpend] = useState(false);
  const byDim = useAiLoad('usage by ' + dim, () => fetchAiUsage(query, dim), [dim, query.hours, query.team, query.project], dim !== 'feature');

  // Quality per feature: the benchmark pass rate of the profiles it used, weighted by calls. One fetch for the page.
  const bench = useAiLoad('benchmarks', () => fetchBenchmarks({ limit: 500, hours: query.hours }), [query.hours], metric === 'quality');

  const T = report.totals;
  const split = report.overview?.totals;
  const prev = report.previous;
  const calls = T.series ?? [];
  const failed = T.failed_series ?? [];
  const cost = T.cost_series;
  // Hourly buckets: failures of the last 2 h. Daily buckets (30 d): the last day, named as such.
  const hourly = (report.step_s ?? 3600) <= 3600;
  const rollup = report.source === 'rollup';
  const failingNow = hourly ? failed.slice(-2).reduce((a, v) => a + v, 0) : failed[failed.length - 1] ?? 0;
  const wasted = rollup ? T.errors : split?.wasted ?? T.errors;
  const answered = calls.map((v, i) => v - (failed[i] ?? 0));
  const degraded = (report.providers ?? []).find((p) => p.status === 'down') ?? (report.providers ?? []).find((p) => p.status === 'degraded');
  const since = degraded?.since ?? report.errors?.causes?.find((c) => c.endpoint === degraded?.endpoint)?.since;
  const costOf = Object.fromEntries((byProvider?.rows ?? []).map((r) => [r.key, r]));
  const errorsOf = Object.fromEntries(report.rows.map((r) => [r.key, r.errors]));
  const names = report.overview?.category_labels;

  const planEndpoints = new Set((report.providers ?? []).filter((p) => p.plan).map((p) => p.endpoint));
  // Calls on a flat plan cost nothing per call: they are not "missing a price".
  const planCalls = (byProvider?.rows ?? []).filter((r) => planEndpoints.has(r.key)).reduce((a, r) => a + Math.max(0, r.calls - r.errors - (r.priced_calls ?? 0)), 0);
  // An older server sends no priced_calls: the cost stays a plain amount.
  const spend = costView(T.cost, T.calls, T.errors ?? 0, T.priced_calls == null ? undefined : T.priced_calls + planCalls, tn, t);
  const spendHint = [spend.hint, T.cache_saved ? t('Prompt cache saved {cost}', { cost: fmtCost(T.cache_saved) ?? '' }) : ''].filter(Boolean).join(' · ') || undefined;

  const incident = hourly ? [] : incidentSlots(calls, failed);
  const dayOf = (i: number) => (report.series_start ? formatDate(new Date(new Date(report.series_start).getTime() + i * (report.step_s ?? 86400) * 1000), { day: '2-digit', month: '2-digit' }) : '');
  const incidentDates = incident.length ? (incident.length === 1 ? dayOf(incident[0]) : `${dayOf(incident[0])}–${dayOf(incident[incident.length - 1])}`) : '';
  const outside = (s: number[]) => s.reduce((a, v, i) => (incident.includes(i) ? a : a + v), 0);
  const rateWithout = incident.length && outside(calls) ? outside(failed) / outside(calls) : null;

  const providers: ShareItem[] = (report.providers ?? []).filter((p) => p.calls > 0).map((p) => ({ key: p.endpoint, name: p.name, calls: p.calls, failed: p.errors, cost: costOf[p.endpoint]?.cost ?? null, priced: p.plan ? undefined : costOf[p.endpoint]?.priced_calls }));
  // A feature is graded on its own usage keys only: a profile's score on another feature says nothing here.
  const runs = bench.data?.runs ?? [];
  const profilesOf = Object.fromEntries(report.rows.map((r) => [r.key, r.profiles]));
  const features: ShareItem[] = dim === 'feature'
    ? (report.overview?.categories ?? []).map((c) => ({ key: c.key, name: categoryLabel(c.key, t, names), calls: c.calls, failed: errorsOf[c.key] ?? 0, cost: c.cost, quality: featureQuality(profilesOf[c.key], profileQuality(runs, c.key)) }))
    : (byDim.data?.rows ?? []).map((r) => ({ key: r.key, name: r.label || r.key, calls: r.calls, failed: r.errors, cost: r.cost, priced: r.priced_calls }));
  const link = { fontSize: TYPOGRAPHY.body.size, cursor: 'pointer' } as const;
  const dims: GroupDim[] = rollup ? ['feature', 'host'] : ['feature', 'user', 'host'];
  const dimLabel: Record<GroupDim, string> = { feature: t('Feature'), user: t('User'), host: t('Host') };

  return (
    <Box>
      <TileRow>
        <UsageTile label={t('Spend')} value={spend.text} hint={spendHint} caption={deltaText(T.cost, prev?.cost) ? `${deltaText(T.cost, prev?.cost)} ${t('vs previous')}` : undefined} onClick={() => nav.view('budget')} />
        <UsageTile
          label={t('Calls')}
          value={fmtCount(T.calls)}
          chart={<Box sx={{ width: '70%' }}><StackedBars answered={answered} failed={failed} height={22} /></Box>}
          caption={deltaText(T.calls, prev?.calls) ? `${deltaText(T.calls, prev?.calls)} ${t('vs previous')}` : undefined}
        />
        <UsageTile
          label={hourly ? t('Failing now') : t('Failed today')}
          value={fmtCount(failingNow)}
          color={failingNow ? P.error : P.success}
          caption={degraded
            ? (degraded.status === 'down' ? t('{name} down since {time}', { name: degraded.name, time: fmtTime(since) }) : t('{name} degraded', { name: degraded.name }))
            : T.last_error_ts ? t('last failure {time}', { time: fmtTime(T.last_error_ts) }) : t('No failure')}
          onClick={degraded ? () => nav.provider(degraded.endpoint) : undefined}
        />
        <UsageTile
          label={rollup ? t('Failed') : t('Wasted')}
          hint={rollup ? t('Calls that got no answer') : t('Failed, unreadable or cut off')}
          value={T.calls ? fmtPct(wasted / T.calls) : '—'}
          color={rateWithout != null ? P.error : undefined}
          caption={rateWithout != null
            ? t('{pct} without {dates}', { pct: fmtPct(rateWithout), dates: incidentDates })
            : `${tn(wasted, '{count} call', '{count} calls', { count: fmtCount(wasted) })} · ${fmtCost(split?.cost_wasted ?? null) ?? '—'}`}
        />
      </TileRow>

      <UsageCard
        title={chartSpend ? (hourly ? t('Spend per hour') : t('Spend per day')) : (hourly ? t('Calls per hour') : t('Calls per day'))}
        right={
          <>
            {incidentDates && <Box component="span" sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.error, fontWeight: 600 }}>{t('Incident {dates}', { dates: incidentDates })}</Box>}
            {!chartSpend && <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}><Box component="span" sx={{ width: 8, height: 8, borderRadius: 0.5, bgcolor: P.error }} />{t('failed')}</Box>}
            {cost && (
              <ToggleButtonGroup exclusive size="small" value={chartSpend ? 'spend' : 'calls'} onChange={(_, v: string | null) => v && setChartSpend(v === 'spend')} sx={segmentedSx(P, 'sm')}>
                <ToggleButton value="calls" disableRipple>{t('Calls')}</ToggleButton>
                <ToggleButton value="spend" disableRipple>{t('Spend')}</ToggleButton>
              </ToggleButtonGroup>
            )}
          </>
        }
      >
        {chartSpend && cost
          ? <StackedBars answered={cost} failed={cost.map(() => 0)} height={110} start={report.series_start} stepS={report.step_s} axis format={(v) => fmtCost(v) ?? '—'} />
          : <StackedBars answered={answered} failed={failed} height={110} start={report.series_start} stepS={report.step_s} axis />}
      </UsageCard>

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'repeat(2, minmax(0, 1fr))' }, gap: 2 }}>
        {providers.length > 0 && (
          <UsageCard title={t('By provider')} right={<MetricSwitch value={metric} onChange={setMetric} />}>
            <ShareList items={providers} metric={metric === 'quality' ? 'calls' : metric} onPick={nav.provider} />
          </UsageCard>
        )}
        <UsageCard
          title={
            <ToggleButtonGroup exclusive size="small" value={dim} onChange={(_, v: GroupDim | null) => v && setDim(v)} sx={segmentedSx(P, 'sm')} aria-label={t('Group by')}>
              {dims.map((d) => <ToggleButton key={d} value={d} disableRipple>{dimLabel[d]}</ToggleButton>)}
            </ToggleButtonGroup>
          }
          right={<MetricSwitch value={metric} onChange={setMetric} quality={dim === 'feature'} />}
        >
          {dim !== 'feature' && !byDim.data ? <Box sx={{ minHeight: 120 }} /> : <ShareList items={features} metric={metric === 'quality' && dim !== 'feature' ? 'calls' : metric} onPick={(key) => nav.group(dim, key)} />}
        </UsageCard>
      </Box>

      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
        <Link sx={link} onClick={() => nav.group('feature', 'model_tests')}>{t('Model quality')}</Link>
        <Link sx={link} onClick={() => nav.view('training')}>{t('Training data')}</Link>
        <Link sx={link} onClick={() => nav.view('budget')}>{t('Budgets')}</Link>
        <Link sx={link} onClick={onExport}>{t('Export CSV')}</Link>
      </Box>
    </Box>
  );
};
