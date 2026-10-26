/**
 * Benchmarks of Monitoring → AI usage (TASK-143): which named model answers a usage key best.
 *
 * One row per run — a usage key, a model profile, the frozen case set — with the pass rate, the cost
 * and the latency. Clicking a run opens the cases of that run: every case, what it asked, and whether
 * the model's answer passed the check.
 */
import { ExpandMore as ExpandIcon } from '@mui/icons-material';
import { Box, Chip, FormControl, InputLabel, LinearProgress, MenuItem, Select, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material';
import React, { useMemo, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { TYPOGRAPHY } from '../../constants/typography';

import type { BenchmarkCase, BenchmarkRun, BenchmarksReport } from './api';
import { fmtCount, fmtDateTime, fmtSeconds } from './format';

const pct = (v: number) => `${Math.round(v * 100)} %`;

const usd = (v: number) => (v > 0 ? `$${v < 0.01 ? v.toFixed(6) : v.toFixed(4)}` : '—');

const RunRow: React.FC<{
  run: BenchmarkRun;
  cases: BenchmarkCase[];
  label: string;
  expanded: boolean;
  onToggle: () => void;
}> = ({ run, cases, label, expanded, onToggle }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const pass = run.pass_rate >= 1;
  const color = pass ? P.success : run.passed > 0 ? P.warning : P.error;
  return (
    <>
      <TableRow hover onClick={onToggle} sx={{ cursor: 'pointer' }}>
        <TableCell sx={{ whiteSpace: 'nowrap' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
            <ExpandIcon sx={{ fontSize: TYPOGRAPHY.body.size, transform: expanded ? 'rotate(90deg)' : 'none', transition: 'transform 120ms', color: P.textMuted }} />
            <Typography noWrap title={run.usage_key} sx={{ fontSize: TYPOGRAPHY.caption.size }}>{label}</Typography>
          </Box>
        </TableCell>
        <TableCell sx={{ whiteSpace: 'nowrap' }}>
          <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.5 }}>
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size }}>{run.profile}</Typography>
            {run.model && run.model !== run.profile && (
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{run.model}</Typography>
            )}
          </Box>
        </TableCell>
        <TableCell sx={{ width: 180 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <LinearProgress
              variant="determinate"
              value={Math.round(run.pass_rate * 100)}
              sx={{ flex: 1, height: 6, borderRadius: 3, bgcolor: `${P.textMuted}22`, '& .MuiLinearProgress-bar': { bgcolor: color } }}
            />
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color }}>{`${run.passed}/${run.scored ?? run.cases}`}</Typography>
          </Box>
        </TableCell>
        <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>{pct(run.pass_rate)}</TableCell>
        <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>{usd(run.cost)}</TableCell>
        <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>{fmtSeconds(run.ms)}</TableCell>
        <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>{`${fmtCount(run.tokens_in)}/${fmtCount(run.tokens_out)}`}</TableCell>
        <TableCell sx={{ whiteSpace: 'nowrap' }}>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
            {run.ts ? fmtDateTime(run.ts) : '—'}
          </Typography>
        </TableCell>
      </TableRow>
      {expanded && (
        <TableRow>
          <TableCell colSpan={8} sx={{ bgcolor: `${P.textMuted}0a`, py: 1.5 }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
              {cases.length === 0 && (
                <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{t('No case rows for this run.')}</Typography>
              )}
              {cases.map((c) => (
                <Box key={c.id} sx={{ display: 'flex', alignItems: 'center', gap: 1, fontSize: TYPOGRAPHY.caption.size }}>
                  <Chip
                    size="small"
                    label={c.ok ? t('pass') : t('fail')}
                    sx={{ height: 20, fontSize: TYPOGRAPHY.microMeta.size, bgcolor: c.ok ? `${P.success}22` : `${P.error}22`, color: c.ok ? P.success : P.error }}
                  />
                  <Typography sx={{ fontFamily: 'monospace', color: P.textMuted }}>{c.case_id}</Typography>
                  <Typography sx={{ color: P.textMuted }}>{c.kind}</Typography>
                  {c.error && <Typography sx={{ color: P.error }}>{c.error}</Typography>}
                  <Box sx={{ flex: 1 }} />
                  <Typography sx={{ color: P.textMuted }}>{fmtSeconds(c.ms)}</Typography>
                  <Typography sx={{ color: P.textMuted }}>{usd(Number(c.cost ?? 0))}</Typography>
                </Box>
              ))}
            </Box>
          </TableCell>
        </TableRow>
      )}
    </>
  );
};

export const BenchmarksTab: React.FC<{ report: BenchmarksReport | null; loading?: boolean; failed?: boolean; onReload?: () => void }> = ({
  report,
  loading,
  failed,
  onReload,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [open, setOpen] = useState<string | null>(null);
  const [picked, setKey] = useState<string>('');
  // A key that has no run in the new period is no longer offered: show all instead of an empty table.
  const key = (report?.usage_keys ?? []).includes(picked) ? picked : '';
  const labelOf = (k: string) => report?.usage_labels?.[k] || k;

  const runs = useMemo(() => {
    const all = report?.runs ?? [];
    return key ? all.filter((r) => r.usage_key === key) : all;
  }, [report, key]);

  if (loading) return <Typography sx={{ color: P.textMuted, py: 2 }}>{t('Loading…')}</Typography>;
  if (failed) {
    return (
      <Box sx={{ py: 2 }}>
        <Typography sx={{ color: P.error, mb: 1 }}>{t('The benchmark results could not be loaded.')}</Typography>
        {onReload && <Typography component="button" onClick={onReload} sx={{ color: P.accent, cursor: 'pointer', background: 'none', border: 'none', p: 0 }}>{t('Retry')}</Typography>}
      </Box>
    );
  }
  if (runs.length === 0) {
    return (
      <Box sx={{ py: 2 }}>
        <Typography sx={{ color: P.textMuted }}>
          {t('No benchmark runs in this period.')}
        </Typography>
      </Box>
    );
  }

  const casesOf = (runId: string) => (report?.cases ?? []).filter((c) => c.run_id === runId);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      <FormControl size="small" sx={{ maxWidth: 360, minWidth: 220 }}>
        <InputLabel id="ai-benchmark-usage-key" shrink>{t('Feature')}</InputLabel>
        <Select
          labelId="ai-benchmark-usage-key"
          label={t('Feature')}
          notched
          displayEmpty
          value={key}
          onChange={(e) => setKey(e.target.value)}
          renderValue={(v) => (
            <Box component="span" title={v || undefined} sx={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {v ? labelOf(v) : t('All features')}
            </Box>
          )}
          MenuProps={{ transitionDuration: 0 }}
        >
          <MenuItem value="">{t('All features')}</MenuItem>
          {(report?.usage_keys ?? []).map((k) => (
            <MenuItem key={k} value={k} title={k}>{labelOf(k)}</MenuItem>
          ))}
        </Select>
      </FormControl>

      <TableContainer sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 2, bgcolor: P.surface, overflowX: 'auto' }}>
        <Table size="small" sx={{ tableLayout: 'fixed' }}>
          {/* S3: the column widths are fixed, so a long model name or a big number never re-flows the rows. */}
          <colgroup>
            <col />
            <col style={{ width: 190 }} />
            <col style={{ width: 170 }} />
            <col style={{ width: 90 }} />
            <col style={{ width: 100 }} />
            <col style={{ width: 90 }} />
            <col style={{ width: 120 }} />
            <col style={{ width: 170 }} />
          </colgroup>
          <TableHead>
            <TableRow>
              <TableCell>{t('Feature')}</TableCell>
              <TableCell>{t('Model')}</TableCell>
              <TableCell>{t('Cases')}</TableCell>
              <TableCell align="right">{t('Pass rate')}</TableCell>
              <TableCell align="right">{t('Cost')}</TableCell>
              <TableCell align="right">{t('Latency')}</TableCell>
              <TableCell align="right">{t('Tokens in/out')}</TableCell>
              <TableCell>{t('When')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {runs.map((run) => (
              <RunRow
                key={run.run_id}
                run={run}
                cases={casesOf(run.run_id)}
                label={labelOf(run.usage_key)}
                expanded={open === run.run_id}
                onToggle={() => setOpen(open === run.run_id ? null : run.run_id)}
              />
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};
