/**
 * The calls of one group (TASK-147): Time · Feature · Model · Tokens · Latency · Cost · Result. A run of identical
 * failures (same feature, model and reason, back to back) is one row with an "N×" badge and its time range.
 * Columns sort on click; a phone keeps Time, Feature, Cost and Result. A row opens the call.
 */
import { Box, Typography } from '@mui/material';
import React, { useMemo, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useResponsiveMode } from '../../hooks/useResponsiveMode';
import { useI18n } from '../../i18n/useI18n';

import type { AiCall } from './api';
import { fmtCost, fmtCount, fmtSeconds, fmtTime, fmtTimeRange, fmtTokens } from './format';
import { categoryLabel, errorTypeLabel } from './labels';

export interface CallRun { call: AiCall; n: number; first: string }

export const foldCalls = (calls: AiCall[]): CallRun[] => {
  const out: CallRun[] = [];
  for (const c of calls) {
    const last = out[out.length - 1];
    if (last && !c.ok && !last.call.ok && last.call.usage_key === c.usage_key && last.call.model === c.model && last.call.error_type === c.error_type) {
      last.n += 1;
      last.first = c.ts;
      continue;
    }
    out.push({ call: c, n: 1, first: c.ts });
  }
  return out;
};

type SortKey = 'ts' | 'feature' | 'model' | 'tokens' | 'latency' | 'cost' | 'result';
const SHOWN = 60;

export const ResultPill: React.FC<{ call: AiCall }> = ({ call }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const avoided = call.outcome === 'avoided';
  const bad = !call.ok && !avoided;
  const text = avoided ? t('Avoided') : call.ok ? t('OK') : errorTypeLabel(call.error_type, t) || t('Failed');
  return (
    <Box component="span" sx={{ px: 1, borderRadius: 2, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, whiteSpace: 'nowrap', bgcolor: bad ? `${P.error}24` : P.hoverBg, color: bad ? P.error : P.textSecondary }}>
      {text}
    </Box>
  );
};

/** `total`: calls of the period behind the list (the list is the newest ones only). */
export const CallList: React.FC<{ calls: AiCall[]; names?: Record<string, string>; total?: number; onOpen: (run: CallRun) => void }> = ({ calls, names, total, onOpen }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { isMobile } = useResponsiveMode();
  const [sort, setSort] = useState<SortKey>('ts');
  const [asc, setAsc] = useState(false);
  const sortBy = (key: SortKey) => { if (key === sort) setAsc(!asc); else { setSort(key); setAsc(false); } };
  const feature = (c: AiCall) => (c.category ? categoryLabel(c.category, t, names) : c.usage_label || c.usage_key);
  const runs = useMemo(() => {
    const folded = foldCalls(calls);
    const key = (r: CallRun): number | string => {
      const c = r.call;
      switch (sort) {
        case 'feature': return feature(c);
        case 'model': return c.model || '';
        case 'tokens': return -(c.tokens_in + c.tokens_out);
        case 'latency': return -c.latency_ms;
        case 'cost': return -(c.cost ?? -1);
        case 'result': return c.ok ? 1 : 0;
        default: return 0;
      }
    };
    const ordered = sort === 'ts' ? folded : [...folded].sort((a, b) => {
      const ka = key(a), kb = key(b);
      return typeof ka === 'number' ? ka - (kb as number) : String(ka).localeCompare(String(kb));
    });
    return asc ? [...ordered].reverse() : ordered;
  }, [calls, sort, asc]);

  const cols: { key: SortKey; label: string; right?: boolean; wide?: boolean }[] = [
    { key: 'ts', label: t('Time') },
    { key: 'feature', label: t('Feature') },
    { key: 'model', label: t('Model'), wide: true },
    { key: 'tokens', label: t('Tokens'), right: true, wide: true },
    { key: 'latency', label: t('Latency'), right: true, wide: true },
    { key: 'cost', label: t('Cost'), right: true },
    { key: 'result', label: t('Result') },
  ];
  const shownCols = cols.filter((c) => !isMobile || !c.wide);
  const cell = { px: 1, py: 0.75, borderBottom: `1px solid ${P.borderColor}`, fontSize: TYPOGRAPHY.body.size, whiteSpace: 'nowrap' } as const;

  return (
    <Box sx={{ overflowX: 'auto' }}>
      <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            {shownCols.map((c) => (
              <Box
                component="th"
                key={c.key}
                onClick={() => sortBy(c.key)}
                sx={{ ...cell, fontWeight: 600, color: P.textSecondary, cursor: 'pointer', textAlign: c.right ? 'right' : 'left', userSelect: 'none' }}
              >
                {c.label}{sort === c.key ? (asc ? ' ↑' : ' ↓') : ''}
              </Box>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.slice(0, SHOWN).map((r) => {
            const c = r.call;
            const time = r.n > 1 && r.first !== c.ts ? fmtTimeRange(r.first, c.ts) : fmtTime(c.ts);
            return (
              <Box
                component="tr"
                key={c.id}
                tabIndex={0}
                onClick={() => onOpen(r)}
                onKeyDown={(e: React.KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(r); } }}
                sx={{ cursor: 'pointer', '&:hover, &:focus-visible': { bgcolor: P.hoverBg, outline: 'none' } }}
              >
                <Box component="td" sx={{ ...cell, fontVariantNumeric: 'tabular-nums' }}>{time}</Box>
                <Box component="td" sx={{ ...cell, maxWidth: { xs: 130, sm: 240 }, overflow: 'hidden', textOverflow: 'ellipsis' }}>{feature(c)}</Box>
                {!isMobile && <Box component="td" sx={{ ...cell, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.model || '—'}</Box>}
                {!isMobile && <Box component="td" sx={{ ...cell, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtTokens(c.tokens_in + c.tokens_out)}</Box>}
                {!isMobile && <Box component="td" sx={{ ...cell, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtSeconds(c.latency_ms)}</Box>}
                <Box component="td" sx={{ ...cell, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtCost(c.cost) ?? '—'}</Box>
                <Box component="td" sx={cell}>
                  <ResultPill call={c} />
                  {r.n > 1 && <Box component="span" sx={{ ml: 0.75, px: 0.5, borderRadius: 1, bgcolor: P.hoverBg, color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600 }}>{fmtCount(r.n)}×</Box>}
                </Box>
              </Box>
            );
          })}
        </tbody>
      </Box>
      {runs.length > SHOWN && (
        <Typography sx={{ mt: 0.75, fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{t('{shown} of {total}', { shown: fmtCount(SHOWN), total: fmtCount(Math.max(total ?? 0, runs.length)) })}</Typography>
      )}
    </Box>
  );
};
