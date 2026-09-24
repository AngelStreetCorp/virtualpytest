import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Box, Button, CircularProgress, IconButton, MenuItem, Paper,
  Tab, Tabs, Table, TableBody, TableCell, TableHead, TableRow, TextField,
  Tooltip, Typography,
} from '@mui/material';
import { Refresh } from '@mui/icons-material';
import { apiClient } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { useServerManager } from '../hooks/useServerManager';

type Question = {
  question: string;
  count: number;
  first: string;
  last: string;
  cached: number;
  off_topic: number;
  errors: number;
  llm_calls: number;
  avg_llm_seconds: number | null;
  sources: string[];
};
type Stats = {
  totals: { questions: number; answered: number; cached: number; off_topic: number; error: number; llm_seconds: number };
  top_questions: Question[];
};
type AgentEvent = {
  id: string;
  session_id: string;
  agent_id: string;
  event_type: string;
  timestamp: string;
  status: string;
  duration_seconds: number | null;
  tool_calls: number;
  error_summary: string | null;
};
type OutcomeFilter = 'all' | 'answered' | 'cached' | 'off_topic' | 'error';
const SERVER_LOG_SERVICES = [
  { name: 'vpt-server', label: 'vpt-server' },
  { name: 'vpt-heatmap', label: 'vpt-heatmap' },
  { name: 'vpt-discard-scripts', label: 'vpt-discard-scripts' },
  { name: 'vpt-discard-incidents', label: 'vpt-discard-incidents' },
];

const formatTimestamp = (value?: string | null) => {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('en-GB');
};
const formatDate = (value?: string | null) => {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('en-GB');
};
const HOST_LOG_SERVICES = [
  'vpt-host', 'vpt-server-host', 'vpt-stream', 'vpt-vnc',
  'vpt-websockify', 'vpt-emulator', 'vpt-emulator-fifo', 'deployments',
];

const Logs: React.FC = () => {
  // Tab order: MCP, API, ASK AI, Server, Host.
  const [tab, setTab] = useState(0);
  const [days, setDays] = useState(30);
  const [limit, setLimit] = useState(50);
  const [query, setQuery] = useState('');
  const [outcome, setOutcome] = useState<OutcomeFilter>('all');
  const [stats, setStats] = useState<Stats | null>(null);
  const [apiLogs, setApiLogs] = useState('');
  const [serverLogs, setServerLogs] = useState('');
  const [hostLogs, setHostLogs] = useState('');
  const [serverService, setServerService] = useState('vpt-server');
  const [hostService, setHostService] = useState('vpt-host');
  const [apiSearch, setApiSearch] = useState('');
  const [apiLines, setApiLines] = useState(100);
  const [apiSince, setApiSince] = useState('1h');
  const [apiLevel, setApiLevel] = useState('');
  const [hostSearch, setHostSearch] = useState('');
  const [expandedQuestions, setExpandedQuestions] = useState<Set<string>>(() => new Set());
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([]);
  const [selectedHost, setSelectedHost] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [refreshed, setRefreshed] = useState<Date | null>(null);
  const { serverHostsData } = useServerManager();
  const hosts = useMemo(() => serverHostsData.flatMap((server) => server.hosts), [serverHostsData]);
  const requestController = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    setLoading(true);
    setError('');
    try {
      if (tab === 0) {
        const response = await apiClient(buildServerUrl('/server/logs/agent?days=30&limit=100&offset=0'), { signal: controller.signal });
        if (response.status === 401) throw new Error('Your session is not available for this server. Sign in again or select an authenticated server.');
        if (response.status === 403) throw new Error('Logs are available to administrators only.');
        if (!response.ok) throw new Error(`Unable to load MCP activity (HTTP ${response.status}).`);
        setAgentEvents((await response.json()).events || []);
      } else if (tab === 2) {
        const response = await apiClient(buildServerUrl(`/server/public/stats?days=${days}&limit=${limit}`), { signal: controller.signal });
        if (response.status === 401) throw new Error('Your session is not available for this server. Sign in again or select an authenticated server.');
        if (response.status === 403) throw new Error('Logs are available to administrators only.');
        if (!response.ok) throw new Error(`Unable to load public question statistics (HTTP ${response.status}).`);
        setStats(await response.json());
      } else if (tab === 1 || tab === 3) {
        const service = tab === 1 ? 'vpt-server' : serverService;
        const response = await apiClient(buildServerUrl('/server/logs/view'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ service, lines: apiLines, since: apiSince, level: apiLevel || undefined }),
          signal: controller.signal,
        });
        if (response.status === 401) throw new Error('Your session is not available for this server. Sign in again or select an authenticated server.');
        if (response.status === 403) throw new Error('Logs are available to administrators only.');
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || `Unable to load ${tab === 1 ? 'API' : 'server'} logs (HTTP ${response.status}).`);
        if (tab === 1) setApiLogs(data.logs || '');
        else setServerLogs(data.logs || '');
      } else if (tab === 4) {
        if (selectedHost && hostService) {
          const logResponse = await apiClient(buildServerUrl('/server/logs/view'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ service: hostService, host_name: selectedHost, lines: apiLines, since: apiSince, level: apiLevel || undefined }),
            signal: controller.signal,
          });
          if (logResponse.status === 401) throw new Error('Your session is not available for this server. Sign in again or select an authenticated server.');
          if (logResponse.status === 403) throw new Error('Logs are available to administrators only.');
          const data = await logResponse.json();
          if (!logResponse.ok || !data.success) throw new Error(data.error || `Unable to load host logs (HTTP ${logResponse.status}).`);
          setHostLogs(data.logs || '');
        }
      }
      setRefreshed(new Date());
    } catch (e) {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Unable to load logs.');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [tab, days, limit, apiLines, apiSince, apiLevel, serverService, selectedHost, hostService]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => () => { requestController.current?.abort(); }, []);

  const questions = useMemo(() => (stats?.top_questions || []).filter((item) => {
    const matchesText = item.question.toLowerCase().includes(query.toLowerCase());
    const matchesOutcome = outcome === 'all'
      || (outcome === 'answered' && item.llm_calls > 0)
      || (outcome === 'cached' && item.cached > 0)
      || (outcome === 'off_topic' && item.off_topic > 0)
      || (outcome === 'error' && item.errors > 0);
    return matchesText && matchesOutcome;
  }), [stats, query, outcome]);

  const metrics: [string, string | number][] = stats ? [
    ['Total questions', stats.totals.questions],
    ['Answered', stats.totals.answered],
    ['Cached', stats.totals.cached],
    ['Off-topic', stats.totals.off_topic],
    ['Errors', stats.totals.error],
    ['Model time · total', `${stats.totals.llm_seconds}s`],
    ['Model time · average', `${(stats.totals.answered + stats.totals.off_topic) ? (stats.totals.llm_seconds / (stats.totals.answered + stats.totals.off_topic)).toFixed(1) : '0'}s`],
  ] : [];

  const commonTableSx = {
    '& .MuiTableCell-root': { whiteSpace: 'nowrap' as const },
    '& .MuiTableRow-hover:hover, & .MuiTableBody-root .MuiTableRow-root:hover': { backgroundColor: 'transparent !important' },
    '& .MuiTableCell-root:hover': { backgroundColor: 'transparent !important' },
    '& .MuiTableHead-root, & .MuiTableCell-head': { backgroundColor: 'rgba(255,255,255,0.06) !important' },
  };
  useEffect(() => {
    if (!selectedHost && hosts.length > 0) setSelectedHost(hosts[0].host_name);
  }, [hosts, selectedHost]);

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
        <Typography variant="h4" sx={{ flex: 1 }}>Logs</Typography>
        {refreshed && <Typography variant="caption" color="text.secondary">Last refreshed: {refreshed.toLocaleString('en-GB')}</Typography>}
        <Tooltip title="Refresh">
          <span><IconButton aria-label="Refresh logs" onClick={() => void load()} disabled={loading}><Refresh /></IconButton></span>
        </Tooltip>
      </Box>

      <Tabs value={tab} onChange={(_, value) => { setTab(value); }} sx={{ mb: 2 }}>
        <Tab label="MCP" />
        <Tab label="API" />
        <Tab label="ASK AI" />
        <Tab label="Server" />
        <Tab label="Host" />
      </Tabs>

      {error && <Alert severity="error" action={<Button color="inherit" onClick={() => void load()}>Retry</Button>} sx={{ mb: 2 }}>{error}</Alert>}
      {loading && <Box sx={{ p: 4, textAlign: 'center' }}><CircularProgress /></Box>}

      {!loading && tab === 0 && (agentEvents.length === 0 ? <Typography color="text.secondary">No MCP activity found for the last 30 days.</Typography> : (
        <Paper sx={{ overflowX: 'auto' }}><Table size="small" sx={commonTableSx}>
          <TableHead><TableRow>{['Timestamp', 'Agent / session', 'Event', 'Tool calls', 'Status', 'Duration', 'Error summary'].map((title) => <TableCell key={title}>{title}</TableCell>)}</TableRow></TableHead>
          <TableBody>{agentEvents.map((event) => <TableRow hover key={event.id}>
            <TableCell>{formatTimestamp(event.timestamp)}</TableCell><TableCell>{event.agent_id || '—'} / {event.session_id || '—'}</TableCell>
            <TableCell>{event.event_type}</TableCell><TableCell>{event.tool_calls}</TableCell><TableCell>{event.status}</TableCell>
            <TableCell>{event.duration_seconds == null ? '—' : `${event.duration_seconds}s`}</TableCell><TableCell>{event.error_summary || '—'}</TableCell>
          </TableRow>)}</TableBody>
        </Table></Paper>
      ))}

      {!loading && tab === 1 && <>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1.5 }}>
          <TextField select label="Time range" size="small" value={apiSince} onChange={(event) => setApiSince(event.target.value)} sx={{ minWidth: 170 }}>
            {[['15m', '15 minutes'], ['1h', '1 hour'], ['6h', '6 hours'], ['24h', '24 hours'], ['7d', '7 days']].map(([value, label]) => <MenuItem key={value} value={value}>{label}</MenuItem>)}
          </TextField>
          <TextField select label="Severity" size="small" value={apiLevel} onChange={(event) => setApiLevel(event.target.value)} sx={{ minWidth: 150 }}>
            {[['', 'All levels'], ['emerg', 'Emergency'], ['alert', 'Alert'], ['crit', 'Critical'], ['err', 'Error'], ['warning', 'Warning'], ['notice', 'Notice'], ['info', 'Info'], ['debug', 'Debug']].map(([value, label]) => <MenuItem key={value || 'all'} value={value}>{label}</MenuItem>)}
          </TextField>
          <TextField select label="Lines" size="small" value={apiLines} onChange={(event) => setApiLines(Number(event.target.value))} sx={{ minWidth: 110 }}>
            {[50, 100, 200, 500].map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}
          </TextField>
          <TextField label="Search logs" size="small" value={apiSearch} onChange={(event) => setApiSearch(event.target.value)} sx={{ width: 240 }} />
        </Box>
        <Paper sx={{ p: 2, minHeight: 320, maxHeight: '65vh', overflow: 'auto', bgcolor: 'grey.900', color: 'grey.100', fontFamily: 'monospace', fontSize: '0.8rem', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
          {apiLogs.split('\n').filter((line) => line.toLowerCase().includes(apiSearch.toLowerCase())).join('\n') || <Typography color="grey.500">No API service logs found for this range.</Typography>}
        </Paper>
      </>}

      {!loading && tab === 2 && <>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(7, minmax(0, 1fr))' }, gap: 1, mb: 2 }}>
          {metrics.map(([label, value]) => <Paper key={label} sx={{ p: 1.25, minWidth: 0, textAlign: 'center' }}>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', whiteSpace: 'nowrap' }}>{label}</Typography>
            <Typography variant="h6" sx={{ textAlign: 'center' }}>{value}</Typography>
          </Paper>)}
        </Box>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', md: 'minmax(190px,1.5fr) minmax(160px,1.3fr) minmax(120px,.8fr) minmax(180px,1fr)' }, gap: 1, mb: 2 }}>
          <TextField select label="Time range" size="small" value={days} onChange={(event) => setDays(Number(event.target.value))}>
            {[1, 7, 30, 90].map((value) => <MenuItem key={value} value={value}>{value} days</MenuItem>)}
          </TextField>
          <TextField select label="Outcome" size="small" value={outcome} onChange={(event) => setOutcome(event.target.value as OutcomeFilter)}>
            {([['all', 'All outcomes'], ['answered', 'Answered'], ['cached', 'Cached'], ['off_topic', 'Off-topic'], ['error', 'Errors']] as [OutcomeFilter, string][]).map(([value, label]) => <MenuItem key={value} value={value}>{label}</MenuItem>)}
          </TextField>
          <TextField select label="Limit" size="small" value={limit} onChange={(event) => setLimit(Number(event.target.value))}>
            {[25, 50, 100, 250].map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}
          </TextField>
          <TextField label="Search questions" size="small" value={query} onChange={(event) => setQuery(event.target.value)} />
        </Box>
        {questions.length === 0 ? <Typography color="text.secondary">No public questions found for these filters.</Typography> : (
          <Paper sx={{ overflow: 'hidden' }}><Table size="small" sx={{ ...commonTableSx, width: '100%', tableLayout: 'fixed' }}>
            <TableHead><TableRow>
              <TableCell sx={{ width: '48%' }}>Question</TableCell>
              <TableCell sx={{ width: '9%' }}>Count</TableCell>
              <TableCell sx={{ width: '17%' }}>Last seen</TableCell>
              <TableCell sx={{ width: '13%' }}>Avg. time</TableCell>
              <TableCell sx={{ width: '13%', display: { xs: 'none', md: 'table-cell' } }}>Sources</TableCell>
            </TableRow></TableHead>
            <TableBody>{questions.map((question, index) => {
              const rowKey = `${question.question}-${index}`;
              const expanded = expandedQuestions.has(rowKey);
              const longQuestion = question.question.length > 160;
              const displayQuestion = longQuestion && !expanded ? `${question.question.slice(0, 160).trimEnd()}…` : question.question;
              return <TableRow hover key={rowKey}>
                <TableCell sx={{ whiteSpace: 'normal !important', overflowWrap: 'anywhere' }}>
                  {displayQuestion}{longQuestion && <Button size="small" onClick={() => setExpandedQuestions((current) => {
                    const next = new Set(current);
                    if (next.has(rowKey)) next.delete(rowKey); else next.add(rowKey);
                    return next;
                  })} sx={{ ml: 0.5, minWidth: 0, p: 0, verticalAlign: 'baseline' }}>{expanded ? 'Show less' : 'Show more'}</Button>}
                </TableCell>
                <TableCell>{question.count}</TableCell>
                <TableCell>{formatDate(question.last)}</TableCell>
                <TableCell>{question.avg_llm_seconds == null ? '—' : `${question.avg_llm_seconds}s`}</TableCell>
                <TableCell sx={{ display: { xs: 'none', md: 'table-cell' }, whiteSpace: 'normal !important', overflowWrap: 'anywhere' }}>{(question.sources || []).join(', ') || '—'}</TableCell>
              </TableRow>;
            })}</TableBody>
          </Table></Paper>
        )}
      </>}

      {!loading && tab === 3 && <>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1.5 }}>
          <TextField select label="Server service" size="small" value={serverService} onChange={(event) => setServerService(event.target.value)} sx={{ minWidth: 250 }}>
            {SERVER_LOG_SERVICES.map((service) => <MenuItem key={service.name} value={service.name}>{service.label}</MenuItem>)}
          </TextField>
          <TextField select label="Time range" size="small" value={apiSince} onChange={(event) => setApiSince(event.target.value)} sx={{ minWidth: 160 }}>
            {[['15m', '15 minutes'], ['1h', '1 hour'], ['6h', '6 hours'], ['24h', '24 hours'], ['7d', '7 days']].map(([value, label]) => <MenuItem key={value} value={value}>{label}</MenuItem>)}
          </TextField>
          <TextField select label="Severity" size="small" value={apiLevel} onChange={(event) => setApiLevel(event.target.value)} sx={{ minWidth: 140 }}>
            {[['', 'All levels'], ['emerg', 'Emergency'], ['alert', 'Alert'], ['crit', 'Critical'], ['err', 'Error'], ['warning', 'Warning'], ['notice', 'Notice'], ['info', 'Info'], ['debug', 'Debug']].map(([value, label]) => <MenuItem key={value || 'all'} value={value}>{label}</MenuItem>)}
          </TextField>
          <TextField select label="Lines" size="small" value={apiLines} onChange={(event) => setApiLines(Number(event.target.value))} sx={{ minWidth: 100 }}>
            {[50, 100, 200, 500].map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}
          </TextField>
          <TextField label="Search logs" size="small" value={apiSearch} onChange={(event) => setApiSearch(event.target.value)} sx={{ width: 220 }} />
        </Box>
        <Paper sx={{ p: 2, minHeight: 320, maxHeight: '65vh', overflow: 'auto', bgcolor: 'grey.900', color: 'grey.100', fontFamily: 'monospace', fontSize: '0.8rem', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
          {serverLogs.split('\n').filter((line) => line.toLowerCase().includes(apiSearch.toLowerCase())).join('\n') || <Typography color="grey.500">No server logs found for this range.</Typography>}
        </Paper>
      </>}

      {!loading && tab === 4 && <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
        <TextField select label="Host" size="small" value={selectedHost} onChange={(event) => setSelectedHost(event.target.value)} sx={{ minWidth: 220 }}>
          {hosts.map((host) => <MenuItem key={host.host_name} value={host.host_name}>{host.host_name}</MenuItem>)}
        </TextField>
        <TextField select label="Host service" size="small" value={hostService} onChange={(event) => setHostService(event.target.value)} sx={{ minWidth: 280 }}>
          {HOST_LOG_SERVICES.map((service) => <MenuItem key={service} value={service}>{service}{service === 'deployments' ? ' · deployment file' : ''}</MenuItem>)}
        </TextField>
        <TextField label="Search logs" size="small" value={hostSearch} onChange={(event) => setHostSearch(event.target.value)} sx={{ width: 220 }} />
      </Box>}

      {!loading && tab === 4 && <Paper sx={{ mt: 1.5, p: 2, minHeight: 320, maxHeight: '65vh', overflow: 'auto', bgcolor: 'grey.900', color: 'grey.100', fontFamily: 'monospace', fontSize: '0.8rem', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
        {hostLogs.split('\n').filter((line) => line.toLowerCase().includes(hostSearch.toLowerCase())).join('\n') || <Typography color="grey.500">No active host services or no host logs found for this range.</Typography>}
      </Paper>}

      {(tab === 1 || tab === 3 || tab === 4) && <Typography variant="body2" sx={{ mt: 2 }}>
        <a href="/docs/user-guide/troubleshooting">Troubleshooting and log review guide</a>
      </Typography>}
    </Box>
  );
};

export default Logs;
