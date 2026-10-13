/**
 * Overview of Monitoring → AI usage: where the AI goes and whether it is worth it.
 * Four tiles, then one bar per category split useful / wasted / saved, then who uses it. A click on a bar or a
 * caller opens the Usage tab filtered to it. Missing fields (an older server) show "—".
 */
import { Box, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import React, { useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { StatTile, StatTiles, rateColor, segmentedSx } from '../common/PageChrome';

import type { Split, UsageQuery, UsageReport } from './api';
import { BudgetPanel } from './BudgetPanel';
import { fmtCost, fmtCount, fmtPct, fmtTokens, orDash } from './format';
import { callerLabel, categoryLabel } from './labels';

type Metric = 'requests' | 'tokens' | 'cost';

const parts = (s: Split, metric: Metric): { useful: number; wasted: number; saved: number } | null => {
  if (metric === 'requests') return { useful: s.useful, wasted: s.wasted, saved: s.saved };
  if (metric === 'tokens') return { useful: s.tokens_useful, wasted: s.tokens_wasted, saved: s.tokens_saved };
  if (s.cost == null && s.cost_saved == null) return null;
  return { useful: s.cost_useful ?? 0, wasted: s.cost_wasted ?? 0, saved: s.cost_saved ?? 0 };
};

const fmtMetric = (n: number, metric: Metric): string =>
  metric === 'cost' ? fmtCost(n) ?? '—' : metric === 'tokens' ? fmtTokens(n) : fmtCount(n);

interface Props {
  report: UsageReport;
  query: UsageQuery;
  restricted: boolean;
  onOpenUsage: (patch: Partial<UsageQuery>) => void;
}

export const OverviewTab: React.FC<Props> = ({ report, query, restricted, onOpenUsage }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [metric, setMetric] = useState<Metric>('requests');
  const totals = report.totals;
  const ov = report.overview;
  const prev = report.previous;
  const colors = { useful: P.success, wasted: P.error, saved: P.accent };

  const Line: React.FC<{ children: React.ReactNode; color?: string }> = ({ children, color }) => (
    <Typography noWrap sx={{ fontSize: '0.72rem', color: color ?? P.textMuted, fontVariantNumeric: 'tabular-nums' }}>{children}</Typography>
  );
  const change = (now: number | null | undefined, before: number | null | undefined) => {
    if (now == null || before == null || before <= 0) return <Line>—</Line>;
    const ratio = (now - before) / before;
    if (Math.abs(ratio) < 0.005) return <Line>{t('same as the previous period')}</Line>;
    return <Line>{ratio > 0 ? '▲' : '▼'} {fmtPct(Math.abs(ratio))} {t('vs previous period')}</Line>;
  };

  const answered = ov ? ov.totals.useful : totals.calls != null ? totals.calls - (totals.errors ?? 0) : null;
  const failed = ov ? ov.totals.wasted : totals.errors;
  const usefulPct = answered != null && totals.calls ? answered / totals.calls : null;
  const cost = totals.cost ?? null;

  const tiles: StatTile[] = [
    {
      label: t('Requests'),
      value: orDash(totals.calls, fmtCount),
      footer: (
        <>
          <Line>{t('{answered} answered · {failed} failed', { answered: orDash(answered, fmtCount), failed: orDash(failed, fmtCount) })}</Line>
          {change(totals.calls, prev?.calls)}
        </>
      ),
    },
    {
      label: t('Useful'),
      value: orDash(usefulPct, fmtPct),
      color: usefulPct == null ? undefined : rateColor(usefulPct * 100, P),
      footer: <Line>{t('{count} wasted', { count: orDash(failed, fmtCount) })}</Line>,
    },
    {
      label: t('Saved by memory'),
      value: orDash(ov?.totals.saved, fmtCount),
      footer: <Line>{ov?.totals.cost_saved != null ? `≈ ${fmtCost(ov.totals.cost_saved)}` : ov ? t('{count} tokens', { count: fmtTokens(ov.totals.tokens_saved) }) : '—'}</Line>,
    },
    {
      label: t('Cost'),
      value: cost != null ? fmtCost(cost) ?? '—' : '—',
      footer: (
        <>
          <Line>{ov?.totals.cost_wasted != null ? t('{cost} wasted', { cost: fmtCost(ov.totals.cost_wasted) ?? '—' }) : '—'}</Line>
          {change(cost, prev?.cost)}
        </>
      ),
    },
  ];

  const section = (title: string, right: React.ReactNode, body: React.ReactNode) => (
    <Box sx={{ mb: 2, minWidth: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, minHeight: 36, flexWrap: 'wrap' }}>
        <Typography sx={{ fontSize: '0.95rem', fontWeight: 600 }}>{title}</Typography>
        {right}
      </Box>
      {body}
    </Box>
  );

  const metricSwitch = (
    <ToggleButtonGroup exclusive size="small" value={metric} onChange={(_, v) => v && setMetric(v)} sx={[segmentedSx(P, 'sm'), { flexShrink: 0 }] as never}>
      <ToggleButton value="requests" disableRipple>{t('Requests')}</ToggleButton>
      <ToggleButton value="tokens" disableRipple>{t('Tokens')}</ToggleButton>
      <ToggleButton value="cost" disableRipple>{t('Cost')}</ToggleButton>
    </ToggleButtonGroup>
  );

  const legend = (
    <Box sx={{ display: 'flex', gap: 1.5 }}>
      {(['useful', 'wasted', 'saved'] as const).map((k) => (
        <Box key={k} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <Box sx={{ width: 8, height: 8, bgcolor: colors[k] }} />
          <Typography sx={{ fontSize: '0.72rem', color: P.textMuted }}>{k === 'useful' ? t('Useful') : k === 'wasted' ? t('Wasted') : t('Saved')}</Typography>
        </Box>
      ))}
    </Box>
  );

  const unavailable = <Typography sx={{ color: P.textMuted, py: 1.5 }}>—</Typography>;
  const frame = (children: React.ReactNode) => (
    <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 2, bgcolor: P.surface, overflow: 'hidden' }}>{children}</Box>
  );

  const categories = ov?.categories ?? [];
  const max = Math.max(1, ...categories.map((c) => { const p = parts(c, metric); return p ? p.useful + p.wasted + p.saved : 0; }));
  const where = categories.length === 0 ? (
    <Typography sx={{ color: P.textMuted, py: 2 }}>{ov ? t('No AI requests in this period.') : '—'}</Typography>
  ) : frame(
    categories.map((c, i) => {
      const p = parts(c, metric);
      const total = p ? p.useful + p.wasted + p.saved : 0;
      const tip = p ? `${t('Useful')} ${fmtMetric(p.useful, metric)} · ${t('Wasted')} ${fmtMetric(p.wasted, metric)} · ${t('Saved')} ${fmtMetric(p.saved, metric)}` : '—';
      return (
        <Box
          key={c.key}
          onClick={() => onOpenUsage({ category: c.key })}
          title={tip}
          sx={{ display: 'grid', gridTemplateColumns: { xs: '130px minmax(0, 1fr) 96px', md: '200px minmax(0, 1fr) 170px' }, alignItems: 'center', columnGap: 1.5, px: 1.5, py: 0.75, cursor: 'pointer', borderTop: i ? `1px solid ${P.borderColor}` : 'none', '&:hover': { bgcolor: P.hoverBg } }}
        >
          <Typography noWrap sx={{ fontSize: '0.85rem' }}>{categoryLabel(c.key, t)}</Typography>
          <Box sx={{ display: 'flex', height: 14, bgcolor: P.hoverBg, borderRadius: 0.5, overflow: 'hidden' }}>
            {p && total > 0 && (['useful', 'wasted', 'saved'] as const).map((k) => p[k] > 0 && (
              <Box key={k} sx={{ width: `${(p[k] / max) * 100}%`, minWidth: 2, bgcolor: colors[k] }} />
            ))}
          </Box>
          <Typography noWrap sx={{ fontSize: '0.8rem', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: P.textSecondary }}>
            {p ? fmtMetric(total, metric) : '—'}
            {p && p.wasted > 0 && total > 0 && <Box component="span" sx={{ color: P.error, display: { xs: 'none', md: 'inline' } }}> · {t('{pct} wasted', { pct: fmtPct(p.wasted / total) })}</Box>}
          </Typography>
        </Box>
      );
    }),
  );

  const callers = ov?.callers ?? [];
  const who = callers.length === 0 ? (ov ? null : unavailable) : frame(
    callers.map((c, i) => {
      const p = parts(c, metric);
      const total = p ? p.useful + p.wasted + p.saved : 0;
      const cats = Object.entries(c.categories).sort((a, b) => b[1] - a[1]).map(([k]) => categoryLabel(k, t)).join(', ');
      return (
        <Box
          key={c.key}
          onClick={() => onOpenUsage({ caller: c.key })}
          title={`${callerLabel(c.key, t)} · ${cats}`}
          sx={{ display: 'grid', gridTemplateColumns: { xs: '130px minmax(0, 1fr) 70px', md: '200px minmax(0, 1fr) 100px 110px' }, alignItems: 'center', columnGap: 1.5, px: 1.5, py: 0.75, cursor: 'pointer', borderTop: i ? `1px solid ${P.borderColor}` : 'none', '&:hover': { bgcolor: P.hoverBg } }}
        >
          <Typography noWrap sx={{ fontSize: '0.85rem' }}>{callerLabel(c.key, t)}</Typography>
          <Typography noWrap sx={{ fontSize: '0.78rem', color: P.textMuted }}>{cats}</Typography>
          <Typography noWrap sx={{ fontSize: '0.8rem', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{p ? fmtMetric(total, metric) : '—'}</Typography>
          <Typography noWrap sx={{ display: { xs: 'none', md: 'block' }, fontSize: '0.78rem', textAlign: 'right', color: p && p.wasted > 0 ? P.error : P.textMuted, fontVariantNumeric: 'tabular-nums' }}>
            {p && total > 0 && p.wasted > 0 ? t('{pct} wasted', { pct: fmtPct(p.wasted / total) }) : '—'}
          </Typography>
        </Box>
      );
    }),
  );

  return (
    <>
      <StatTiles tiles={tiles} columns={4} />
      {section(t('Where the AI goes'), <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>{legend}{metricSwitch}</Box>, where)}
      {callers.length > 0 || !ov ? section(t('Who uses it'), null, who) : null}
      {!restricted && report.scope === 'team' && !query.team && <BudgetPanel />}
    </>
  );
};
