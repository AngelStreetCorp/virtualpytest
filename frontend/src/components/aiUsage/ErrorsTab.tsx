/** Errors tab: one row per cause (provider + reason) with the categories it hits, since / last, and a link to the provider. */
import { ErrorOutline as ErrorIcon, WarningAmber as WarningIcon } from '@mui/icons-material';
import { Box, Link, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material';
import React from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';

import type { UsageReport } from './api';
import { fmtCount, fmtTime } from './format';
import { categoryLabel, causeSentence, errorTypeLabel } from './labels';
import { cellSx, headSx } from './tableStyles';

/** Settings → AI, Endpoints sub-tab: where a provider's key and URL are. */
export const PROVIDER_SETTINGS = '/configuration/settings?tab=ai&sub=endpoints';

export const ErrorsTab: React.FC<{ report: UsageReport }> = ({ report }) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const causes = report.errors?.causes ?? [];
  if (!report.errors) return <Typography sx={{ color: P.textMuted, py: 2 }}>—</Typography>;
  if (causes.length === 0) return <Typography sx={{ color: P.textMuted, py: 3 }}>{t('No errors in this period.')}</Typography>;
  const cols = [112, 150, 190, undefined, 80, 90, 90];
  const heads = [t('Level'), t('Provider'), t('Cause'), t('Hits'), t('Failed'), t('Since'), t('Last')];
  return (
    <TableContainer sx={{ minWidth: 0, maxWidth: '100%', border: `1px solid ${P.borderColor}`, bgcolor: P.surface }}>
      <Table size="small" sx={{ minWidth: 760, tableLayout: 'fixed' }}>
        <colgroup>{cols.map((w, i) => <col key={i} style={w ? { width: w } : undefined} />)}</colgroup>
        <TableHead>
          <TableRow>{heads.map((h, i) => <TableCell key={h} align={i >= 4 ? 'right' : 'left'} sx={headSx}>{h}</TableCell>)}</TableRow>
        </TableHead>
        <TableBody>
          {causes.map((c) => {
            const color = c.severity === 'error' ? P.error : P.warning;
            const Icon = c.severity === 'error' ? ErrorIcon : WarningIcon;
            const hits = c.categories.map((k) => categoryLabel(k, t)).join(', ');
            const skipped = c.skipped > 0 ? ` · ${tn(c.skipped, '{count} call skipped while paused', '{count} calls skipped while paused', { count: fmtCount(c.skipped) })}` : '';
            return (
              <TableRow key={`${c.endpoint}|${c.reason}`}>
                <TableCell sx={{ ...cellSx, color }}>
                  <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
                    <Icon sx={{ fontSize: 16 }} />{c.severity === 'error' ? t('Error') : t('Warning')}
                  </Box>
                </TableCell>
                <TableCell title={c.endpoint} sx={cellSx}>
                  <Link component={RouterLink} to={PROVIDER_SETTINGS}>{c.provider}</Link>
                </TableCell>
                <TableCell title={`${causeSentence(c.reason, c.provider, t)}${skipped}`} sx={cellSx}>{errorTypeLabel(c.reason, t)}</TableCell>
                <TableCell title={hits} sx={cellSx}>{hits}</TableCell>
                <TableCell align="right" sx={cellSx}>{fmtCount(c.errors)}</TableCell>
                <TableCell align="right" sx={{ ...cellSx, fontVariantNumeric: 'tabular-nums' }}>{fmtTime(c.since)}</TableCell>
                <TableCell align="right" sx={{ ...cellSx, fontVariantNumeric: 'tabular-nums' }}>{fmtTime(c.last)}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </TableContainer>
  );
};
