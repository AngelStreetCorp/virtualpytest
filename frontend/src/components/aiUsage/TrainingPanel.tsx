/**
 * Training data next to the call log (TASK-27 samples): counts as tiles, samples per family with a total row,
 * and — only once a labelled sample is linked to a call — production accuracy per model next to its cost.
 */
import { Box, Link, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material';
import { ChevronRight, ExpandMore } from '@mui/icons-material';
import React, { useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';

import { StatTiles } from '../common/PageChrome';

import { TrainingReport, UsageQuery, fetchTrainingReport } from './api';
import { fmtCost, fmtCount, fmtPct } from './format';
import { PanelError } from './PanelError';
import { cellSx as cell, headSx as head } from './tableStyles';
import { useAiLoad } from './useAiLoad';
import { TYPOGRAPHY } from '../../constants/typography';


type Group = NonNullable<TrainingReport['groups']>[number];
interface Skill { family: string; samples: number; labelled: number; conflicts: number; by_source: Record<string, number>; devices: Group[] }

/** One row per skill (family), summing its device models; busiest first. */
const skillRows = (groups: Group[]): Skill[] => {
  const by = new Map<string, Skill>();
  groups.forEach((g) => {
    const k = by.get(g.family) ?? { family: g.family, samples: 0, labelled: 0, conflicts: 0, by_source: {}, devices: [] };
    k.samples += g.samples;
    k.labelled += g.labelled;
    k.conflicts += g.conflicts;
    Object.entries(g.by_source ?? {}).forEach(([src, n]) => { k.by_source[src] = (k.by_source[src] ?? 0) + n; });
    k.devices.push(g);
    by.set(g.family, k);
  });
  return [...by.values()].sort((a, b) => b.samples - a.samples);
};

const skillName = (family: string, t: (k: string) => string): string => {
  switch (family) {
    case 'screen-id': return t('Screen recognition');
    case 'focus': return t('Focus');
    case 'banner': return t('Channel banner');
    case 'menu': return t('Language menu');
    case 'av-fault': return t('Video / audio faults');
    case 'content-type': return t('Content type');
    default: return family === 'other' ? t('Other examples') : family;
  }
};
const skillHint = (family: string, t: (k: string) => string): string => {
  switch (family) {
    case 'screen-id': return t('which screen is this');
    case 'focus': return t('which item is highlighted');
    case 'banner': return t('read it after a zap');
    case 'menu': return t('read audio / subtitle options');
    case 'av-fault': return t('freeze, black, no signal');
    case 'content-type': return t('live, ad, menu…');
    default: return '';
  }
};

export const TrainingPanel: React.FC<{ query: UsageQuery }> = ({ query }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (key: string) => setOpen((s) => { const next = new Set(s); if (!next.delete(key)) next.add(key); return next; });
  const { data, failed, loading, reload } = useAiLoad('training data', () => fetchTrainingReport(query), [query.team, query.hours]);

  if (failed) return <PanelError what={t('the training data')} onRetry={reload} />;
  if (!data) return <Box sx={{ minHeight: 80 }} />;
  const totals = data.totals;
  if (!totals || totals.samples === 0) {
    return <Typography sx={{ color: P.textMuted, py: 2, minHeight: loading ? 80 : undefined }}>{t('No training samples yet.')}</Typography>;
  }
  const accuracy = data.accuracy ?? [];
  const groups = data.groups ?? [];

  const skills = skillRows(groups);
  const COLS = '20px 280px 110px minmax(150px, 1fr) minmax(0, 1.6fr) 100px';
  const sourceWords = (by: Record<string, number> | undefined): string => {
    const parts: [string, number | undefined][] = [[t('Person'), by?.human], [t('Test run'), by?.run], [t('AI'), by?.teacher]];
    return parts.filter(([, n]) => n).map(([label, n]) => `${label} ${fmtCount(n ?? 0)}`).join(' · ') || '—';
  };
  const labelledCell = (labelled: number, samples: number) => (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
      <Typography noWrap sx={{ fontSize: TYPOGRAPHY.body.size, fontVariantNumeric: 'tabular-nums', minWidth: 96 }}>
        {fmtCount(labelled)} · {samples ? fmtPct(labelled / samples) : '—'}
      </Typography>
      <Box sx={{ flex: 1, height: 6, bgcolor: P.hoverBg, borderRadius: 0.5, overflow: 'hidden', minWidth: 30 }}>
        <Box sx={{ width: `${samples ? (labelled / samples) * 100 : 0}%`, height: '100%', bgcolor: P.success }} />
      </Box>
    </Box>
  );
  const conflictCell = (n: number) => n > 0 ? (
    <Link component={RouterLink} to="/training-review" title={t('Two examples that look the same but have different answers. Click to review.')} onClick={(e: React.MouseEvent) => e.stopPropagation()} sx={{ color: P.warning, fontSize: TYPOGRAPHY.body.size }}>{fmtCount(n)}</Link>
  ) : <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}>–</Typography>;
  const gridRow = { display: 'grid', gridTemplateColumns: COLS, alignItems: 'center', columnGap: 1.5, px: 1, py: 0.75, minWidth: 880 } as const;
  const head2 = (label: string, right = false) => <Typography key={label} noWrap sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, textAlign: right ? 'right' : 'left' }}>{label}</Typography>;
  const skillTable = (
    <Box sx={{ border: `1px solid ${P.borderColor}`, bgcolor: P.surface, minWidth: 0, overflowX: 'auto' }}>
      <Box sx={{ ...gridRow, py: 0.5, borderBottom: `1px solid ${P.borderColor}` }}>
        <Box />{head2(t('Skill'))}{head2(t('Examples'), true)}{head2(t('Labelled'))}{head2(t('Labelled by'))}{head2(t('Conflicts'), true)}
      </Box>
      {skills.map((k) => {
        const isOpen = open.has(k.family);
        return (
          <React.Fragment key={k.family}>
            <Box onClick={() => toggle(k.family)} sx={{ ...gridRow, cursor: 'pointer', borderTop: `1px solid ${P.borderColor}`, '&:hover': { bgcolor: P.hoverBg } }}>
              {isOpen ? <ExpandMore sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} /> : <ChevronRight sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} />}
              <Box sx={{ minWidth: 0 }}>
                <Typography noWrap title={skillName(k.family, t)} sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600 }}>{skillName(k.family, t)}</Typography>
                <Typography noWrap title={skillHint(k.family, t)} sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{skillHint(k.family, t)}</Typography>
              </Box>
              <Typography noWrap sx={{ fontSize: TYPOGRAPHY.body.size, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtCount(k.samples)}</Typography>
              {labelledCell(k.labelled, k.samples)}
              <Typography noWrap title={sourceWords(k.by_source)} sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>{sourceWords(k.by_source)}</Typography>
              <Box sx={{ textAlign: 'right' }}>{conflictCell(k.conflicts)}</Box>
            </Box>
            {isOpen && k.devices.map((g) => (
              <Box key={g.device_model} sx={{ ...gridRow, bgcolor: P.hoverBg, py: 0.5 }}>
                <Box />
                <Typography noWrap title={g.device_model} sx={{ fontSize: TYPOGRAPHY.body.size, pl: 1 }}>{g.device_model}</Typography>
                <Typography noWrap sx={{ fontSize: TYPOGRAPHY.caption.size, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtCount(g.samples)}</Typography>
                {labelledCell(g.labelled, g.samples)}
                <Typography noWrap title={sourceWords(g.by_source)} sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>{sourceWords(g.by_source)}</Typography>
                <Box sx={{ textAlign: 'right' }}>{conflictCell(g.conflicts)}</Box>
              </Box>
            ))}
          </React.Fragment>
        );
      })}
    </Box>
  );

  return (
    <Box sx={{ minWidth: 0 }}>
      <StatTiles
        columns={5}
        tiles={[
          { label: t('Samples'), value: fmtCount(totals.samples) },
          { label: t('Labelled'), value: fmtCount(totals.labelled) },
          { label: t('Label conflicts'), value: fmtCount(totals.conflicts), color: totals.conflicts ? P.warning : undefined,
            footer: totals.conflicts > 0 ? <Link component={RouterLink} to="/training-review" sx={{ fontSize: TYPOGRAPHY.caption.size }}>{t('Review')}</Link> : undefined },
          { label: t('Linked to a call'), value: fmtCount(totals.linked) },
          { label: t('Teams opted in'), value: fmtCount(data.opted_in_teams ?? 0) },
        ]}
      />
      <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textSecondary, mb: 1 }}>{t('Examples saved for teaching our own models. A labelled example has the right answer.')}</Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', xl: accuracy.length ? '1fr 1fr' : '1fr' }, gap: 2 }}>
        {skillTable}
        {accuracy.length > 0 && (
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, mb: 0.5 }}>
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
