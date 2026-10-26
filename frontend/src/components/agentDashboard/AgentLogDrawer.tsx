import { APP_CONFIG } from '../../config/constants';
import {
  CheckCircleOutline, Close, DescriptionOutlined, ErrorOutline, NotificationsNoneOutlined, OpenInNew,
  ChatBubbleOutline, SyncOutlined, WarningAmberOutlined,
} from '@mui/icons-material';

import { AIIcon as SmartToyOutlined } from '../../components/common/icons/CustomIcons';
import {
  Alert, Box, Button, CircularProgress, Drawer, IconButton, MenuItem, TextField, ToggleButton,
  ToggleButtonGroup, Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Socket } from 'socket.io-client';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { getServerBaseUrl } from '../../utils/buildUrlUtils';
import { openR2Url } from '../../utils/infrastructure/cloudflareUtils';
import { createServerSocket } from '../../utils/serverSocket';
import { segmentedSx } from '../common/PageChrome';
import { AgentOverview, Level, LogRow, Turn, fetchLogs, fetchTurns, fmtDuration, fmtTokens } from './api';
import { TYPOGRAPHY } from '../../constants/typography';

const LIVE_POLL_MS = 15000;
const WINDOWS = [{ h: 1, l: '1 h' }, { h: 24, l: '24 h' }, { h: 168, l: '7 d' }, { h: 720, l: '30 d' }];

const useLevelStyle = () => {
  const P = useAgentChatPalette();
  return (l: Level) => {
    switch (l) {
      case 'error': return { icon: <ErrorOutline sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} />, color: P.error };
      case 'fallback': return { icon: <WarningAmberOutlined sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} />, color: P.warning };
      case 'running': return { icon: <SyncOutlined sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} />, color: P.accentText };
      default: return { icon: <CheckCircleOutline sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} />, color: P.success };
    }
  };
};

const TurnsView: React.FC<{ agentId: string; sessionId: string }> = ({ agentId, sessionId }) => {
  const P = useAgentChatPalette();
  const [turns, setTurns] = useState<Turn[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    setTurns(null); setErr(null);
    fetchTurns(agentId, sessionId, ctl.signal).then((r) => setTurns(r.turns)).catch((e) => { if (!ctl.signal.aborted) setErr(e.message); });
    return () => ctl.abort();
  }, [agentId, sessionId]);
  if (err) return <Alert severity="error" sx={{ my: 1 }}>{err}</Alert>;
  if (!turns) return <Box sx={{ py: 1 }}><CircularProgress size={18} /></Box>;
  if (!turns.length) return <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, py: 1 }}>No stored turns for this session (kept 30 days).</Typography>;
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75, py: 1 }}>
      {turns.map((t, i) => {
        const mine = t.role === 'user';
        return (
          <Box key={i} sx={{ alignSelf: mine ? 'flex-end' : 'flex-start', maxWidth: '92%' }}>
            <Box sx={{
              px: 1.25, py: 0.75, borderRadius: 2, fontSize: TYPOGRAPHY.body.size, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              bgcolor: mine ? `${P.accent}26` : P.hoverBg, border: `1px solid ${t.role === 'tool' ? P.borderColor : 'transparent'}`,
              fontFamily: t.role === 'tool' ? 'monospace' : undefined, color: t.role === 'tool' ? P.textSecondary : P.textPrimary,
            }}>{t.content}</Box>
            <Typography sx={{ fontSize: TYPOGRAPHY.microMeta.size, color: P.textMuted, mt: 0.25, textAlign: mine ? 'right' : 'left' }}>
              {t.role} · {new Date(t.ts).toLocaleTimeString()}
              {(t.tokens_in || t.tokens_out) ? ` · ${fmtTokens(t.tokens_in || 0)}/${fmtTokens(t.tokens_out || 0)} tok` : ''}
              {t.trace_url && (<> · <Box component="a" href={t.trace_url} target="_blank" rel="noopener noreferrer" sx={{ color: P.accentText, textDecoration: "none" }}>trace</Box></>)}
            </Typography>
          </Box>
        );
      })}
    </Box>
  );
};

const Row: React.FC<{ agentId: string; row: LogRow }> = ({ agentId, row }) => {
  const P = useAgentChatPalette();
  const navigate = useNavigate();
  const levelStyle = useLevelStyle();
  const [open, setOpen] = useState(false);
  const st = levelStyle(row.level);
  const ln = row.links || {};
  const iconBtn = { color: P.textSecondary, '&:hover': { color: P.accentText } } as const;
  const hasDetail = !!(row.detail && (row.detail.question || row.detail.answer));
  return (
    <Box sx={{ px: 1.5, py: 1, borderBottom: `1px solid ${P.borderColor}`, '&:hover': { bgcolor: P.hoverBg } }}>
      <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-start' }}>
        <Box sx={{ color: st.color, display: 'flex', pt: 0.1 }} title={row.level}>{st.icon}</Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Box sx={{ display: 'flex', gap: 0.75, alignItems: 'center', flexWrap: 'wrap' }}>
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, fontFamily: 'monospace' }}>
              {new Date(row.ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </Typography>
            <Box component="span" sx={{ fontSize: TYPOGRAPHY.caption.size, px: 0.75, borderRadius: 1, color: P.accentText, bgcolor: `${P.accent}1f`, border: `1px solid ${P.accent}66` }}>{row.part}</Box>
            {(row.tokens_in > 0 || row.tokens_out > 0) && (
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{fmtTokens(row.tokens_in)} / {fmtTokens(row.tokens_out)} tok</Typography>
            )}
            {row.duration_ms > 0 && <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{fmtDuration(row.duration_ms)}</Typography>}
          </Box>
          <Typography
            onClick={hasDetail ? () => setOpen((o) => !o) : undefined}
            sx={{ fontSize: TYPOGRAPHY.body.size, wordBreak: 'break-word', cursor: hasDetail ? 'pointer' : 'default', color: row.level === 'error' ? P.error : P.textPrimary }}
          >{row.summary}</Typography>
          {open && row.detail && (
            <Box sx={{ mt: 0.5, p: 1, borderRadius: 1.5, bgcolor: P.hoverBg, fontSize: TYPOGRAPHY.caption.size, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: P.textSecondary }}>
              {row.detail.question && (<><b>Q</b> {row.detail.question}{'\n'}</>)}
              {row.detail.answer && (<><b>A</b> {row.detail.answer}</>)}
            </Box>
          )}
        </Box>
        <Box sx={{ display: 'flex', flexShrink: 0 }}>
          {ln.report && (
            <Tooltip title="Report"><IconButton size="small" sx={iconBtn} onClick={() => { void openR2Url(ln.report!); }}><DescriptionOutlined sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} /></IconButton></Tooltip>
          )}
          {ln.alert && (
            <Tooltip title="Incidents"><IconButton size="small" sx={iconBtn} onClick={() => navigate('/monitoring/incidents')}><NotificationsNoneOutlined sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} /></IconButton></Tooltip>
          )}
          {ln.testprompt && (
            <Tooltip title="Test Prompt (Atlas chat)"><IconButton size="small" sx={iconBtn} onClick={() => navigate('/ai-agent')}><SmartToyOutlined sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} /></IconButton></Tooltip>
          )}
          {ln.chat_session && (
            <Tooltip title="Transcript"><IconButton size="small" sx={iconBtn} onClick={() => setOpen((o) => !o)}><ChatBubbleOutline sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} /></IconButton></Tooltip>
          )}
          {ln.trace && (
            <Tooltip title="Trace"><IconButton size="small" sx={iconBtn} component="a" href={ln.trace} target="_blank" rel="noopener noreferrer"><OpenInNew sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} /></IconButton></Tooltip>
          )}
        </Box>
      </Box>
      {open && ln.chat_session && <TurnsView agentId={agentId} sessionId={ln.chat_session} />}
    </Box>
  );
};

export const AgentLogDrawer: React.FC<{ agent: AgentOverview | null; initialHours: number; isAdmin: boolean; onClose: () => void }> = ({ agent, initialHours, isAdmin, onClose }) => {
  const P = useAgentChatPalette();
  const theme = useTheme();
  const phone = useMediaQuery(theme.breakpoints.down('sm'));
  const agentId = agent?.id ?? null;

  const [mode, setMode] = useState<'history' | 'live'>('history');
  const [part, setPart] = useState('');
  const [level, setLevel] = useState('');
  const [hours, setHours] = useState(initialHours);
  const [q, setQ] = useState('');
  const [qApplied, setQApplied] = useState('');
  const [rows, setRows] = useState<LogRow[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ctlRef = useRef<AbortController | null>(null);
  const filtersRef = useRef({ part, level, hours, qApplied });
  filtersRef.current = { part, level, hours, qApplied };

  // Reset when another agent opens.
  useEffect(() => {
    if (!agentId) return;
    setMode('history'); setPart(''); setLevel(''); setHours(initialHours); setQ(''); setQApplied(''); setRows([]); setNext(null);
  }, [agentId, initialHours]);

  const load = useCallback(async (silent = false) => {
    if (!agentId) return;
    ctlRef.current?.abort();
    const ctl = new AbortController();
    ctlRef.current = ctl;
    if (!silent) setLoading(true);
    try {
      const f = filtersRef.current;
      const r = await fetchLogs(agentId, { part: f.part, level: f.level, hours: f.hours, q: f.qApplied }, ctl.signal);
      if (ctl.signal.aborted) return;
      setRows(r.rows); setNext(r.next_before); setError(null);
    } catch (e) {
      if (!ctl.signal.aborted) setError(e instanceof Error ? e.message : 'Failed to load logs');
    } finally {
      if (!ctl.signal.aborted && !silent) setLoading(false);
    }
  }, [agentId]);

  useEffect(() => { if (agentId) void load(); return () => ctlRef.current?.abort(); }, [agentId, part, level, hours, qApplied, load]);

  const loadOlder = async () => {
    if (!agentId || !next) return;
    setLoadingMore(true);
    try {
      const r = await fetchLogs(agentId, { part, level, hours, q: qApplied, before: next });
      setRows((prev) => [...prev, ...r.rows.filter((x) => !prev.some((p) => p.id === x.id))]);
      setNext(r.next_before);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load older rows');
    } finally { setLoadingMore(false); }
  };

  // Live: socket push + 15 s poll, both cleaned up on close, agent change or mode change.
  useEffect(() => {
    if (!agentId || mode !== 'live') return;
    let socket: Socket | null = null;
    try {
      socket = createServerSocket(getServerBaseUrl(), '/system', { transports: ['websocket'], reconnection: true });
      // /system is shared by every team and the pushed row is stripped of its text: only react to this
      // team's events, and refetch so the drawer shows the full row.
      socket.on('system_update', (ev: any) => {
        if (ev?.domain !== 'agent_activity' || ev?.agent_id !== agentId) return;
        if (ev?.team_id && ev.team_id !== APP_CONFIG.DEFAULT_TEAM_ID) return;
        void load(true);
      });
    } catch { /* poll still runs */ }
    const id = window.setInterval(() => { void load(true); }, LIVE_POLL_MS);
    return () => { window.clearInterval(id); socket?.removeAllListeners(); socket?.disconnect(); };
  }, [agentId, mode, load]);

  const fieldSx = { '& .MuiInputBase-root': { fontSize: TYPOGRAPHY.body.size }, minWidth: 100 };

  return (
    <Drawer anchor="right" open={!!agent} onClose={onClose}
      PaperProps={{ sx: { width: phone ? '100%' : 640, maxWidth: '100%', bgcolor: P.background, backgroundImage: 'none', borderLeft: `1px solid ${P.borderColor}` } }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.5, py: 1, borderBottom: `1px solid ${P.borderColor}`, flexWrap: 'wrap' }}>
        <Typography sx={{ fontSize: TYPOGRAPHY.navbarItem.size, fontWeight: 600, flex: 1, minWidth: 0 }} noWrap>{agent?.name} logs</Typography>
        <ToggleButtonGroup exclusive size="small" value={mode} onChange={(_, v) => v && setMode(v)} sx={segmentedSx(P, 'sm')}>
          <ToggleButton value="history">History</ToggleButton>
          <ToggleButton value="live">
            <Box component="span" sx={{ width: 7, height: 7, borderRadius: '50%', mr: 0.75, bgcolor: mode === 'live' ? P.success : P.textMuted }} />Live
          </ToggleButton>
        </ToggleButtonGroup>
        <IconButton size="small" onClick={onClose} aria-label="Close"><Close sx={{ fontSize: TYPOGRAPHY.pageSubtitle.size }} /></IconButton>
      </Box>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', px: 1.5, py: 1, borderBottom: `1px solid ${P.borderColor}` }}>
        <TextField select size="small" label="Part" value={part} onChange={(e) => setPart(e.target.value)} sx={fieldSx}>
          <MenuItem value="">All parts</MenuItem>
          {(agent?.parts || []).map((p) => <MenuItem key={p.key} value={p.key}>{p.label}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Level" value={level} onChange={(e) => setLevel(e.target.value)} sx={fieldSx}>
          <MenuItem value="">All</MenuItem>
          <MenuItem value="ok">ok</MenuItem><MenuItem value="error">error</MenuItem>
          <MenuItem value="fallback">fallback</MenuItem><MenuItem value="running">running</MenuItem>
        </TextField>
        <TextField select size="small" label="Window" value={hours} onChange={(e) => setHours(Number(e.target.value))} sx={fieldSx}>
          {WINDOWS.map((w) => <MenuItem key={w.h} value={w.h}>{w.l}</MenuItem>)}
        </TextField>
        <TextField size="small" label="Search" value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') setQApplied(q.trim()); }} onBlur={() => setQApplied(q.trim())}
          sx={{ ...fieldSx, flex: 1, minWidth: 140 }} />
      </Box>
      <Box sx={{ flex: 1, overflowY: 'auto' }}>
        {error && <Alert severity="error" sx={{ m: 1.5 }}>{error}</Alert>}
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={24} /></Box>
        ) : rows.length === 0 && !error ? (
          <Typography sx={{ p: 2, fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}>
            No rows for these filters in the window. Widen the window or clear the filters.
            {!isAdmin && ' Error details are visible to admins only.'}
          </Typography>
        ) : (
          rows.map((r) => <Row key={r.id} agentId={agent?.id ?? ""} row={r} />)
        )}
        {next && !loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 1.5 }}>
            <Button size="small" variant="outlined" onClick={loadOlder} disabled={loadingMore}>{loadingMore ? 'Loading…' : 'Load older'}</Button>
          </Box>
        )}
      </Box>
    </Drawer>
  );
};
