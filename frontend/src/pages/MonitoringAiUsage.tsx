/**
 * Monitoring → AI usage (TASK-87 round 2): where the AI goes and whether it is worth it.
 * Header (title, errors badge, AI settings link), one filter bar shared by every tab (kept in the URL), and the
 * tabs Overview · Usage · Errors · Providers · Calls · Training (`?tab=`, each rendered when opened).
 * One bundle serves servers on different code versions: a field an older server does not send shows "—" and a
 * server without the AI usage API says so instead of failing. Palette colours, no motion.
 */
import { ErrorOutline as ErrorIcon } from '@mui/icons-material';
import { Alert, Box, CircularProgress, Link, Tab, Tabs, Typography } from '@mui/material';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';

import {
  AiUsageMissingError,
  EMPTY_QUERY,
  GroupBy,
  RangeHours,
  UsageQuery,
  UsageReport,
  fetchAiCalls,
  fetchAiUsage,
  usageExportUrl,
} from '../components/aiUsage/api';
import { CallsTable } from '../components/aiUsage/CallsTable';
import { ErrorsTab } from '../components/aiUsage/ErrorsTab';
import { FilterBar } from '../components/aiUsage/FilterBar';
import { OverviewTab } from '../components/aiUsage/OverviewTab';
import { PanelError } from '../components/aiUsage/PanelError';
import { ProvidersPanel } from '../components/aiUsage/ProvidersPanel';
import { TrainingPanel } from '../components/aiUsage/TrainingPanel';
import { UsageTab } from '../components/aiUsage/UsageTab';
import { useAiLoad } from '../components/aiUsage/useAiLoad';
import { PageTitle, pageSurfaceSx } from '../components/common/PageChrome';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { useI18n } from '../i18n/useI18n';
import { apiClient } from '../utils/apiClient';

type TabId = 'overview' | 'usage' | 'errors' | 'providers' | 'calls' | 'training';
const TABS: TabId[] = ['overview', 'usage', 'errors', 'providers', 'calls', 'training'];
const HOURS: RangeHours[] = [1, 24, 168, 720];
const SETTINGS_AI_HREF = '/configuration/settings?tab=ai';
const DEFAULT_GROUP: GroupBy = 'category_caller';
// Up to 7 days the per-call log answers every dimension; 30 days reads the hourly rollup.
const ROLLUP_GROUPS: GroupBy[] = ['usage', 'model', 'endpoint', 'team', 'origin', 'host', 'arm', 'category', 'caller', 'category_caller'];

const queryFrom = (sp: URLSearchParams): UsageQuery => {
  const hours = Number(sp.get('period')) as RangeHours;
  const result = sp.get('result');
  return {
    hours: HOURS.includes(hours) ? hours : EMPTY_QUERY.hours,
    team: sp.get('team') ?? '',
    project: sp.get('project') ?? '',
    user: sp.get('user') ?? '',
    provider: sp.get('provider') ?? '',
    model: sp.get('model') ?? '',
    result: result === 'success' || result === 'failed' ? result : '',
    category: sp.get('category') ?? '',
    caller: sp.get('caller') ?? '',
  };
};

const MonitoringAiUsage: React.FC = () => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const [sp, setSp] = useSearchParams();
  const requested = sp.get('tab');
  const tab: TabId = TABS.includes(requested as TabId) ? (requested as TabId) : 'overview';
  const query = useMemo(() => queryFrom(sp), [sp]);
  const requestedGroup = sp.get('group') as GroupBy | null;

  const [report, setReport] = useState<UsageReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [missing, setMissing] = useState(false);
  const run = useRef(0);

  const groupBy: GroupBy = requestedGroup && (query.hours > 168 ? ROLLUP_GROUPS.includes(requestedGroup) : true) ? requestedGroup : DEFAULT_GROUP;

  /** Change URL state; an empty value removes the parameter. */
  const patchUrl = useCallback((patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(sp);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setSp(next, { replace: true });
  }, [sp, setSp]);

  const changeQuery = useCallback((patch: Partial<UsageQuery>) => {
    const urlPatch: Record<string, string | undefined> = {};
    Object.entries(patch).forEach(([k, v]) => { urlPatch[k === 'hours' ? 'period' : k] = v === EMPTY_QUERY.hours ? undefined : String(v || ''); });
    // The 30-day rollup cannot answer these: drop them when the period grows.
    if (patch.hours && patch.hours > 168) Object.assign(urlPatch, { user: undefined, project: undefined, result: undefined });
    patchUrl(urlPatch);
  }, [patchUrl]);

  const load = useCallback(async () => {
    const id = ++run.current;
    setLoading(true);
    try {
      const next = await fetchAiUsage(query, groupBy);
      if (id !== run.current) return;
      setReport(next);
      setFailed(false);
      setMissing(false);
    } catch (e) {
      if (id !== run.current) return;
      if (e instanceof AiUsageMissingError) setMissing(true);
      else {
        console.error('[@page:MonitoringAiUsage] usage failed', e);
        setFailed(true);
      }
    } finally {
      if (id === run.current) setLoading(false);
    }
  }, [query, groupBy]);

  useEffect(() => { void load(); }, [load]);

  const exportCsv = async () => {
    const response = await apiClient(usageExportUrl(query, groupBy));
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `ai-usage-${groupBy}-${query.hours}h.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const restricted = report?.restricted_to_self ?? false;
  const errorCount = report?.errors?.count ?? 0;
  const visibleTabs = TABS.filter((id) => id !== 'training' || !restricted);
  const tabLabel = (id: TabId): React.ReactNode => {
    switch (id) {
      case 'overview': return t('Overview');
      case 'usage': return t('Usage');
      case 'errors':
        return (
          <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
            {t('Errors')}
            {errorCount > 0 && <Box component="span" sx={{ px: 0.75, borderRadius: 1, bgcolor: `${P.error}1f`, color: P.error, fontSize: '0.72rem', fontWeight: 600 }}>{errorCount}</Box>}
          </Box>
        );
      case 'providers': return t('Providers');
      case 'calls': return t('Calls');
      default: return t('Training');
    }
  };

  const panel = (() => {
    if (!report) return null;
    switch (tab) {
      case 'overview':
        return (
          <OverviewTab
            report={report}
            query={query}
            restricted={restricted}
            onOpenUsage={(patch) => patchUrl({ tab: 'usage', category: patch.category, caller: patch.caller })}
          />
        );
      case 'usage':
        return <UsageTab report={report} groupBy={groupBy} onGroup={(g) => patchUrl({ group: g === DEFAULT_GROUP ? undefined : g })} onExport={exportCsv} />;
      case 'errors':
        return <ErrorsTab report={report} />;
      case 'providers':
        return restricted ? null : <ProvidersPanel report={report} />;
      case 'calls':
        return <CallsTab query={query} source={report.source} />;
      default:
        return <TrainingPanel query={query} />;
    }
  })();

  return (
    <Box sx={[{ p: { xs: 1.5, sm: 2.5 }, maxWidth: 1400, width: '100%', minWidth: 0, boxSizing: 'border-box', mx: 'auto' }, ...[pageSurfaceSx(P)].flat()]}>
      <PageTitle
        title={t('AI usage')}
        right={
          <>
            {errorCount > 0 && (
              <Box
                component="button"
                type="button"
                onClick={() => patchUrl({ tab: 'errors' })}
                sx={{ all: 'unset', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 0.5, px: 1, py: 0.25, borderRadius: 4, bgcolor: `${P.error}1f`, border: `1px solid ${P.error}66`, color: P.error, fontSize: '0.8rem', fontWeight: 600, whiteSpace: 'nowrap', '&:hover': { bgcolor: `${P.error}33` } }}
              >
                <ErrorIcon sx={{ fontSize: 16 }} />
                {tn(errorCount, '{count} error', '{count} errors', { count: errorCount })}
              </Box>
            )}
            <Link component={RouterLink} to={SETTINGS_AI_HREF} sx={{ fontSize: '0.85rem', whiteSpace: 'nowrap' }}>{t('AI settings')} →</Link>
          </>
        }
      />

      {missing ? (
        <Alert severity="info">{t('This server does not have AI usage yet.')}</Alert>
      ) : (
        <>
          <FilterBar query={query} report={report} onChange={changeQuery} />
          {restricted && <Alert severity="info" sx={{ mb: 1.5 }}>{t('You see your own requests only.')}</Alert>}
          {failed && <PanelError what={t('AI usage')} onRetry={load} />}
          {loading && !report && !failed && <Box sx={{ display: 'flex', justifyContent: 'center', py: 4, minHeight: 120 }}><CircularProgress /></Box>}
          {report && (
            <>
              <Tabs
                value={tab}
                onChange={(_, v: TabId) => patchUrl({ tab: v === 'overview' ? undefined : v })}
                variant="scrollable"
                scrollButtons="auto"
                sx={{ borderBottom: 1, borderColor: 'divider', minHeight: 40, mb: 2, '& .MuiTabs-indicator': { bgcolor: P.accent, transition: 'none' }, '& .MuiTab-root.Mui-selected': { color: P.accentText } }}
              >
                {visibleTabs.map((id) => (
                  <Tab key={id} value={id} label={tabLabel(id)} disableRipple sx={{ minHeight: 40, textTransform: 'none', fontSize: '0.8125rem', transition: 'none' }} />
                ))}
              </Tabs>
              <Box sx={{ opacity: loading ? 0.6 : 1 }}>{panel}</Box>
            </>
          )}
        </>
      )}
    </Box>
  );
};

/** The Calls tab: every request of the period (newest first), loaded when the tab opens. */
const CallsTab: React.FC<{ query: UsageQuery; source: 'calls' | 'rollup' }> = ({ query, source }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const calls = useAiLoad('request list', () => fetchAiCalls(query, 200), [query], source === 'calls');
  if (source !== 'calls') return <Typography sx={{ color: P.textMuted, py: 2 }}>{t('Single requests are listed for up to 7 days.')}</Typography>;
  if (calls.failed) return <PanelError what={t('the request list')} onRetry={calls.reload} />;
  if (!calls.data) return <Box sx={{ minHeight: 120 }} />;
  if ((calls.data.calls ?? []).length === 0) return <Typography sx={{ color: P.textMuted, py: 2 }}>{t('No requests in this period.')}</Typography>;
  return <CallsTable calls={calls.data.calls} showFeature />;
};

export default MonitoringAiUsage;
