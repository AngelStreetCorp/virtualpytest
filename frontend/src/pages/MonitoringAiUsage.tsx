/**
 * Monitoring → AI usage (TASK-147 redesign): three levels, three clicks at most, all state in the URL.
 * 1. Overview: Spend · Calls · Failing now · Wasted, calls per hour, calls by provider and by feature.
 * 2. Group (`?provider=`, `?feature=`, `?user=` or `?host=`): who uses it or where it goes (`&pick=` filters the
 *    calls), its models, its calls (`&res=failed`).
 * 3. Call (`&call=<request id>`, `&n=` / `&first=` for a folded run of failures).
 * Side views: `?view=budget` (budgets, from Spend) and `?view=training` (training data). Same layout on a phone.
 * `?project=` (the project page's link) scopes every level to one project; its chip in the header removes it.
 * One bundle serves servers on different code versions: a server without the AI usage API says so.
 */
import { Alert, Box, CircularProgress, Link, MenuItem, Select, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import React, { useCallback, useMemo } from 'react';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';

import {
  AiUsageMissingError,
  EMPTY_QUERY,
  RangeHours,
  UsageQuery,
  fetchAiUsage,
  usageExportUrl,
} from '../components/aiUsage/api';
import { BudgetPanel } from '../components/aiUsage/BudgetPanel';
import { PanelError } from '../components/aiUsage/PanelError';
import { TrainingPanel } from '../components/aiUsage/TrainingPanel';
import { UsageCall } from '../components/aiUsage/UsageCall';
import { GroupKind, UsageGroup, groupName } from '../components/aiUsage/UsageGroup';
import { UsageOverview } from '../components/aiUsage/UsageOverview';
import { useAiLoad } from '../components/aiUsage/useAiLoad';
import { PageTitle, pageSurfaceSx, segmentedSx } from '../components/common/PageChrome';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { AppIcon } from '../constants/icons';
import { TYPOGRAPHY } from '../constants/typography';
import { useI18n } from '../i18n/useI18n';
import { apiClient } from '../utils/apiClient';

const HOURS: RangeHours[] = [1, 24, 168, 720];
const SETTINGS_AI_HREF = '/configuration/settings?tab=ai';
type SideView = 'budget' | 'training';

const MonitoringAiUsage: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [sp, setSp] = useSearchParams();
  const hours = Number(sp.get('period')) as RangeHours;
  const query: UsageQuery = useMemo(() => ({ ...EMPTY_QUERY, hours: HOURS.includes(hours) ? hours : EMPTY_QUERY.hours, team: sp.get('team') ?? '', project: sp.get('project') ?? '' }), [hours, sp]);
  const KINDS: GroupKind[] = ['provider', 'feature', 'user', 'host'];
  const kind: GroupKind | null = KINDS.find((k) => sp.get(k)) ?? null;
  const groupId = kind ? sp.get(kind) ?? '' : '';
  const call = sp.get('call') ?? '';
  const view = (['budget', 'training'] as SideView[]).find((v) => v === sp.get('view')) ?? null;

  /** Move to another level: keeps period and team, replaces everything else. */
  const go = useCallback((params: Record<string, string>) => {
    const next = new URLSearchParams();
    ['period', 'team', 'project'].forEach((k) => { const v = sp.get(k); if (v) next.set(k, v); });
    Object.entries(params).forEach(([k, v]) => v && next.set(k, v));
    setSp(next);
    window.scrollTo(0, 0);
  }, [sp, setSp]);
  /** Change a parameter in place (filters inside a level). */
  const patch = useCallback((params: Record<string, string>) => {
    const next = new URLSearchParams(sp);
    Object.entries(params).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setSp(next, { replace: true });
  }, [sp, setSp]);

  /** 30 days reads the hourly rollup: no single calls and no users. Leave those views instead of failing. */
  const changePeriod = (v: RangeHours) => {
    const period = v === EMPTY_QUERY.hours ? '' : String(v);
    if (v > 168 && kind === 'user') return go({ period });
    if (v > 168 && call) return patch({ period, call: '', n: '', first: '' });
    return patch({ period });
  };
  const base = useAiLoad('usage', () => fetchAiUsage(query, 'category'), [query.hours, query.team, query.project]);
  const byProvider = useAiLoad('usage by provider', () => fetchAiUsage(query, 'endpoint'), [query.hours, query.team, query.project], !kind && !call && !view);
  const missing = base.failed && base.error instanceof AiUsageMissingError;
  const report = base.data;

  const exportCsv = async () => {
    const response = await apiClient(usageExportUrl(query, 'category'));
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `ai-usage-${query.hours}h.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const groupParams: Record<string, string> = kind ? { [kind]: groupId, pick: sp.get('pick') ?? '', res: sp.get('res') ?? '' } : {};
  const crumbs: { label: string; to?: Record<string, string> }[] = [{ label: t('AI usage'), to: {} }];
  if (report && kind) crumbs.push({ label: groupName(kind, groupId, report, t), to: groupParams });
  if (view === 'budget') crumbs.push({ label: t('Budgets') });
  if (view === 'training') crumbs.push({ label: t('Training data') });
  if (call) crumbs.push({ label: t('Call') });
  const last = crumbs.length - 1;

  const teams = report?.options?.team ?? [];
  const periodLabel: Record<RangeHours, string> = { 1: t('1 h'), 24: t('24 h'), 168: t('7 d'), 720: t('30 d') };

  const body = (() => {
    if (!report) return null;
    if (call) {
      return <UsageCall requestId={call} query={query} base={report} repeat={Number(sp.get('n')) || 1} first={sp.get('first') ?? ''} onBack={() => go(groupParams)} />;
    }
    if (view === 'budget') return <BudgetPanel />;
    if (view === 'training') return <TrainingPanel query={query} />;
    if (kind) {
      return (
        <UsageGroup
          kind={kind}
          id={groupId}
          query={query}
          base={report}
          pick={sp.get('pick') ?? ''}
          failedOnly={sp.get('res') === 'failed'}
          onPick={(key) => patch({ pick: sp.get('pick') === key ? '' : key })}
          onFailedOnly={(on) => patch({ res: on ? 'failed' : '' })}
          onOpenCall={(run) => run.call.request_id && go({ ...groupParams, call: run.call.request_id, n: run.n > 1 ? String(run.n) : '', first: run.n > 1 ? run.first : '' })}
        />
      );
    }
    return (
      <UsageOverview
        report={report}
        byProvider={byProvider.data}
        query={query}
        nav={{ provider: (id) => go({ provider: id }), group: (dim, id) => go({ [dim]: id }), view: (v) => go({ view: v }) }}
        onExport={exportCsv}
      />
    );
  })();

  return (
    <Box sx={[{ p: { xs: 1.5, sm: 2.5 }, maxWidth: 1400, width: '100%', minWidth: 0, boxSizing: 'border-box', mx: 'auto' }, ...[pageSurfaceSx(P)].flat()]}>
      <PageTitle
        title={
          <Box component="nav" aria-label={t('Breadcrumb')} sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap', minWidth: 0 }}>
            {crumbs.map((c, i) => (
              <React.Fragment key={i}>
                {i > 0 && <Box component="span" sx={{ color: P.textMuted }}>›</Box>}
                {i < last && c.to
                  ? <Link component="button" onClick={() => go(c.to ?? {})} sx={{ fontSize: TYPOGRAPHY.pageTitle.size, fontWeight: 500, color: P.textSecondary, textDecoration: 'none' }}>{c.label}</Link>
                  : <Typography component="span" sx={{ fontSize: TYPOGRAPHY.pageTitle.size, fontWeight: 600, lineHeight: 1.3 }}>{c.label}</Typography>}
              </React.Fragment>
            ))}
          </Box>
        }
        right={
          <>
            <ToggleButtonGroup exclusive size="small" value={query.hours} onChange={(_, v: RangeHours | null) => v && changePeriod(v)} sx={segmentedSx(P, 'sm')}>
              {HOURS.map((h) => <ToggleButton key={h} value={h} disableRipple>{periodLabel[h]}</ToggleButton>)}
            </ToggleButtonGroup>
            {query.project && (
              <Box component="button" type="button" onClick={() => patch({ project: '' })} sx={{ all: 'unset', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 0.5, px: 1, py: 0.25, borderRadius: 1.5, bgcolor: P.hoverBg, color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size }}>
                {t('Project')}: {report?.options?.project?.find((o) => o.key === query.project)?.label ?? query.project}<AppIcon name="close" />
              </Box>
            )}
            {teams.length > 1 && (
              <Select size="small" value={query.team} displayEmpty onChange={(e) => patch({ team: String(e.target.value) })} sx={{ fontSize: TYPOGRAPHY.body.size, minWidth: 140 }}>
                <MenuItem value="">{t('All teams')}</MenuItem>
                {teams.map((o) => <MenuItem key={o.key} value={o.key}>{o.label ?? o.key}</MenuItem>)}
              </Select>
            )}
            <Link component={RouterLink} to={SETTINGS_AI_HREF} sx={{ fontSize: TYPOGRAPHY.body.size, whiteSpace: 'nowrap' }}>{t('Settings')}</Link>
          </>
        }
      />
      {missing ? (
        <Alert severity="info">{t('This server does not have AI usage yet.')}</Alert>
      ) : (
        <>
          {report?.restricted_to_self && <Alert severity="info" sx={{ mb: 1.5 }}>{t('You see your own requests only.')}</Alert>}
          {base.failed && <PanelError what={t('AI usage')} onRetry={base.reload} />}
          {!report && !base.failed && <Box sx={{ display: 'flex', justifyContent: 'center', py: 4, minHeight: 120 }}><CircularProgress /></Box>}
          {report && <Box sx={{ opacity: base.loading ? 0.6 : 1, minWidth: 0 }}>{body}</Box>}
        </>
      )}
    </Box>
  );
};

export default MonitoringAiUsage;
