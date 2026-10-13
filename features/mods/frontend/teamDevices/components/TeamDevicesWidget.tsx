import { Box, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../../../frontend/src/constants/agentChatTheme';
import { useI18n } from '../../../../../frontend/src/i18n/useI18n';
import type { WidgetProps } from '../../../../../frontend/src/mods/core/types';
import { ERRORS_FAILED_24H, MAX_ROWS, SHOW_ALL } from '../constants';
import { useTeamDevices } from '../hooks/useTeamDevices';
import type { ErrorSource } from '../types';

/** Tile label and row word per error source (English i18n keys). */
const ERROR_LABELS: Record<ErrorSource, { tile: string; row: string }> = {
  failed_24h: { tile: 'Failed 24 h', row: '{count} failed' },
  failed_7d: { tile: 'Failed 7 days', row: '{count} failed' },
  open_alerts: { tile: 'Open alerts', row: '{count} alerts' },
};

/** Team devices: totals (devices, running, errors, offline) and the busiest devices. */
export const TeamDevicesWidget: React.FC<WidgetProps> = ({ settings }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const source = (Object.keys(ERROR_LABELS).includes(String(settings.errors)) ? settings.errors : ERRORS_FAILED_24H) as ErrorSource;
  const labels = ERROR_LABELS[source];
  const { rows, totals, errorsLoaded } = useTeamDevices(String(settings.show ?? SHOW_ALL), source);

  const tiles = [
    { label: t('Devices'), value: totals.devices, color: P.textPrimary },
    { label: t('Running'), value: totals.running, color: totals.running ? P.accentText : P.textMuted },
    { label: t(labels.tile), value: errorsLoaded ? totals.failed : '—', color: totals.failed ? P.error : P.textMuted },
    { label: t('Offline'), value: totals.offline, color: totals.offline ? P.warning : P.textMuted },
  ];

  return (
    <Box>
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 1, mb: 1 }}>
        {tiles.map((tile) => (
          <Box key={tile.label} sx={{ bgcolor: P.hoverBg, borderRadius: 2, px: 1, py: 0.75 }}>
            <Typography sx={{ fontSize: '0.7rem', color: P.textMuted }} noWrap>
              {tile.label}
            </Typography>
            <Typography sx={{ fontSize: '1.1rem', fontWeight: 600, color: tile.color }}>{tile.value}</Typography>
          </Box>
        ))}
      </Box>
      {rows.length === 0 ? (
        <Typography sx={{ fontSize: '0.8rem', color: P.textMuted }}>{t('Nothing to show')}</Typography>
      ) : (
        rows.slice(0, MAX_ROWS).map((r) => (
          <Box
            key={`${r.hostName}:${r.deviceId}`}
            sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 0.5, borderTop: `1px solid ${P.borderColor}` }}
          >
            <Box sx={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0, bgcolor: r.online ? P.success : P.warning }} />
            <Typography sx={{ fontSize: '0.8rem', color: P.textPrimary, flex: 1, minWidth: 0 }} noWrap>
              {r.deviceName}
              <Box component="span" sx={{ color: P.textMuted, ml: 0.75 }}>
                {r.hostName}
              </Box>
            </Typography>
            {r.running > 0 && (
              <Typography sx={{ fontSize: '0.75rem', color: P.accentText, whiteSpace: 'nowrap' }}>
                {t('{count} running', { count: r.running })}
              </Typography>
            )}
            {r.failed > 0 && (
              <Typography sx={{ fontSize: '0.75rem', color: P.error, whiteSpace: 'nowrap' }}>
                {t(labels.row, { count: r.failed })}
              </Typography>
            )}
          </Box>
        ))
      )}
      {rows.length > MAX_ROWS && (
        <Typography sx={{ fontSize: '0.75rem', color: P.textMuted, pt: 0.5 }}>{t('+{count} more', { count: rows.length - MAX_ROWS })}</Typography>
      )}
    </Box>
  );
};
