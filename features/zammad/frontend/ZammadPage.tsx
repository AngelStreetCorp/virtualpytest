/**
 * Zammad feature - the plugin page (Plugins > Zammad).
 *
 * Mirrors the GitLab page's contract: the instance is configured either by env (ZAMMAD_URL +
 * ZAMMAD_API_TOKEN, no UI needed) or by the Settings (gear) dialog here, which tests the connection before
 * it saves. The page shows a status dot next to the title (connection + where the config comes from, in the
 * tooltip), ticket counts (Opened / Closed / Total) over a Today / 7d / 30d / All period with Team / User /
 * Project filters, and the recent tickets under the same filters. The on/off switch is NOT here: it lives in
 * Settings -> Features -> Feature Toggles (SupportTicketsToggle.tsx).
 *
 * Styling follows docs/agent/platform/UI_STYLE.md: palette tokens via useAgentChatPalette, PageChrome
 * building blocks, no literal colours. Reads are open to every signed-in user; changing the config is
 * admin-only (the route enforces it, the control is hidden for everyone else).
 */
import {
  Alert,
  Box,
  Button,
  Card,
  Chip,
  CardContent,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Link,
  MenuItem,
  ToggleButton,
  ToggleButtonGroup,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import {
  OpenInNew as ExternalIcon,
  Settings as SettingsIcon,
} from '@mui/icons-material';
import { useCallback, useEffect, useState } from 'react';

import {
  PageTitle,
  StatTiles,
  goldButtonSx,
  pageSurfaceSx,
  segmentedSx,
} from '../../../frontend/src/components/common/PageChrome';
import { useAgentChatPalette } from '../../../frontend/src/constants/agentChatTheme';
import { usePermissions } from '../../../frontend/src/hooks/auth/usePermissions';
import { useI18n } from '../../../frontend/src/i18n/useI18n';
import { ZammadMark } from './ZammadMark';
import { openReportIncident, refreshReportEnabled } from './reportIncident';
import type { Priority, ReporterStatus, Severity } from './ticketModel';
import type { SupportTicket } from './useSupportTickets';
import { useTicketLabels } from './useTicketLabels';
import { FilterOption, TicketPeriod, TicketStats, ZammadHealth, zammadApi } from './zammadApi';

const CONTENT_MAX = 1280;
const EXAMPLE_URL = 'https://support.example.com';

type Tone = 'success' | 'error' | 'warning' | 'textMuted' | 'accentText';

/** The reporter's simplified status as a coloured dot + word. */
const STATUS_TONE: Record<ReporterStatus, Tone> = {
  open: 'warning',
  in_progress: 'accentText',
  waiting: 'error',
  delivered: 'success',
  closed: 'textMuted',
};

const SEVERITY_TONE: Record<Severity, Tone> = {
  blocker: 'error',
  major: 'warning',
  minor: 'accentText',
};

const PRIORITY_TONE: Record<Priority, Tone> = {
  P0: 'error',
  P1: 'warning',
  P2: 'textMuted',
};

export default function ZammadPage() {
  const { t, formatDate } = useI18n();
  const P = useAgentChatPalette();
  const { hasRole } = usePermissions();
  const isAdmin = hasRole('admin');
  const { label, status: statusLabel } = useTicketLabels();

  const [health, setHealth] = useState<ZammadHealth | null>(null);
  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [stats, setStats] = useState<TicketStats | null>(null);
  const [period, setPeriod] = useState<TicketPeriod>('7d');
  const [teamId, setTeamId] = useState('');
  const [user, setUser] = useState('');
  const [project, setProject] = useState('');
  const [listError, setListError] = useState<string | null>(null);
  const [teamOptions, setTeamOptions] = useState<FilterOption[]>([]);
  const [projectOptions, setProjectOptions] = useState<FilterOption[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showSetup, setShowSetup] = useState(false);
  const [formUrl, setFormUrl] = useState('');
  const [formToken, setFormToken] = useState('');
  const [formPublicUrl, setFormPublicUrl] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  // Re-reads the connection for the CURRENT server (the config is per server).
  const boot = useCallback(async () => {
    setHealth(null);
    setError(null);
    try {
      const h = await zammadApi.health();
      setHealth(h);
      setFormUrl(h.config.base_url);
      setFormPublicUrl(h.config.public_url);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  // Counts and the recent list follow the same filters. A different team has different people, so the
  // User filter is dropped whenever the team changes.
  const loadTickets = useCallback(async () => {
    const f = {
      period, teamId: teamId || undefined, user: user || undefined, project: project || undefined,
    };
    setListError(null);
    try {
      const [s, list] = await Promise.all([zammadApi.stats(f), zammadApi.tickets(f)]);
      setStats(s);
      setTickets(list.tickets);
    } catch (e) {
      // Say why the counts are missing instead of leaving them on "…".
      setStats(null);
      setTickets([]);
      setListError((e as Error).message);
    }
  }, [period, teamId, user, project]);

  useEffect(() => {
    boot();
  }, [boot]);

  useEffect(() => {
    zammadApi.filters()
      .then((o) => { setTeamOptions(o.team); setProjectOptions(o.project); })
      .catch(() => { setTeamOptions([]); setProjectOptions([]); });
  }, []);

  useEffect(() => {
    loadTickets();
  }, [loadTickets]);

  useEffect(() => {
    const onServer = () => {
      boot();
      loadTickets();
    };
    window.addEventListener('vpt:server-changed', onServer);
    return () => window.removeEventListener('vpt:server-changed', onServer);
  }, [boot, loadTickets]);

  const config = health?.config;
  const configured = Boolean(config?.configured);
  const enabled = Boolean(config?.enabled);

  const closeSetup = () => {
    setShowSetup(false);
    setFormToken('');
    setFormError(null);
    setFormUrl(config?.base_url ?? '');
    setFormPublicUrl(config?.public_url ?? '');
  };

  const saveSetup = async () => {
    setBusy(true);
    setFormError(null);
    try {
      await zammadApi.saveConfig({
        base_url: formUrl,
        token: formToken || undefined,
        public_url: formPublicUrl,
      });
      setShowSetup(false);
      setFormToken('');
      await boot();
      refreshReportEnabled();
    } catch (e) {
      // The server tested the connection and refused to save: its reason is the message.
      setFormError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const connection: { word: string; tone: Tone } = !health
    ? { word: '…', tone: 'textMuted' }
    : !configured
      ? { word: t('Not configured'), tone: 'textMuted' }
      : health.reachable
        ? { word: t('Connected'), tone: 'success' }
        : { word: t('Unreachable'), tone: 'error' };
  const statusDetail = [
    connection.word,
    configured ? config?.base_url : null,
    configured ? `${t('Configured from')}: ${config?.source === 'env' ? t('Environment') : t('Settings')}` : null,
    health && !health.reachable ? health.error : null,
  ].filter(Boolean).join(' · ');

  const setupDialog = (
    <Dialog open={showSetup} onClose={closeSetup} fullWidth maxWidth="xs"
            PaperProps={{ sx: { borderRadius: 3, border: `1px solid ${P.borderColor}` } }}>
      <DialogTitle sx={{ pb: 0.5 }}>
        {t('Zammad instance')}
        <Typography variant="body2" sx={{ color: P.textMuted, mt: 0.5 }}>
          {t('The connection is tested before anything is saved.')}
        </Typography>
      </DialogTitle>
      <DialogContent>
        {formError && <Alert severity="error" sx={{ mt: 1 }}>{formError}</Alert>}
        <Box component="form" autoComplete="off" onSubmit={(e) => e.preventDefault()}
             sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          <TextField size="small" fullWidth label={t('Zammad URL')} name="zm-instance-address" autoComplete="off"
                     value={formUrl} onChange={(e) => setFormUrl(e.target.value)}
                     placeholder={EXAMPLE_URL} />
          <TextField size="small" fullWidth label={t('API token')} name="zm-instance-secret" autoComplete="new-password"
                     type="password" value={formToken} onChange={(e) => setFormToken(e.target.value)}
                     placeholder={config?.has_token ? t('•••••••• (saved)') : undefined}
                     InputLabelProps={{ shrink: true }} />
          <TextField size="small" fullWidth label={t('Public URL (optional)')} name="zm-public-address" autoComplete="off"
                     value={formPublicUrl} onChange={(e) => setFormPublicUrl(e.target.value)}
                     helperText={t('Where agents open tickets from a browser. Defaults to the Zammad URL.')} />
        </Box>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button disabled={busy} onClick={closeSetup} sx={{ color: P.accentText, fontWeight: 600 }}>{t('Cancel')}</Button>
        <Button sx={goldButtonSx(P)} disabled={busy || !formUrl || (!formToken && !config?.has_token)} onClick={saveSetup}>
          {busy ? t('Testing…') : t('Test and save')}
        </Button>
      </DialogActions>
    </Dialog>
  );

  return (
    <Box sx={pageSurfaceSx(P)}>
      <Box sx={{ maxWidth: CONTENT_MAX, mx: 'auto' }}>
        <PageTitle
          title={
            <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 1 }}>
              {t('Zammad')}
              <Tooltip title={statusDetail}>
                <Box
                  component="span"
                  role="img"
                  aria-label={statusDetail}
                  sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: P[connection.tone], display: 'inline-block' }}
                />
              </Tooltip>
            </Box>
          }
          subtitle={
            configured
              ? `${config?.base_url}${health?.user ? ` · ${health.user}` : ''}`
              : t('Connect a Zammad helpdesk to file support tickets from the app')
          }
          right={
            <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center' }}>
              {configured && enabled && (
                <Button sx={goldButtonSx(P)} onClick={() => openReportIncident()}>
                  {t('Open a ticket')}
                </Button>
              )}
              {isAdmin && configured && (
                <Tooltip title={t('Instance settings')}>
                  <IconButton
                    aria-label={t('Instance settings')}
                    onClick={() => setShowSetup(true)}
                    sx={{
                      width: 36, height: 36, borderRadius: 2, border: '1px solid',
                      borderColor: P.borderColor, color: P.textSecondary,
                    }}
                  >
                    <SettingsIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              )}
            </Box>
          }
        />

        {!health && !error && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
            <CircularProgress size={26} />
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>
        )}

        {health && !configured && (
          <Card sx={{ maxWidth: 560, mx: 'auto' }}>
            <CardContent sx={{ py: 4, textAlign: 'center' }}>
              <Box sx={{ color: P.accentText, mb: 1.5 }}><ZammadMark fontSize={40} /></Box>
              <Typography variant="h6" sx={{ mb: isAdmin ? 2.5 : 0, color: P.textPrimary }}>
                {t('Connect to Zammad')}
              </Typography>
              {!isAdmin && (
                <Typography variant="body2" sx={{ color: P.textMuted }}>
                  {t('An admin has to connect the instance.')}
                </Typography>
              )}
              {isAdmin && (
                <Button sx={goldButtonSx(P)} onClick={() => setShowSetup(true)}>{t('Setup')}</Button>
              )}
            </CardContent>
          </Card>
        )}

        {health && configured && (
          <>
            <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center', flexWrap: 'wrap', mb: 1.5 }}>
              <ToggleButtonGroup exclusive size="small" value={period} onChange={(_, v) => v && setPeriod(v)} sx={segmentedSx(P, 'sm')}>
                <ToggleButton value="today">{t('Today')}</ToggleButton>
                <ToggleButton value="7d">{t('7d')}</ToggleButton>
                <ToggleButton value="30d">{t('30d')}</ToggleButton>
                <ToggleButton value="all">{t('All')}</ToggleButton>
              </ToggleButtonGroup>
              {teamOptions.length > 1 && (
                <TextField select size="small" label={t('Team')} value={teamId} sx={{ minWidth: 150 }}
                           onChange={(e) => { setTeamId(e.target.value); setUser(''); }}>
                  <MenuItem value="">{t('My team')}</MenuItem>
                  {teamOptions.map((o) => <MenuItem key={o.key} value={o.key}>{o.label}</MenuItem>)}
                </TextField>
              )}
              <TextField select size="small" label={t('User')} value={user} sx={{ minWidth: 170 }}
                         onChange={(e) => setUser(e.target.value)}>
                <MenuItem value="">{t('All')}</MenuItem>
                {(stats?.users ?? []).map((u) => <MenuItem key={u.id} value={u.id}>{u.email}</MenuItem>)}
              </TextField>
              {projectOptions.length > 0 && (
                <TextField select size="small" label={t('Project')} value={project} sx={{ minWidth: 150 }}
                           onChange={(e) => setProject(e.target.value)}>
                  <MenuItem value="">{t('All')}</MenuItem>
                  {projectOptions.map((o) => <MenuItem key={o.key} value={o.key}>{o.label}</MenuItem>)}
                </TextField>
              )}
            </Box>
            <StatTiles
              columns={3}
              tiles={[
                { label: t('Opened'), value: stats?.opened ?? (listError ? '—' : '…') },
                { label: t('Closed'), value: stats?.closed ?? (listError ? '—' : '…') },
                { label: t('Total (all time)'), value: stats?.total ?? (listError ? '—' : '…') },
              ]}
            />
            {listError && (
              <Alert severity="error" sx={{ mb: 2 }}>{t('Could not load tickets: {error}', { error: listError })}</Alert>
            )}
            {!health.reachable && health.error && (
              <Alert severity="error" sx={{ mb: 2 }}>{health.error}</Alert>
            )}
            {!enabled && (
              <Alert severity="info" sx={{ mb: 2 }}>
                {t('Support tickets are off: "Open a ticket" is hidden and new tickets are refused. Switch them on in Settings → Features.')}
              </Alert>
            )}

            <Typography sx={{ fontWeight: 600, fontSize: '0.95rem', color: P.textPrimary, mb: 1 }}>
              {t('Recent tickets')}
            </Typography>
            {listError ? null : tickets.length === 0 ? (
              <Typography variant="body2" sx={{ color: P.textMuted }}>{t('No tickets yet.')}</Typography>
            ) : (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>#</TableCell>
                      <TableCell>{t('Title')}</TableCell>
                      <TableCell>{t('Type')}</TableCell>
                      <TableCell>{t('Area')}</TableCell>
                      <TableCell>{t('Status')}</TableCell>
                      <TableCell>{t('Created')}</TableCell>
                      <TableCell />
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {tickets.map((ticket) => (
                      <TableRow key={ticket.id}>
                        <TableCell sx={{ color: P.textSecondary }}>{ticket.external_number ?? '—'}</TableCell>
                        <TableCell>{ticket.title}</TableCell>
                        <TableCell sx={{ whiteSpace: 'nowrap' }}>
                          <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
                            {label[ticket.ticket_type]}
                            {ticket.priority && (
                              <Chip
                                size="small"
                                variant="outlined"
                                label={ticket.priority}
                                title={label[ticket.priority]}
                                sx={{
                                  height: 20, fontSize: 11,
                                  color: P[PRIORITY_TONE[ticket.priority]],
                                  borderColor: P[PRIORITY_TONE[ticket.priority]],
                                }}
                              />
                            )}
                            {ticket.severity && (
                              <Chip
                                size="small"
                                variant="outlined"
                                label={label[ticket.severity]}
                                sx={{
                                  height: 20, fontSize: 11,
                                  color: P[SEVERITY_TONE[ticket.severity]],
                                  borderColor: P[SEVERITY_TONE[ticket.severity]],
                                }}
                              />
                            )}
                          </Box>
                        </TableCell>
                        <TableCell sx={{ color: P.textSecondary }}>
                          {[label[ticket.family], label[ticket.category], ticket.target_label || ticket.target_id]
                            .filter(Boolean).join(' / ')}
                        </TableCell>
                        <TableCell>
                          <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75, color: P[STATUS_TONE[ticket.reporter_status]] }}>
                            <Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: P[STATUS_TONE[ticket.reporter_status]] }} />
                            {statusLabel[ticket.reporter_status]}
                          </Box>
                        </TableCell>
                        <TableCell sx={{ color: P.textSecondary }}>{formatDate(ticket.created_at)}</TableCell>
                        <TableCell align="right">
                          {ticket.zammad_url && (
                            <Tooltip title={t('Open in Zammad')}>
                              <IconButton
                                size="small"
                                component={Link}
                                href={ticket.zammad_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                aria-label={t('Open in Zammad')}
                              >
                                <ExternalIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </>
        )}
      </Box>
      {setupDialog}
    </Box>
  );
}
