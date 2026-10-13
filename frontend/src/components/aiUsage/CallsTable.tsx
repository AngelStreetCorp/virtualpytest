/**
 * Newest requests as a table, one line each. Runs of identical consecutive failures fold into one line
 * ("64× No credit (402)  21:44 → 22:41") that opens on click. Run-report link and, only when a Langfuse
 * trace exists, a small conversation icon. "Turn · tools" appears only when a chat agent is in the list.
 */
import { DescriptionOutlined as RunIcon, ExpandLess, ExpandMore, OpenInNew as TraceIcon } from '@mui/icons-material';
import { Box, IconButton, Link, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tooltip, Typography } from '@mui/material';
import React, { useMemo, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { REPORT_ROUTES } from '../../types/reports';

import type { AiCall } from './api';
import { fmtCount, fmtSeconds, fmtTime, fmtTokens } from './format';
import { callerLabel, categoryLabel, errorTypeLabel, originLabel } from './labels';
import { cellSx as cell, headSx } from './tableStyles';

interface Item {
  key: string;
  calls: AiCall[];
}

const sameFailure = (a: AiCall, b: AiCall) =>
  !a.ok && !b.ok && a.usage_key === b.usage_key && a.error_type === b.error_type && (a.model ?? a.profile) === (b.model ?? b.profile);

export const groupCalls = (calls: AiCall[]): Item[] => {
  const items: Item[] = [];
  calls.forEach((c) => {
    const last = items[items.length - 1];
    if (last && sameFailure(last.calls[0], c)) last.calls.push(c);
    else items.push({ key: String(c.id), calls: [c] });
  });
  return items;
};

interface Props {
  calls: AiCall[];
  /** Show the feature column (the Calls tab lists every feature). */
  showFeature?: boolean;
  /** Items shown before "show more". */
  limit?: number;
}

export const CallsTable: React.FC<Props> = ({ calls, showFeature, limit = 40 }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [all, setAll] = useState(false);
  const items = useMemo(() => groupCalls(calls), [calls]);
  const shown = all ? items : items.slice(0, limit);
  const chat = calls.some((c) => c.turn_index != null);
  const widths = [150, ...(showFeature ? [220] : []), 170, undefined, 130, 90, ...(chat ? [100] : []), 150, 64];
  const toggle = (key: string) =>
    setOpen((s) => {
      const next = new Set(s);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  const row = (c: AiCall, key: string, opts?: { time?: string; result?: React.ReactNode; lead?: React.ReactNode; onClick?: () => void; count?: number }) => (
    <TableRow key={key} hover={Boolean(opts?.onClick)} onClick={opts?.onClick} sx={{ cursor: opts?.onClick ? 'pointer' : 'default' }}>
      <TableCell sx={{ ...cell, fontVariantNumeric: 'tabular-nums' }} title={c.ts}>
        <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.25 }}>
          {opts?.lead}
          {opts?.time ?? fmtTime(c.ts)}
        </Box>
      </TableCell>
      {showFeature && <TableCell title={c.usage_key} sx={cell}>{c.category ? `${categoryLabel(c.category, t)} · ` : ''}{c.usage_label ?? c.usage_key}</TableCell>}
      <TableCell title={[callerLabel(c.caller ?? `other:${c.origin}`, t), originLabel(c.origin, t), c.host_name].filter(Boolean).join(' · ')} sx={cell}>
        {callerLabel(c.caller ?? `other:${c.origin}`, t)}
        {c.host_name && <Box component="span" sx={{ color: P.textMuted, fontSize: '0.72rem' }}> · {c.host_name}</Box>}
      </TableCell>
      <TableCell title={`${c.model ?? c.profile} · ${c.endpoint}`} sx={cell}>
        {c.model ?? c.profile}
        {c.fallback_used && <Box component="span" sx={{ color: P.warning, fontSize: '0.72rem' }}> · {t('backup')}</Box>}
      </TableCell>
      <TableCell align="right" sx={cell}>{c.tokens_in || c.tokens_out ? `${fmtTokens(c.tokens_in)} / ${fmtTokens(c.tokens_out)}` : '—'}</TableCell>
      <TableCell align="right" sx={cell}>{fmtSeconds(c.latency_ms)}</TableCell>
      {chat && <TableCell sx={{ ...cell, color: P.textSecondary }}>{c.turn_index != null ? `${c.turn_index} · ${c.tool_calls ?? 0}` : '—'}</TableCell>}
      <TableCell sx={{ ...cell, color: c.ok ? P.success : P.error }}>
        {opts?.result ?? (c.ok ? t('ok') : errorTypeLabel(c.error_type, t) || t('failed'))}
      </TableCell>
      <TableCell sx={{ ...cell, overflow: 'visible' }}>
        {c.script_result_id && (
          <Tooltip title={t('Run report')}>
            <IconButton size="small" component={RouterLink} to={REPORT_ROUTES.summary('script', c.script_result_id)} onClick={(e) => e.stopPropagation()} sx={{ p: 0.25, color: P.textSecondary }}>
              <RunIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </Tooltip>
        )}
        {c.trace_url && (
          <Tooltip title={t('View conversation')}>
            <IconButton size="small" component={Link} href={c.trace_url} target="_blank" rel="noopener noreferrer" onClick={(e: React.MouseEvent) => e.stopPropagation()} sx={{ p: 0.25, color: P.textSecondary }}>
              <TraceIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </Tooltip>
        )}
      </TableCell>
    </TableRow>
  );

  return (
    <Box>
      <TableContainer sx={{ minWidth: 0, maxWidth: '100%', border: `1px solid ${P.borderColor}`, bgcolor: P.surface }}>
        <Table size="small" sx={{ minWidth: showFeature ? 1100 : 900, tableLayout: 'fixed' }}>
          <colgroup>{widths.map((w, i) => <col key={i} style={w ? { width: w } : undefined} />)}</colgroup>
          <TableHead>
            <TableRow>
              {[t('Time'), ...(showFeature ? [t('Feature')] : []), t('Caller'), t('Model'), t('Tokens in / out'), t('Latency'), ...(chat ? [t('Turn · tools')] : []), t('Result'), '']
                .map((h, i, arr) => (
                  <TableCell key={`${h}-${i}`} align={h === t('Tokens in / out') || h === t('Latency') ? 'right' : 'left'} sx={headSx}>
                    {i === arr.length - 1 ? '' : h}
                  </TableCell>
                ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {shown.flatMap((item) => {
              const first = item.calls[0];
              if (item.calls.length === 1) return [row(first, item.key)];
              const last = item.calls[item.calls.length - 1];
              const isOpen = open.has(item.key);
              const head = row(first, item.key, {
                time: `${fmtTime(last.ts)} → ${fmtTime(first.ts)}`,
                lead: isOpen ? <ExpandLess sx={{ fontSize: 16 }} /> : <ExpandMore sx={{ fontSize: 16 }} />,
                result: `${fmtCount(item.calls.length)}× ${errorTypeLabel(first.error_type, t) || t('failed')}`,
                onClick: () => toggle(item.key),
              });
              return isOpen ? [head, ...item.calls.slice(0, 50).map((c) => row(c, `${item.key}-${c.id}`))] : [head];
            })}
          </TableBody>
        </Table>
      </TableContainer>
      {items.length > limit && !all && (
        <Typography
          component="button"
          type="button"
          onClick={() => setAll(true)}
          sx={{ all: 'unset', cursor: 'pointer', fontSize: '0.78rem', color: P.accentText, mt: 0.75, '&:hover': { textDecoration: 'underline' } }}
        >
          {t('Show {count} more lines', { count: fmtCount(items.length - limit) })}
        </Typography>
      )}
    </Box>
  );
};
