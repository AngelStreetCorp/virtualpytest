import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Box, Button, CircularProgress, MenuItem, Paper, Tab, Tabs, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from '@mui/material';
import { Refresh, Terminal } from '@mui/icons-material';
import { apiClient } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { ServiceLogsModal } from '../components/common/ServiceLogsModal';
import { useServerManager } from '../hooks/useServerManager';

type Question = { question: string; count: number; first: string; last: string; cached: number; off_topic: number; llm_calls: number; avg_llm_seconds: number | null; sources: string[] };
type Stats = { totals: { questions: number; answered: number; cached: number; off_topic: number; error: number; llm_seconds: number }; top_questions: Question[] };
type AgentEvent = { id: string; session_id: string; agent_id: string; event_type: string; timestamp: string; status: string; duration_seconds: number | null; tool_calls: number; error_summary: string | null };

const Logs: React.FC = () => {
  const [tab, setTab] = useState(0);
  const [days, setDays] = useState(30);
  const [limit, setLimit] = useState(50);
  const [query, setQuery] = useState('');
  const [stats, setStats] = useState<Stats | null>(null);
  const [services, setServices] = useState<{name: string; status: string}[]>([]);
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([]);
  const [selectedService, setSelectedService] = useState('');
  const [selectedHost, setSelectedHost] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [refreshed, setRefreshed] = useState<Date | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const { serverHostsData } = useServerManager();
  const hosts = useMemo(() => serverHostsData.flatMap((server) => server.hosts), [serverHostsData]);
  const activeHost = hosts.find((host) => host.host_name === selectedHost);
  const requestController = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    setLoading(true); setError('');
    try {
      if (tab === 0) {
        const response = await apiClient(buildServerUrl(`/server/public/stats?days=${days}&limit=${limit}`), { signal: controller.signal });
        if (response.status === 401) throw new Error('Your session is not available for this server. Sign in again or select an authenticated server.');
        if (response.status === 403) throw new Error('Logs are available to administrators only.');
        if (!response.ok) throw new Error(`Unable to load public question statistics (HTTP ${response.status}).`);
        setStats(await response.json());
      } else if (tab === 2) {
        const response = await apiClient(buildServerUrl('/server/logs/services'), { signal: controller.signal });
        if (response.status === 401) throw new Error('Your session is not available for this server. Sign in again or select an authenticated server.');
        if (response.status === 403) throw new Error('Logs are available to administrators only.');
        if (!response.ok) throw new Error(`Unable to load services (HTTP ${response.status}).`);
        const data = await response.json(); setServices(data.services || []);
      } else if (tab === 1) {
        const response = await apiClient(buildServerUrl('/server/logs/agent?days=30&limit=100&offset=0'), { signal: controller.signal });
        if (response.status === 401) throw new Error('Your session is not available for this server. Sign in again or select an authenticated server.');
        if (response.status === 403) throw new Error('Logs are available to administrators only.');
        if (!response.ok) throw new Error(`Unable to load agent activity (HTTP ${response.status}).`);
        const data = await response.json(); setAgentEvents(data.events || []);
      }
      setRefreshed(new Date());
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Unable to load logs.'); }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }, [tab, days, limit]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => () => { requestController.current?.abort(); }, []);
  const questions = useMemo(() => (stats?.top_questions || []).filter((q) => q.question.toLowerCase().includes(query.toLowerCase())), [stats, query]);
  return <Box sx={{ p: 3 }}>
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}><Terminal color="primary"/><Typography variant="h4" sx={{ flex: 1 }}>Logs</Typography><Button startIcon={<Refresh/>} onClick={() => void load()} disabled={loading}>Refresh</Button></Box>
    <Typography color="text.secondary" sx={{ mb: 2 }}>Review public assistant questions and operational service logs. Content may include screen, device, host, URL, or customer data.</Typography>
    {refreshed && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>Last refreshed: {refreshed.toLocaleString()}</Typography>}
    <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}><Tab label="Public AI Questions"/><Tab label="Agent / MCP Activity"/><Tab label="Services"/></Tabs>
    {error && <Alert severity="error" action={<Button color="inherit" onClick={() => void load()}>Retry</Button>} sx={{ mb: 2 }}>{error}</Alert>}
    {loading && <Box sx={{ p: 4, textAlign: 'center' }}><CircularProgress/></Box>}
    {!loading && tab === 0 && <>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}>{[["Total questions",stats?.totals.questions],["Answered",stats?.totals.answered],["Cached",stats?.totals.cached],["Off-topic",stats?.totals.off_topic],["Errors",stats?.totals.error],["Model time (total / avg)", stats ? `${stats.totals.llm_seconds}s / ${stats.totals.questions ? (stats.totals.llm_seconds / stats.totals.questions).toFixed(1) : '0'}s` : '—']].map(([label,value])=><Paper key={String(label)} sx={{ p: 1.5, minWidth: 130, flex: 1 }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h6">{value ?? '—'}</Typography></Paper>)}</Box>
      <Box sx={{ display: 'flex', gap: 1, mb: 2 }}><TextField select label="Time range" size="small" value={days} onChange={(e)=>setDays(Number(e.target.value))}>{[1,7,30,90].map(n=><MenuItem key={n} value={n}>{n} days</MenuItem>)}</TextField><TextField select label="Limit" size="small" value={limit} onChange={(e)=>setLimit(Number(e.target.value))}>{[25,50,100,250].map(n=><MenuItem key={n} value={n}>{n}</MenuItem>)}</TextField><TextField label="Search questions" size="small" value={query} onChange={(e)=>setQuery(e.target.value)} fullWidth/></Box>
      <Alert severity="info" sx={{ mb: 2 }}>Rows are aggregated top questions, not individual event records. IP hashes are not shown.</Alert>
      {questions.length === 0 ? <Typography color="text.secondary">No public questions found for this range.</Typography> : <Paper sx={{ overflowX: 'auto' }}><Table size="small"><TableHead><TableRow>{['Question','Count','First seen','Last seen','Outcomes (cached / off-topic / model)','Avg model time','Sources'].map(h=><TableCell key={h}>{h}</TableCell>)}</TableRow></TableHead><TableBody>{questions.map((q,i)=><TableRow key={`${q.question}-${i}`}><TableCell sx={{ minWidth: 280 }}>{q.question}</TableCell><TableCell>{q.count}</TableCell><TableCell>{q.first || '—'}</TableCell><TableCell>{q.last || '—'}</TableCell><TableCell>{q.cached} / {q.off_topic} / {q.llm_calls}</TableCell><TableCell>{q.avg_llm_seconds == null ? '—' : `${q.avg_llm_seconds}s`}</TableCell><TableCell>{(q.sources || []).join(', ') || '—'}</TableCell></TableRow>)}</TableBody></Table></Paper>}
    </>}
    {!loading && tab === 1 && (agentEvents.length === 0 ? <Typography color="text.secondary">No agent activity found for the last 30 days.</Typography> : <Paper sx={{ overflowX: 'auto' }}><Table size="small"><TableHead><TableRow>{['Timestamp','Agent / session','Event','Tool calls','Status','Duration','Error summary'].map(h=><TableCell key={h}>{h}</TableCell>)}</TableRow></TableHead><TableBody>{agentEvents.map((event)=><TableRow key={event.id}><TableCell>{event.timestamp || '—'}</TableCell><TableCell>{event.agent_id || '—'} / {event.session_id || '—'}</TableCell><TableCell>{event.event_type}</TableCell><TableCell>{event.tool_calls}</TableCell><TableCell>{event.status}</TableCell><TableCell>{event.duration_seconds == null ? '—' : `${event.duration_seconds}s`}</TableCell><TableCell>{event.error_summary || '—'}</TableCell></TableRow>)}</TableBody></Table></Paper>)}
    {!loading && tab === 2 && <><Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap', mb: 2 }}><TextField select label="Service" size="small" value={selectedService} onChange={(e)=>setSelectedService(e.target.value)} sx={{ minWidth: 270 }}><MenuItem value="">Select a service</MenuItem>{services.map(s=><MenuItem key={s.name} value={s.name}>{s.name} — {s.status}</MenuItem>)}{selectedHost && <MenuItem value="deployments">deployments — deployment file log</MenuItem>}</TextField><TextField select label="Host (optional)" size="small" value={selectedHost} onChange={(e)=>setSelectedHost(e.target.value)} sx={{ minWidth: 230 }}><MenuItem value="">Backend server</MenuItem>{hosts.map((host)=><MenuItem key={host.host_name} value={host.host_name}>{host.host_name}</MenuItem>)}</TextField><Button variant="contained" disabled={!selectedService} onClick={()=>setModalOpen(true)}>View logs</Button></Box><Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Backend service logs use the server journal. Selecting a host proxies the whitelisted service to that host. Deployment file logs and per-device stream logs are identified separately.</Typography><Typography variant="body2"><a href="/docs/user-guide/troubleshooting">Troubleshooting and log review guide</a></Typography>{selectedService && <ServiceLogsModal open={modalOpen} serviceLabel={selectedService} logService={selectedService} logHostName={selectedHost || undefined} streamDevices={selectedHost && selectedService === 'vpt-stream' ? activeHost?.devices.map((device) => ({ device_id: device.device_id, device_name: device.device_name })) : undefined} onClose={()=>setModalOpen(false)}/>}</>}
  </Box>;
};
export default Logs;
