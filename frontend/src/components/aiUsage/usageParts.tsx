/**
 * Building blocks of the AI usage page (TASK-147): a stat tile (label, one number or chart, one short caption,
 * UI_STYLE §16 rule 3b), a card, and a share list (name, bar, calls, cost) whose rows open the next level.
 */
import { Box, Link, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import React, { useState } from 'react';

import { segmentedSx } from '../common/PageChrome';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';

import { fmtCost, fmtCount, fmtPct } from './format';

/**
 * A cost that says what it is missing: "no price" when no answered call has one, "≥ $x" with a hover hint when only
 * some do. Only ANSWERED calls count: a failed call is not billed, so it is never "missing a price"
 * (unpriced = calls − failed − priced). `priced` undefined = the source does not say, or a flat plan: plain amount.
 */
export const costView = (
  cost: number | null,
  calls: number,
  failed: number,
  priced: number | undefined,
  tn: (count: number, one: string, other: string, vars?: Record<string, string | number>) => string,
  t: (key: string) => string,
): { text: string; hint?: string } => {
  const plain = { text: fmtCost(cost) ?? '—' };
  const answered = calls - failed;
  if (priced === undefined || answered <= 0) return plain;
  const missing = (n: number) => tn(n, '{count} call has no price', '{count} calls have no price', { count: fmtCount(n) });
  if (cost == null || priced <= 0) return { text: t('no price'), hint: missing(answered) };
  if (priced < answered) return { text: `≥ ${fmtCost(cost) ?? ''}`, hint: missing(answered - priced) };
  return plain;
};

export const TileRow: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', md: 'repeat(4, minmax(0, 1fr))' }, gap: 1.5, mb: 2 }}>{children}</Box>
);

interface TileProps {
  label: string;
  value: React.ReactNode;
  color?: string;
  /** One line, ten words at most. */
  caption?: React.ReactNode;
  /** The word's meaning, on hover. */
  hint?: string;
  chart?: React.ReactNode;
  onClick?: () => void;
}

export const UsageTile: React.FC<TileProps> = ({ label, value, color, caption, chart, hint, onClick }) => {
  const P = useAgentChatPalette();
  return (
    <Box
      component={onClick ? 'button' : 'div'}
      type={onClick ? 'button' : undefined}
      onClick={onClick}
      sx={{
        all: onClick ? 'unset' : undefined, boxSizing: 'border-box', minHeight: 120, minWidth: 0, px: 1.5,
        display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', textAlign: 'center', gap: 0.5,
        bgcolor: P.surface, border: `1px solid ${P.borderColor}`, borderRadius: 3, cursor: onClick ? 'pointer' : 'default',
        '&:hover': onClick ? { borderColor: P.accentText } : undefined,
      }}
    >
      <Typography title={hint} sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, textDecoration: hint ? `underline dotted ${P.textMuted}` : undefined, textUnderlineOffset: 3 }}>{label}</Typography>
      <Typography sx={{ fontSize: TYPOGRAPHY.kpiValue.size, fontWeight: 600, lineHeight: 1.15, color: color ?? P.textPrimary, fontVariantNumeric: 'tabular-nums' }}>{value}</Typography>
      {chart}
      {caption && (
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, maxWidth: '100%', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{caption}</Typography>
      )}
    </Box>
  );
};

export const UsageCard: React.FC<{ title: React.ReactNode; right?: React.ReactNode; children: React.ReactNode }> = ({ title, right, children }) => {
  const P = useAgentChatPalette();
  return (
    <Box sx={{ bgcolor: P.surface, border: `1px solid ${P.borderColor}`, borderRadius: 3, px: 2, py: 1.5, mb: 2, minWidth: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, minHeight: 32, flexWrap: 'wrap' }}>
        <Typography sx={{ fontSize: TYPOGRAPHY.cardTitle.size, fontWeight: 600, color: P.textSecondary }}>{title}</Typography>
        {right && <Box sx={{ ml: 'auto', display: 'flex', alignItems: 'center', gap: 1 }}>{right}</Box>}
      </Box>
      {children}
    </Box>
  );
};

export type Metric = 'calls' | 'cost' | 'failed' | 'quality';

export const MetricSwitch: React.FC<{ value: Metric; onChange: (m: Metric) => void; quality?: boolean }> = ({ value, onChange, quality }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  return (
    <ToggleButtonGroup exclusive size="small" value={value} onChange={(_, v: Metric | null) => v && onChange(v)} sx={segmentedSx(P, 'sm')}>
      <ToggleButton value="calls" disableRipple>{t('Calls')}</ToggleButton>
      <ToggleButton value="cost" disableRipple>{t('Cost')}</ToggleButton>
      <ToggleButton value="failed" disableRipple>{t('Failed')}</ToggleButton>
      {quality && <ToggleButton value="quality" disableRipple>{t('Quality')}</ToggleButton>}
    </ToggleButtonGroup>
  );
};

export interface ShareItem {
  key: string;
  name: string;
  calls: number;
  failed: number;
  /** null: not known for this row (a provider row of a feature); the column stays empty. */
  cost: number | null;
  /** Calls that carry a price; with it the cost column says "no price" or "≥" when some have none. */
  priced?: number;
  /** Benchmark pass rate 0..1; null: no run; undefined: the list shows no quality. */
  quality?: number | null;
  /** Hover of the quality value: "{passed} of {scored} cases · {date}". */
  qualityHint?: string;
}

const SHORT_LIST = 10;

export const ShareList: React.FC<{ items: ShareItem[]; metric?: Metric; active?: string; onPick?: (key: string) => void; showQuality?: boolean }> = ({ items, metric = 'calls', active, onPick, showQuality }) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const [all, setAll] = useState(false);
  const value = (i: ShareItem) => (metric === 'cost' ? i.cost ?? 0 : metric === 'failed' ? i.failed : metric === 'quality' ? i.quality ?? 0 : i.calls);
  // Quality: untested rows last, then by calls.
  const rows = [...items].sort((a, b) => (metric === 'quality' && (a.quality == null) !== (b.quality == null) ? (a.quality == null ? 1 : -1) : value(b) - value(a) || b.calls - a.calls));
  const max = Math.max(1e-9, ...rows.map(value));
  const listed = metric === 'failed' ? rows.filter((r) => r.failed > 0) : rows;
  const shown = all ? listed : listed.filter((r, n) => n < SHORT_LIST || r.key === active);
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column' }}>
      {shown.map((i) => {
        const ok = metric === 'cost' ? i.cost ?? 0 : metric === 'failed' ? 0 : metric === 'quality' ? i.quality ?? 0 : i.calls - i.failed;
        const ko = metric === 'cost' || metric === 'quality' ? 0 : i.failed;
        const idle = showQuality && i.calls === 0;
        const qualityCell = (
          <Typography noWrap title={i.qualityHint} sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{i.quality == null ? '—' : fmtPct(i.quality)}</Typography>
        );
        const perCall = i.cost != null && i.calls ? t('{cost} per call', { cost: fmtCost(i.cost / i.calls) ?? '' }) : undefined;
        const costCell = i.cost == null && i.priced === undefined ? { text: '—' } : costView(i.cost, i.calls, i.failed, i.priced, tn, t);
        const costHint = [costCell.hint, perCall].filter(Boolean).join(' · ') || undefined;
        return (
          <Box
            key={i.key}
            component={onPick ? 'button' : 'div'}
            type={onPick ? 'button' : undefined}
            onClick={onPick ? () => onPick(i.key) : undefined}
            sx={{
              all: onPick ? 'unset' : undefined, boxSizing: 'border-box', width: '100%', display: 'grid', alignItems: 'center', gap: 1.25,
              gridTemplateColumns: showQuality
                ? { xs: 'minmax(0, 1fr) 44px 66px 44px', sm: 'minmax(0, 1.5fr) minmax(0, 1fr) 64px 78px 52px' }
                : { xs: 'minmax(0, 1fr) 56px 78px', sm: 'minmax(0, 1.5fr) minmax(0, 1fr) 64px 78px' },
              opacity: idle ? 0.6 : 1,
              px: 0.75, py: 0.75, borderRadius: 1.5, cursor: onPick ? 'pointer' : 'default',
              bgcolor: active === i.key ? P.hoverBg : 'transparent', '&:hover': onPick ? { bgcolor: P.hoverBg } : undefined,
            }}
          >
            <Typography noWrap sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary }} title={i.failed ? `${i.name} · ${t('{count} failed', { count: fmtCount(i.failed) })}` : i.name}>{i.name}</Typography>
            <Box sx={{ display: { xs: 'none', sm: 'flex' }, height: 8, borderRadius: 1, bgcolor: P.hoverBg, overflow: 'hidden' }}>
              <Box sx={{ width: `${(100 * ok) / max}%`, bgcolor: P.accent }} />
              {ko > 0 && <Box sx={{ width: `${(100 * ko) / max}%`, bgcolor: P.error }} />}
            </Box>
            {metric === 'quality' ? (
              <>
                {qualityCell}
                <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtCount(i.calls)}</Typography>
              </>
            ) : metric === 'failed' ? (
              <>
                <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.error, fontWeight: 600, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtCount(i.failed)}</Typography>
                <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{i.calls ? fmtPct(i.failed / i.calls) : '—'}</Typography>
              </>
            ) : (
              <>
                <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtCount(i.calls)}</Typography>
                <Typography noWrap title={costHint} sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{costCell.text}</Typography>
                {showQuality && qualityCell}
              </>
            )}
          </Box>
        );
      })}
      {metric === 'failed' && listed.length === 0 && <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, px: 0.75 }}>{t('No failure')}</Typography>}
      {listed.length > shown.length && (
        <Link component="button" onClick={() => setAll(true)} sx={{ alignSelf: 'flex-start', mt: 0.5, px: 0.75, fontSize: TYPOGRAPHY.caption.size }}>
          {t('{count} more', { count: fmtCount(listed.length - shown.length) })}
        </Link>
      )}
    </Box>
  );
};

/** "↓ 40 %" against the previous window of the same length; empty when there is no previous value. */
export const deltaText = (now: number | null | undefined, prev: number | null | undefined): string => {
  if (now == null || !prev) return '';
  const d = Math.round((100 * (now - prev)) / prev);
  return `${d < 0 ? '↓' : '↑'} ${Math.abs(d)} %`;
};
