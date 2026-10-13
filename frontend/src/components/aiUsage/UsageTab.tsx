/**
 * Usage tab: who spends what, one line per row. Default grouping is category × caller; "Group by" also offers
 * category, caller, feature, model, provider, team, user and the call-only dimensions. A row opens to show its model
 * chain: per model `145 tried · 51 answered · 94 failed · last 08:51 · Empty answer`.
 */
import { Download as DownloadIcon, ExpandLess, ExpandMore } from '@mui/icons-material';
import { Box, Button, FormControl, InputLabel, MenuItem, Select, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material';
import React, { useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';

import type { GroupBy, UsageReport, UsageRow } from './api';
import { fmtCost, fmtCount, fmtPct, fmtTime, fmtTokens, orDash } from './format';
import { callerLabel, categoryLabel, errorTypeLabel, groupLabel, originLabel, resultLabel } from './labels';
import { cellSx, headSx } from './tableStyles';

/** Group-by choices, in the order of the select (only those the period allows are offered). */
export const USAGE_GROUPS: GroupBy[] = [
  'category_caller', 'category', 'caller', 'usage', 'model', 'endpoint', 'team', 'user', 'host', 'device', 'script', 'campaign', 'server', 'origin', 'error', 'arm', 'client',
];

interface Props {
  report: UsageReport;
  groupBy: GroupBy;
  onGroup: (g: GroupBy) => void;
  onExport: () => void;
}

export const UsageTab: React.FC<Props> = ({ report, groupBy, onGroup, onExport }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [open, setOpen] = useState<Set<string>>(new Set());
  const pair = groupBy === 'category_caller';
  const groups = USAGE_GROUPS.filter((g) => report.groups.includes(g));

  const keyName = (g: GroupBy, key: string): string => {
    if (key === '—') return '—';
    switch (g) {
      case 'category': return categoryLabel(key, t);
      case 'caller': return callerLabel(key, t);
      case 'origin': return originLabel(key, t);
      case 'error': return errorTypeLabel(key, t);
      case 'result': return resultLabel(key, t);
      case 'arm': return key.toUpperCase();
      default: return key;
    }
  };
  const names = (r: UsageRow): [string, string] => {
    if (pair) {
      const [category, ...caller] = r.key.split('|');
      return [categoryLabel(category, t), callerLabel(caller.join('|'), t)];
    }
    return [r.label || keyName(groupBy, r.key), ''];
  };

  const toggle = (key: string) => setOpen((s) => {
    const next = new Set(s);
    if (!next.delete(key)) next.add(key);
    return next;
  });

  const heads = [...(pair ? [t('Category'), t('Caller')] : [groupLabel(groupBy, t)]), t('Requests'), t('Errors'), t('Tokens'), t('Cost'), t('Last')];
  const cols = pair ? [28, 190, undefined, 90, 120, 80, 80, 80] : [28, undefined, 90, 120, 80, 80, 80];
  const total = report.totals;

  const chain = (r: UsageRow) => {
    const hops = Object.entries(r.profiles ?? {}).sort((a, b) => b[1] - a[1]);
    return hops.map(([profile, tried]) => {
      const failed = r.profile_errors?.[profile] ?? 0;
      const causes = Object.entries(r.profile_causes?.[profile] ?? {}).sort((a, b) => b[1] - a[1]);
      const last = r.profile_last?.[profile];
      const line = [
        t('{count} tried', { count: fmtCount(tried) }),
        t('{count} answered', { count: fmtCount(tried - failed) }),
        t('{count} failed', { count: fmtCount(failed) }),
        ...(last ? [`${t('last')} ${fmtTime(last)}`] : []),
        ...(causes[0] ? [errorTypeLabel(causes[0][0], t)] : []),
      ].join(' · ');
      return (
        <Typography key={profile} noWrap title={`${profile} — ${line}`} sx={{ fontSize: '0.78rem', color: P.textSecondary, py: 0.15, fontVariantNumeric: 'tabular-nums' }}>
          <Box component="span" sx={{ color: P.textPrimary, mr: 1 }}>{profile}</Box>{line}
        </Typography>
      );
    });
  };

  return (
    <Box sx={{ minWidth: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, flexWrap: 'wrap' }}>
        <FormControl size="small" sx={{ width: 220, flexShrink: 0 }}>
          <InputLabel id="ai-usage-group">{t('Group by')}</InputLabel>
          <Select labelId="ai-usage-group" label={t('Group by')} value={groups.includes(groupBy) ? groupBy : ''} onChange={(e) => onGroup(e.target.value as GroupBy)} MenuProps={{ transitionDuration: 0 }}>
            {groups.map((g) => <MenuItem key={g} value={g}>{groupLabel(g, t)}</MenuItem>)}
          </Select>
        </FormControl>
        <Box sx={{ flex: 1 }} />
        <Button size="small" variant="outlined" startIcon={<DownloadIcon fontSize="small" />} onClick={onExport} disableRipple sx={{ textTransform: 'none', transition: 'none', flexShrink: 0, whiteSpace: 'nowrap' }}>
          {t('Export CSV')}
        </Button>
      </Box>
      {report.rows.length === 0 ? (
        <Typography sx={{ color: P.textMuted, py: 3 }}>{t('No AI requests in this period.')}</Typography>
      ) : (
        <TableContainer sx={{ minWidth: 0, maxWidth: '100%', border: `1px solid ${P.borderColor}`, bgcolor: P.surface }}>
          <Table size="small" sx={{ minWidth: pair ? 760 : 640, tableLayout: 'fixed' }}>
            <colgroup>{cols.map((w, i) => <col key={i} style={w ? { width: w } : undefined} />)}</colgroup>
            <TableHead>
              <TableRow>
                <TableCell sx={headSx} />
                {heads.map((h, i) => <TableCell key={h} align={i >= heads.length - 5 ? 'right' : 'left'} sx={headSx}>{h}</TableCell>)}
              </TableRow>
            </TableHead>
            <TableBody>
              {report.rows.map((r) => {
                const [a, b] = names(r);
                const isOpen = open.has(r.key);
                const tokens = (r.tokens_in ?? 0) + (r.tokens_out ?? 0);
                const errColor = r.error_rate >= 0.25 ? P.error : r.error_rate >= 0.05 ? P.warning : P.textSecondary;
                return (
                  <React.Fragment key={r.key}>
                    <TableRow hover onClick={() => toggle(r.key)} sx={{ cursor: 'pointer' }}>
                      <TableCell sx={{ ...cellSx, px: 0.5, overflow: 'visible' }}>{isOpen ? <ExpandLess sx={{ fontSize: 18 }} /> : <ExpandMore sx={{ fontSize: 18 }} />}</TableCell>
                      <TableCell title={a} sx={cellSx}>{a}</TableCell>
                      {pair && <TableCell title={b} sx={cellSx}>{b}</TableCell>}
                      <TableCell align="right" sx={cellSx}>{orDash(r.calls, fmtCount)}</TableCell>
                      <TableCell align="right" title={r.main_error ? errorTypeLabel(r.main_error, t) : ''} sx={{ ...cellSx, color: errColor }}>
                        {r.errors ? `${fmtCount(r.errors)} · ${fmtPct(r.error_rate)}` : '—'}
                      </TableCell>
                      <TableCell align="right" sx={cellSx}>{tokens ? fmtTokens(tokens) : '—'}</TableCell>
                      <TableCell align="right" sx={cellSx}>{fmtCost(r.cost) ?? '—'}</TableCell>
                      <TableCell align="right" title={r.last_ts ?? ''} sx={{ ...cellSx, fontVariantNumeric: 'tabular-nums' }}>{fmtTime(r.last_ts)}</TableCell>
                    </TableRow>
                    {isOpen && (
                      <TableRow>
                        <TableCell sx={{ ...cellSx, bgcolor: P.hoverBg }} />
                        <TableCell colSpan={cols.length - 1} sx={{ ...cellSx, bgcolor: P.hoverBg }}>{chain(r)}</TableCell>
                      </TableRow>
                    )}
                  </React.Fragment>
                );
              })}
              <TableRow>
                <TableCell sx={{ ...cellSx, fontWeight: 600 }} />
                <TableCell sx={{ ...cellSx, fontWeight: 600 }} colSpan={pair ? 2 : 1}>{t('Total')}</TableCell>
                <TableCell align="right" sx={{ ...cellSx, fontWeight: 600 }}>{orDash(total.calls, fmtCount)}</TableCell>
                <TableCell align="right" sx={{ ...cellSx, fontWeight: 600 }}>{total.errors ? fmtCount(total.errors) : '—'}</TableCell>
                <TableCell align="right" sx={{ ...cellSx, fontWeight: 600 }}>{fmtTokens((total.tokens_in ?? 0) + (total.tokens_out ?? 0))}</TableCell>
                <TableCell align="right" sx={{ ...cellSx, fontWeight: 600 }}>{fmtCost(total.cost) ?? '—'}</TableCell>
                <TableCell sx={cellSx} />
              </TableRow>
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  );
};
