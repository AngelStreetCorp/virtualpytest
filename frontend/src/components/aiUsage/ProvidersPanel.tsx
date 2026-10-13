/**
 * Providers of Monitoring → AI usage: one bordered list, one row per configured provider (also those with no
 * requests) — status (icon + word), answered / failed bars over the page period, counts, the reason with since.
 */
import { CheckCircleOutline as OkIcon, ErrorOutline as DownIcon, WarningAmber as DegradedIcon } from '@mui/icons-material';
import { Box, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';

import type { ProviderView, UsageReport } from './api';
import { StackedBars } from './charts';
import { fmtCount, fmtTime } from './format';
import { errorTypeLabel, providerTypeLabel } from './labels';

const COLUMNS = '210px 112px minmax(120px, 1fr) 160px minmax(0, 1.4fr)';

export const ProvidersPanel: React.FC<{ report: UsageReport }> = ({ report }) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const providers = report.providers ?? [];
  if (providers.length === 0) return <Typography sx={{ color: P.textMuted, py: 2 }}>—</Typography>;

  const statusOf = (p: ProviderView) => {
    if (p.status === 'down') return { Icon: DownIcon, color: P.error, word: t('Down') };
    if (p.status === 'degraded') return { Icon: DegradedIcon, color: P.warning, word: t('Degraded') };
    if (p.status === 'unused') return { Icon: OkIcon, color: P.textMuted, word: p.enabled ? t('No requests') : t('Disabled') };
    return { Icon: OkIcon, color: P.success, word: t('OK') };
  };

  return (
    <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 2, bgcolor: P.surface, overflow: 'hidden' }}>
      {providers.map((p, i) => {
        const { Icon, color, word } = statusOf(p);
        const reason = p.reason && p.status !== 'ok' && p.status !== 'unused'
          ? `${errorTypeLabel(p.reason, t)}${p.since ? ` · ${t('since')} ${fmtTime(p.since)}` : ''}${p.skipped > 0 ? ` · ${tn(p.skipped, '{count} call skipped', '{count} calls skipped', { count: fmtCount(p.skipped) })}` : ''}`
          : '';
        const counts = p.calls === 0 ? '—' : `${tn(p.calls, '{count} request', '{count} requests', { count: fmtCount(p.calls) })}${p.errors ? ` · ${t('{count} failed', { count: fmtCount(p.errors) })}` : ''}`;
        return (
          <Box
            key={p.endpoint}
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', md: COLUMNS },
              alignItems: 'center',
              columnGap: 1.5,
              rowGap: 0.25,
              px: 1.5,
              py: 0.75,
              borderTop: i ? `1px solid ${P.borderColor}` : 'none',
              '&:hover': { bgcolor: P.hoverBg },
            }}
          >
            <Box sx={{ minWidth: 0 }} title={`${p.endpoint}${p.region ? ` · ${p.region}` : ''}`}>
              <Typography noWrap sx={{ fontSize: '0.85rem', fontWeight: 600 }}>{p.name}</Typography>
              <Typography noWrap sx={{ fontSize: '0.72rem', color: P.textMuted }}>
                {providerTypeLabel(p.type, t)}{p.plan ? ` · ${t('included in plan')}` : ''}{p.region ? ` · ${p.region}` : ''}
              </Typography>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, color }}>
              <Icon sx={{ fontSize: 18 }} />
              <Typography noWrap sx={{ fontSize: '0.8rem', fontWeight: 600, color }}>{word}</Typography>
            </Box>
            <StackedBars answered={p.answered_series ?? []} failed={p.failed_series ?? []} height={26} />
            <Typography noWrap title={counts} sx={{ fontSize: '0.78rem', color: P.textSecondary, fontVariantNumeric: 'tabular-nums' }}>{counts}</Typography>
            <Typography noWrap title={reason} sx={{ fontSize: '0.78rem', color: p.status === 'ok' ? P.textMuted : color }}>{reason || '—'}</Typography>
          </Box>
        );
      })}
    </Box>
  );
};
