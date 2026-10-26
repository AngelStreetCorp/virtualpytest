/**
 * AI usage, level 2 (TASK-147): one provider or one feature. A line of 2-3 short facts, four tiles, who uses it
 * (a provider's features, a feature's providers: a click filters the calls), its models, then its calls
 * (All / Failed). Model tests also shows the benchmark results.
 */
import { Box, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import React, { useMemo } from 'react';

import { segmentedSx } from '../common/PageChrome';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { AppIcon } from '../../constants/icons';
import { TYPOGRAPHY } from '../../constants/typography';
import { formatDate } from '../../i18n';
import { useProfile } from '../../hooks/auth/useProfile';
import { useI18n } from '../../i18n/useI18n';

import { BudgetBucketsReport, CreditRow, UsageQuery, UsageReport, UsageRow, fetchAiCalls, fetchAiUsage, fetchBenchmarks, fetchBudget, fetchCredits } from './api';
import { BenchmarksTab } from './BenchmarksTab';
import { StackedBars } from './charts';
import { CallList, CallRun } from './CallList';
import { fmtCost, fmtCount, fmtPct, fmtSeconds } from './format';
import { categoryLabel, errorTypeLabel } from './labels';
import { profileQuality } from './quality';
import { PanelError } from './PanelError';
import { ShareItem, ShareList, TileRow, UsageCard, UsageTile, costView } from './usageParts';
import { useAiLoad } from './useAiLoad';

/** provider, user and host list the features they serve; a feature lists the providers it is sent to. */
export type GroupKind = 'provider' | 'feature' | 'user' | 'host';

interface Props {
  kind: GroupKind;
  id: string;
  query: UsageQuery;
  /** The unfiltered report of the period: shares, provider status and names. */
  base: UsageReport;
  pick: string;
  failedOnly: boolean;
  onPick: (key: string) => void;
  onFailedOnly: (on: boolean) => void;
  onOpenCall: (run: CallRun) => void;
}

/** Models of a set of rows: calls and failures per routing profile, by its human name. */
const modelsOf = (rows: UsageRow[]): ShareItem[] => {
  const m = new Map<string, ShareItem>();
  rows.forEach((r) => Object.entries(r.profiles ?? {}).forEach(([profile, calls]) => {
    const item = m.get(profile) ?? { key: profile, name: r.profile_labels?.[profile] ?? profile, calls: 0, failed: 0, cost: null };
    item.calls += calls;
    item.failed += r.profile_errors?.[profile] ?? 0;
    m.set(profile, item);
  }));
  return [...m.values()];
};

export const groupName = (kind: GroupKind, id: string, base: UsageReport, t: (k: string, v?: Record<string, string | number>) => string): string => {
  if (kind === 'provider') return (base.providers ?? []).find((p) => p.endpoint === id)?.name ?? id;
  if (kind === 'user') return base.options?.user?.find((o) => o.key === id)?.label ?? id;
  if (kind === 'host') return id;
  return categoryLabel(id, t, base.overview?.category_labels);
};

const SCOPE: Record<Exclude<GroupKind, 'feature'>, keyof UsageQuery> = { provider: 'provider', user: 'user', host: 'host' };

export const UsageGroup: React.FC<Props> = ({ kind, id, query, base, pick, failedOnly, onPick, onFailedOnly, onOpenCall }) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const byFeature = kind !== 'feature';
  const scoped: UsageQuery = byFeature ? { ...query, [SCOPE[kind]]: id } : { ...query, category: id };
  const group = useAiLoad('group', () => fetchAiUsage(scoped, byFeature ? 'category' : 'endpoint'), [JSON.stringify(scoped), kind]);
  const callQuery: UsageQuery = { ...scoped, ...(pick ? (byFeature ? { category: pick } : { provider: pick }) : {}), result: failedOnly ? 'failed' : '' };
  const calls = useAiLoad('group calls', () => fetchAiCalls(callQuery, 200, false), [JSON.stringify(callQuery)], base.source === 'calls');
  // Latency is the group's, whatever the list shows: a pick or the Failed switch must not change it.
  const narrowed = JSON.stringify(callQuery) !== JSON.stringify({ ...scoped, result: '' });
  const whole = useAiLoad('group latency', () => fetchAiCalls(scoped, 1, false), [JSON.stringify(scoped)], base.source === 'calls' && narrowed);
  const budget = useAiLoad('budget', () => fetchBudget() as Promise<BudgetBucketsReport>, [], kind === 'provider');
  // Platform admins only: a 403 (or any failure) shows nothing.
  // Credit is platform-admin data (the endpoint answers 403 to anyone else): ask only when it can answer.
  const { isPlatformAdmin } = useProfile();
  const credits = useAiLoad('credits', () => fetchCredits().then((r) => r.endpoints ?? []).catch((): CreditRow[] => []), [], kind === 'provider' && isPlatformAdmin);
  const bench = useAiLoad('benchmarks', () => fetchBenchmarks({ limit: 200, hours: query.hours }), [query.hours], id === 'model_tests');
  // A feature's models: cost per profile, and the benchmark pass rate of each profile on this feature's usage keys.
  const modelCost = useAiLoad('feature models', () => fetchAiUsage(scoped, 'model'), [JSON.stringify(scoped)], kind === 'feature' && id !== 'model_tests');
  const quality = useAiLoad('feature quality', () => fetchBenchmarks({ category: id, limit: 500, hours: query.hours }), [id, query.hours], kind === 'feature' && id !== 'model_tests');

  const report = group.data;
  // A provider's rows are its categories: their failed calls (errors), not their wasted ones.
  const errorsOf: Record<string, number> = Object.fromEntries((byFeature ? report?.rows ?? [] : []).map((r) => [r.key, r.errors]));
  const names = base.overview?.category_labels;
  const providerName = useMemo(() => Object.fromEntries((base.providers ?? []).map((p) => [p.endpoint, p.name])), [base.providers]);
  if (group.failed) return <PanelError what={t('AI usage')} onRetry={group.reload} />;
  if (!report) return <Box sx={{ minHeight: 240 }} />;

  const T = report.totals;
  const status = kind === 'provider' ? (base.providers ?? []).find((p) => p.endpoint === id) : undefined;
  const others: ShareItem[] = byFeature
    ? (report.overview?.categories ?? []).map((c) => ({ key: c.key, name: categoryLabel(c.key, t, names), calls: c.calls, failed: errorsOf[c.key] ?? 0, cost: c.cost }))
    : report.rows.map((r) => ({ key: r.key, name: providerName[r.key] ?? r.key, calls: r.calls, failed: r.errors, cost: r.cost, priced: r.priced_calls }));
  const models = modelsOf(report.rows);
  if (kind === 'feature' && id !== 'model_tests') {
    const costOf = Object.fromEntries((modelCost.data?.rows ?? []).map((r) => [r.key, r]));
    const scores = profileQuality(quality.data?.runs ?? [], id);
    models.forEach((m) => {
      m.cost = costOf[m.key]?.cost ?? null;
      m.priced = costOf[m.key]?.priced_calls;
    });
    // Tested profiles production did not use in the period: listed with 0 calls, so a cheaper tested model is visible.
    scores.forEach((_, profile) => {
      if (!models.some((m) => m.key === profile)) models.push({ key: profile, name: report.rows.map((r) => r.profile_labels?.[profile]).find(Boolean) ?? modelCost.data?.rows.find((r) => r.key === profile)?.label ?? profile, calls: 0, failed: 0, cost: null });
    });
    models.forEach((m) => {
      const q = scores.get(m.key);
      m.quality = q ? q.rate : null;
      m.qualityHint = q ? t('{passed} of {scored} cases · {date}', { passed: q.passed, scored: q.scored, date: q.ts ? formatDate(new Date(q.ts), { day: '2-digit', month: '2-digit' }) : '' }) : undefined;
    });
  }
  const bad = byFeature ? T.errors : report.overview?.totals.wasted ?? T.errors;
  const avoided = report.overview?.totals.saved ?? 0;
  const failedSeries = T.failed_series ?? [];
  const bucket = (budget.data?.buckets ?? []).find((b) => b.bucket_type === 'endpoint' && b.bucket_id === id);
  const byCalls = [...others].sort((a, b) => b.calls - a.calls)[0];
  const byCost = [...others].sort((a, b) => (b.cost ?? 0) - (a.cost ?? 0))[0];
  const picked = others.find((o) => o.key === pick);
  const balance = kind === 'provider' ? (credits.data ?? []).find((c) => c.endpoint === id)?.balance : undefined;
  // A flat plan bills nothing per call: never "missing a price".
  const cost = costView(T.cost, T.calls, T.errors ?? 0, status?.plan || T.priced_calls == null ? undefined : T.priced_calls, tn, t);
  const costHint = [cost.hint, T.calls && T.cost ? t('{cost} per call', { cost: fmtCost(T.cost / T.calls) ?? '' }) : '', T.cache_saved ? t('Prompt cache saved {cost}', { cost: fmtCost(T.cache_saved) ?? '' }) : '', balance != null ? t('{cost} credit left', { cost: fmtCost(balance) ?? '' }) : ''].filter(Boolean).join(' · ') || undefined;
  const latency = (narrowed ? whole.data : calls.data)?.latency;

  const facts: React.ReactNode[] = [<span key="share"><b>{fmtPct(base.totals.calls ? T.calls / base.totals.calls : 0)}</b> {t('of calls')}</span>];
  if (byCalls && others.length > 1) facts.push(<span key="calls">{byCalls.name} <b>{fmtPct(T.calls ? byCalls.calls / T.calls : 0)}</b></span>);
  if (byCost && byCost !== byCalls && T.cost && byCost.cost) facts.push(<span key="cost">{byCost.name} <b>{fmtPct(byCost.cost / T.cost)}</b> {t('of cost')}</span>);

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, mb: 2, flexWrap: 'wrap' }}>
        {status && status.status !== 'unused' && (
          <Box component="span" title={status.reason ?? ''} sx={{ px: 1, borderRadius: 2, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, bgcolor: status.status === 'ok' ? `${P.success}24` : `${P.error}24`, color: status.status === 'ok' ? P.success : P.error }}>
            {status.status === 'ok' ? t('OK') : status.status === 'down' ? t('Down') : t('Degraded')}
          </Box>
        )}
        {status && status.status !== 'ok' && status.reason && <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.error }}>{errorTypeLabel(status.reason, t)}</Typography>}
        <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary, '& b': { fontWeight: 600 } }}>
          {facts.map((f, i) => <React.Fragment key={i}>{i > 0 && <Box component="span" sx={{ color: P.textMuted }}> · </Box>}{f}</React.Fragment>)}
        </Typography>
      </Box>

      <TileRow>
        <UsageTile label={t('Calls')} value={fmtCount(T.calls)} chart={<Box sx={{ width: '70%' }}><StackedBars answered={(T.series ?? []).map((v, i) => v - (failedSeries[i] ?? 0))} failed={failedSeries} height={22} /></Box>} />
        <UsageTile
          label={t('Cost')}
          value={cost.text}
          hint={costHint}
          caption={bucket ? t('month {spent} of {limit} budget', { spent: fmtCost(bucket.spent) ?? '', limit: fmtCost(bucket.limit) ?? '' })
            : base.totals.cost ? t('{pct} of spend', { pct: fmtPct((T.cost ?? 0) / base.totals.cost) }) : undefined}
        />
        <UsageTile label={byFeature ? t('Failed') : t('Wasted')} hint={byFeature ? undefined : t('Failed, unreadable or cut off')} value={fmtCount(bad)} color={bad ? P.error : undefined} caption={T.calls ? fmtPct(bad / T.calls) : undefined} />
        {avoided > 0
          ? <UsageTile label={t('Avoided')} hint={t('Answered by a cache or a rule, no model call')} value={fmtCount(avoided)} caption={t('answered by a rule')} />
          : <UsageTile label={t('Latency')} value={latency?.p50 != null ? fmtSeconds(latency.p50) : '—'} caption={latency?.p95 != null ? t('95 % under {time}', { time: fmtSeconds(latency.p95) }) : undefined} />}
      </TileRow>

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'repeat(2, minmax(0, 1fr))' }, gap: 2 }}>
        <UsageCard title={byFeature ? t('Used by') : t('Sent to')}>
          <ShareList items={others} active={pick} onPick={onPick} />
        </UsageCard>
        <UsageCard title={t('Models')}>
          <ShareList items={models} showQuality={kind === 'feature' && id !== 'model_tests'} />
        </UsageCard>
      </Box>

      {id === 'model_tests' && <Box sx={{ mb: 2 }}><BenchmarksTab report={bench.data} loading={bench.loading} failed={bench.failed} onReload={bench.reload} /></Box>}

      <UsageCard
        title={
          <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 1 }}>
            {t('Calls')}
            {picked && (
              <Box component="button" type="button" onClick={() => onPick(pick)} sx={{ all: 'unset', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 0.5, px: 1, borderRadius: 1.5, bgcolor: P.hoverBg, color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size }}>
                {picked.name}<AppIcon name="close" />
              </Box>
            )}
          </Box>
        }
        right={
          <ToggleButtonGroup exclusive size="small" value={failedOnly ? 'failed' : 'all'} onChange={(_, v: string | null) => v && onFailedOnly(v === 'failed')} sx={segmentedSx(P, 'sm')}>
            <ToggleButton value="all" disableRipple>{t('All')}</ToggleButton>
            <ToggleButton value="failed" disableRipple>{t('Failed')} {fmtCount(picked ? picked.failed : T.errors)}</ToggleButton>
          </ToggleButtonGroup>
        }
      >
        {base.source !== 'calls'
          ? <Typography sx={{ color: P.textMuted, py: 1 }}>{t('Single requests are listed for up to 7 days.')}</Typography>
          : calls.failed
            ? <PanelError what={t('the request list')} onRetry={calls.reload} />
            : !calls.data
              ? <Box sx={{ minHeight: 120 }} />
              : calls.data.calls.length === 0
                ? <Typography sx={{ color: P.textMuted, py: 1 }}>—</Typography>
                : <CallList calls={calls.data.calls} names={names} total={failedOnly ? undefined : picked ? picked.calls : T.calls} onOpen={onOpenCall} />}
      </UsageCard>
    </Box>
  );
};
