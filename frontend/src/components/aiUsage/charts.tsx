/** Small chart pieces of the AI usage page: stacked answered / failed bars with a time axis. No motion. */
import { Box, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { formatDate } from '../../i18n';
import { useI18n } from '../../i18n/useI18n';

import { fmtCount } from './format';
import { TYPOGRAPHY } from '../../constants/typography';

interface BarsProps {
  answered: number[];
  failed: number[];
  height?: number;
  /** ISO start of the first bar and seconds per bar: labels the time axis and each bar's tooltip. */
  start?: string;
  stepS?: number;
  axis?: boolean;
  /** Bar value in words (default: "N answered · N failed"); a money chart passes its own. */
  format?: (total: number) => string;
}

/** Axis and tooltip labels through the app formatter, so they match every other date on the page (dd/mm, 24 h). */
const labelOf = (start: string, stepS: number, i: number, _lang: string, long: boolean): string => {
  const d = new Date(new Date(start).getTime() + i * stepS * 1000);
  return stepS >= 86400
    ? formatDate(d, { day: '2-digit', month: '2-digit' })
    : formatDate(d, long ? { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' } : { hour: '2-digit', minute: '2-digit' });
};

export const StackedBars: React.FC<BarsProps> = ({ answered, failed, height = 40, start, stepS = 3600, axis, format }) => {
  const P = useAgentChatPalette();
  const { t, lang } = useI18n();
  const totals = answered.map((a, i) => a + (failed[i] ?? 0));
  const max = Math.max(1, ...totals);
  return (
    <Box sx={{ minWidth: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'flex-end', gap: '1px', height, borderBottom: `1px solid ${P.borderColor}` }}>
        {totals.map((total, i) => {
          const f = failed[i] ?? 0;
          const a = answered[i] ?? 0;
          const when = start ? `${labelOf(start, stepS, i, lang, true)} · ` : '';
          return (
            <Box
              key={i}
              title={`${when}${format ? format(total) : `${t('{count} answered', { count: fmtCount(a) })} · ${t('{count} failed', { count: fmtCount(f) })}`}`}
              sx={{ flex: 1, minWidth: '1px', height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}
            >
              {f > 0 && <Box sx={{ height: `${Math.max(6, (f / max) * 100)}%`, bgcolor: P.error }} />}
              {a > 0 && <Box sx={{ height: `${Math.max(6, (a / max) * 100)}%`, bgcolor: P.accent }} />}
              {total === 0 && <Box sx={{ height: 1, bgcolor: P.hoverBg }} />}
            </Box>
          );
        })}
      </Box>
      {axis && start && (
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 0.25, fontVariantNumeric: 'tabular-nums' }}>
          <Typography sx={{ fontSize: TYPOGRAPHY.microMeta.size, color: P.textMuted }}>{labelOf(start, stepS, 0, lang, stepS < 86400 && totals.length > 24)}</Typography>
          <Typography sx={{ fontSize: TYPOGRAPHY.microMeta.size, color: P.textMuted }}>{t('max {count} per bar', { count: format ? format(max) : fmtCount(max) })}</Typography>
          <Typography sx={{ fontSize: TYPOGRAPHY.microMeta.size, color: P.textMuted }}>{labelOf(start, stepS, totals.length - 1, lang, stepS < 86400 && totals.length > 24)}</Typography>
        </Box>
      )}
    </Box>
  );
};
