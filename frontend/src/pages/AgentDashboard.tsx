import { Alert, Box, Card, CircularProgress, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { AgentCard } from '../components/agentDashboard/AgentCard';
import { AgentLogDrawer } from '../components/agentDashboard/AgentLogDrawer';
import { UsageTab } from '../components/agentDashboard/UsageTab';
import { Overview, fetchOverview, fmtAgo, fmtTokens } from '../components/agentDashboard/api';
import { PageTitle, StatTiles, pageSurfaceSx, segmentedSx } from '../components/common/PageChrome';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { useProfile } from '../hooks/auth/useProfile';

const WINDOWS = [{ h: 1, l: '1 h' }, { h: 24, l: '24 h' }, { h: 168, l: '7 d' }, { h: 720, l: '30 d' }];

const AgentDashboard: React.FC = () => {
  const P = useAgentChatPalette();
  const { isAdmin } = useProfile();
  const [view, setView] = useState<'overview' | 'usage'>('overview');
  const [hours, setHours] = useState(24);
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [logAgentId, setLogAgentId] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const o = await fetchOverview(hours, signal);
      if (signal?.aborted) return;
      setData(o); setError(null);
    } catch (e) {
      if (!signal?.aborted) setError(e instanceof Error ? e.message : 'Failed to load agents');
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [hours]);

  useEffect(() => {
    const ctl = new AbortController();
    void load(ctl.signal);
    return () => ctl.abort();
  }, [load]);

  useEffect(() => { if (!isAdmin && view === 'usage') setView('overview'); }, [isAdmin, view]);

  const agents = data?.agents ?? [];
  const totals = useMemo(() => agents.reduce((a, g) => ({
    calls: a.calls + g.stats.calls, errors: a.errors + g.stats.errors,
    tin: a.tin + g.stats.tokens_in, tout: a.tout + g.stats.tokens_out,
    active: a.active + (g.health !== 'idle' ? 1 : 0),
  }), { calls: 0, errors: 0, tin: 0, tout: 0, active: 0 }), [agents]);
  const recentErrors = useMemo(() => agents
    .flatMap((g) => g.recent_errors.map((e) => ({ ...e, agent: g.name })))
    .sort((a, b) => b.ts.localeCompare(a.ts)).slice(0, 15), [agents]);
  const logAgent = agents.find((g) => g.id === logAgentId) ?? null;
  const days = Math.max(1, Math.ceil(hours / 24));

  return (
    <Box sx={pageSurfaceSx(P)}>
      <PageTitle
        title="Agents"
        subtitle="What the AI agents did for your team: health, current work, errors and token use"
        right={
          <ToggleButtonGroup exclusive size="small" value={hours} onChange={(_, v) => v && setHours(v)} sx={segmentedSx(P, 'sm')}>
            {WINDOWS.map((w) => <ToggleButton key={w.h} value={w.h}>{w.l}</ToggleButton>)}
          </ToggleButtonGroup>
        }
      />
      <StatTiles tiles={[
        { label: 'Calls', value: data ? totals.calls.toLocaleString() : '-' },
        { label: 'Errors', value: data ? totals.errors.toLocaleString() : '-', color: totals.errors ? P.error : undefined },
        { label: 'Tokens in', value: data ? fmtTokens(totals.tin) : '-' },
        { label: 'Tokens out', value: data ? fmtTokens(totals.tout) : '-' },
        { label: 'Active agents', value: data ? totals.active : '-', extra: data ? `of ${agents.length}` : undefined },
      ]} />

      {isAdmin && (
        <ToggleButtonGroup exclusive size="small" value={view} onChange={(_, v) => v && setView(v)} sx={{ ...segmentedSx(P), mb: 1.5 }}>
          <ToggleButton value="overview">Overview</ToggleButton>
          <ToggleButton value="usage">Usage &amp; decisions</ToggleButton>
        </ToggleButtonGroup>
      )}

      {view === 'usage' && isAdmin ? (
        <UsageTab days={days} />
      ) : loading && !data ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}><CircularProgress /></Box>
      ) : (
        <>
          {error && <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert>}
          {!error && data && agents.length === 0 && (
            <Typography sx={{ color: P.textMuted, fontSize: '0.9rem' }}>
              No agents reported for this team. Nothing is recorded until an agent runs.
            </Typography>
          )}
          <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 300px), 1fr))', gap: 1.5, opacity: loading ? 0.6 : 1, transition: 'opacity 0.15s' }}>
            {agents.map((g) => <AgentCard key={g.id} agent={g} onLogs={() => setLogAgentId(g.id)} />)}
          </Box>

          {agents.length > 0 && (
            <Card sx={{ mt: 2, bgcolor: P.surface }}>
              <Typography sx={{ fontSize: '1rem', fontWeight: 600, px: 1.75, pt: 1.5, pb: 0.75 }}>Recent errors</Typography>
              {recentErrors.length === 0 ? (
                <Typography sx={{ fontSize: '0.85rem', color: P.textMuted, px: 1.75, pb: 1.5 }}>No errors in this window.</Typography>
              ) : recentErrors.map((e, i) => (
                <Box key={i} onClick={() => { const a = agents.find((g) => g.name === e.agent); if (a) setLogAgentId(a.id); }}
                  sx={{ display: 'flex', gap: 1.25, px: 1.75, py: 0.9, borderTop: `1px solid ${P.borderColor}`, cursor: 'pointer', '&:hover': { bgcolor: P.hoverBg }, alignItems: 'baseline', minWidth: 0 }}>
                  <Typography sx={{ fontSize: '0.75rem', color: P.textMuted, flexShrink: 0, width: 72 }}>{fmtAgo(e.ts)}</Typography>
                  <Typography sx={{ fontSize: '0.8rem', color: P.textSecondary, flexShrink: 0 }}>{e.agent} · {e.part}</Typography>
                  <Typography noWrap sx={{ fontSize: '0.8rem', color: P.error, flex: 1, minWidth: 0 }}>{e.summary}</Typography>
                  {e.count > 1 && <Typography sx={{ fontSize: '0.75rem', color: P.textMuted, flexShrink: 0 }}>x{e.count}</Typography>}
                </Box>
              ))}
            </Card>
          )}
        </>
      )}

      <AgentLogDrawer agent={logAgent} initialHours={hours} isAdmin={isAdmin} onClose={() => setLogAgentId(null)} />
    </Box>
  );
};

export default AgentDashboard;
