/**
 * Training data next to the call log (TASK-27 samples): counts as tiles, samples per family with a total row,
 * and — only once a labelled sample is linked to a call — production accuracy per model next to its cost.
 */
import { Box, Link, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material';
import React from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';

import { StatTiles } from '../common/PageChrome';

import { UsageQuery, fetchTrainingReport } from './api';
import { fmtCost, fmtCount, fmtPct } from './format';
import { PanelError } from './PanelError';
import { cellSx as cell, headSx as head } from './tableStyles';
import { useAiLoad } from './useAiLoad';


export const TrainingPanel: React.FC<{ query: UsageQuery }> = ({ query }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { data, failed, loading, reload } = useAiLoad('training data', () => fetchTrainingReport(query), [query.team]);

  if (failed) return <PanelError what={t('the training data')} onRetry={reload} />;
  if (!data) return <Box sx={{ minHeight: 80 }} />;
  const totals = data.totals;
  if (!totals || totals.samples === 0) {
    return <Typography sx={{ color: P.textMuted, py: 2, minHeight: loading ? 80 : undefined }}>{t('No training samples yet.')}</Typography>;
  }
  const accuracy = data.accuracy ?? [];
  const groups = data.groups ?? [];
  const sum = (pick: (g: (typeof groups)[number]) => number) => groups.reduce((n, g) => n + pick(g), 0);

  return (
    <Box sx={{ minWidth: 0 }}>
      <StatTiles
        columns={5}
        tiles={[
          { label: t('Samples'), value: fmtCount(totals.samples) },
          { label: t('Labelled'), value: fmtCount(totals.labelled) },
          { label: t('Label conflicts'), value: fmtCount(totals.conflicts), color: totals.conflicts ? P.warning : undefined,
            footer: totals.conflicts > 0 ? <Link component={RouterLink} to="/training-review" sx={{ fontSize: '0.72rem' }}>{t('Review')}</Link> : undefined },
          { label: t('Linked to a call'), value: fmtCount(totals.linked) },
          { label: t('Teams opted in'), value: fmtCount(data.opted_in_teams ?? 0) },
        ]}
      />
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', xl: accuracy.length ? '1fr 1fr' : '1fr' }, gap: 2 }}>
        <TableContainer sx={{ border: `1px solid ${P.borderColor}`, bgcolor: P.surface, minWidth: 0 }}>
          <Table size="small" sx={{ minWidth: 640, tableLayout: 'fixed' }}>
            <colgroup>
              <col style={{ width: 110 }} />
              <col />
              <col style={{ width: 90 }} />
              <col style={{ width: 90 }} />
              <col style={{ width: 150 }} />
              <col style={{ width: 90 }} />
            </colgroup>
            <TableHead>
              <TableRow>
                <TableCell sx={head}>{t('Family')}</TableCell>
                <TableCell sx={head}>{t('Device model')}</TableCell>
                <TableCell align="right" sx={head}>{t('Samples')}</TableCell>
                <TableCell align="right" sx={head}>{t('Labelled')}</TableCell>
                <TableCell align="right" sx={head}>{t('Human / run / AI')}</TableCell>
                <TableCell align="right" sx={head}>{t('Conflicts')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {groups.slice(0, 12).map((g) => (
                <TableRow key={`${g.family}/${g.device_model}`}>
                  <TableCell title={g.family} sx={cell}>{g.family}</TableCell>
                  <TableCell title={g.device_model} sx={cell}>{g.device_model}</TableCell>
                  <TableCell align="right" sx={cell}>{fmtCount(g.samples)}</TableCell>
                  <TableCell align="right" sx={cell}>{fmtCount(g.labelled)}</TableCell>
                  <TableCell align="right" sx={{ ...cell, color: P.textSecondary }}>{g.by_source?.human ?? '—'} / {g.by_source?.run ?? '—'} / {g.by_source?.teacher ?? '—'}</TableCell>
                  <TableCell align="right" sx={{ ...cell, color: g.conflicts ? P.warning : P.textSecondary }}>{g.conflicts || '–'}</TableCell>
                </TableRow>
              ))}
              <TableRow>
                <TableCell colSpan={2} sx={{ ...cell, fontWeight: 600 }}>{t('Total')}</TableCell>
                <TableCell align="right" sx={{ ...cell, fontWeight: 600 }}>{fmtCount(sum((g) => g.samples))}</TableCell>
                <TableCell align="right" sx={{ ...cell, fontWeight: 600 }}>{fmtCount(sum((g) => g.labelled))}</TableCell>
                <TableCell sx={cell} />
                <TableCell align="right" sx={{ ...cell, fontWeight: 600 }}>{sum((g) => g.conflicts) || '–'}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </TableContainer>
        {accuracy.length > 0 && (
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontSize: '0.75rem', color: P.textMuted, mb: 0.5 }}>
              {t('Production accuracy per model (labelled samples) and cost per call')}
            </Typography>
            <TableContainer sx={{ border: `1px solid ${P.borderColor}`, bgcolor: P.surface }}>
              <Table size="small" sx={{ minWidth: 560, tableLayout: 'fixed' }}>
                <colgroup>
                  <col />
                  <col style={{ width: 170 }} />
                  <col style={{ width: 90 }} />
                  <col style={{ width: 90 }} />
                  <col style={{ width: 120 }} />
                </colgroup>
                <TableHead>
                  <TableRow>
                    <TableCell sx={head}>{t('Feature')}</TableCell>
                    <TableCell sx={head}>{t('Model')}</TableCell>
                    <TableCell align="right" sx={head}>{t('Labelled')}</TableCell>
                    <TableCell align="right" sx={head}>{t('Accuracy')}</TableCell>
                    <TableCell align="right" sx={head}>{t('Cost per call')}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {accuracy.map((a) => (
                    <TableRow key={`${a.usage}/${a.profile}`}>
                      <TableCell title={a.usage} sx={cell}>{a.label}</TableCell>
                      <TableCell title={a.model} sx={cell}>{a.model}</TableCell>
                      <TableCell align="right" sx={cell}>{fmtCount(a.labelled)}</TableCell>
                      <TableCell align="right" sx={{ ...cell, color: a.accuracy >= 0.9 ? P.success : a.accuracy >= 0.7 ? P.warning : P.error }}>{fmtPct(a.accuracy)}</TableCell>
                      <TableCell align="right" sx={cell}>{fmtCost(a.avg_cost) ?? '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Box>
        )}
      </Box>
    </Box>
  );
};
