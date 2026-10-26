/**
 * ProjectDetail — the one project page (Overview | Scope | Usage | Team).
 *
 * Sources: `GET /server/projects/<id>/overview` (project, tags, edit rights),
 * `/executive` (pass rate + delta, daily trend, top failures, members) and `/in-scope`
 * (devices, executables, per-project AI usage). The Last executions table is the one of
 * Run Tests (`useExecutionHistoryRows`), narrowed to the project's scripts and devices.
 * `/projects/:id/executive-summary` redirects to `?tab=overview`.
 *
 * Rename / Delete (BUG-0577) are gated on `permissions.can_edit` and live in the overflow menu.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate, useSearchParams, Link as RouterLink } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Link,
  Menu,
  MenuItem,
  Paper,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import FolderOutlinedIcon from '@mui/icons-material/FolderOutlined';
import LocalOfferOutlinedIcon from '@mui/icons-material/LocalOfferOutlined';
import MoreHorizIcon from '@mui/icons-material/MoreHoriz';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import PeopleOutlineIcon from '@mui/icons-material/PeopleOutline';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { ExecutionHistoryFilters } from '../components/common/ExecutionHistoryFilters';
import ExecutionHistorySection from '../components/common/ExecutionHistorySection';
import { AddKind, AddToProjectDialog } from '../components/projects/AddToProjectDialog';
import { ProjectInScope, fetchProjectInScope } from '../components/projects/ProjectInScope';
import { ProjectTagsEditor } from '../components/projects/ProjectTagsEditor';
import {
  neutralButtonSx,
  PageTitle,
  pageSurfaceSx,
  primaryButtonSx,
  segmentedSx,
  StatTiles,
  StatTile,
} from '../components/common/PageChrome';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { AppIcon, StatusText } from '../constants/icons';
import { useToast } from '../contexts';
import { useExecutionHistoryFilters } from '../hooks/executions/useExecutionHistoryFilters';
import { useExecutionHistoryRows } from '../hooks/executions/useExecutionHistoryRows';
import { useRerun } from '../hooks/script/useRerun';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import { useI18n } from '../i18n/useI18n';
import { api, apiClient } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { openR2Url } from '../utils/infrastructure/cloudflareUtils';
import {
  Project,
  useCurrentProject,
  writeCurrentProjectId,
} from '../hooks/common/useCurrentProject';
import { TYPOGRAPHY } from '../constants/typography';


interface OverviewResponse {
  project: Project;
  days: number;
  // `my_role` is the caller's row in `projects_members` (null for admins / service keys);
  // `can_edit` is the same gate the PATCH / DELETE / members routes enforce.
  permissions: {
    my_role: 'owner' | 'viewer' | null;
    can_edit: boolean;
  };
}

interface MemberRow {
  team_member_id: string;
  display_name: string;
  role: 'owner' | 'viewer';
}

interface ExecutiveResponse {
  days: number;
  tiles: {
    health: { level: 'green' | 'yellow' | 'red'; current: number; previous: number; delta_pp: number };
    pass_rate_trend: Array<{ day: string; pass: number; fail: number; total: number; pass_rate: number | null }>;
    top_failures: Array<{
      script_name: string;
      failure_count: number;
      last_failure_at: string | null;
      last_failure_report_url?: string | null;
    }>;
    members: { owners: MemberRow[]; viewers: MemberRow[]; can_add: boolean; can_remove: boolean };
  };
}

type TabId = 'overview' | 'scope' | 'usage' | 'team';
const TABS: TabId[] = ['overview', 'scope', 'usage', 'team'];

const formatTokens = (n: number): string => {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)} M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)} k`;
  return String(n);
};
const formatDelta = (pp: number): string => `${pp > 0 ? '+' : ''}${pp.toFixed(1)} pp`;
const DASH = '—';

// BUG-0577 — matches the 60-char cap on POST /server/projects so rename can share the same
// validator. The server still re-checks; the mirror only keeps Save disabled and the error inline.
const MAX_PROJECT_NAME_LEN = 60;


const ProjectDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { isMobile } = useResponsiveMode();
  const { showError, showSuccess } = useToast();
  const { rerun } = useRerun();
  const [searchParams, setSearchParams] = useSearchParams();
  const { refresh: refreshProjectsList, setCurrentProject } = useCurrentProject();

  const requestedTab = searchParams.get('tab');
  const tab: TabId = TABS.includes(requestedTab as TabId) ? (requestedTab as TabId) : 'overview';
  const setTab = (next: TabId) => {
    const sp = new URLSearchParams(searchParams);
    if (next === 'overview') sp.delete('tab'); else sp.set('tab', next);
    setSearchParams(sp, { replace: true });
  };

  const overviewQ = useQuery<OverviewResponse>({
    queryKey: ['project', 'overview', id, 30],
    queryFn: () => api.get<OverviewResponse>(buildServerUrl(`/server/projects/${id}/overview?days=30`)),
    enabled: !!id,
    staleTime: 30_000,
  });
  const executiveQ = useQuery<ExecutiveResponse>({
    queryKey: ['project', 'executive', id, 30],
    queryFn: () => api.get<ExecutiveResponse>(buildServerUrl(`/server/projects/${id}/executive?days=30`)),
    enabled: !!id,
    staleTime: 30_000,
  });
  const inScopeQ = useQuery({
    queryKey: ['project', 'in-scope', id, 30],
    queryFn: () => fetchProjectInScope(id!, 30),
    enabled: !!id,
    staleTime: 30_000,
  });

  // Reflect this project into localStorage so other pages (Atlas, scripts) pick up the scope.
  useEffect(() => {
    if (id) writeCurrentProjectId(id);
  }, [id]);

  const project = overviewQ.data?.project;
  const canEdit = overviewQ.data?.permissions?.can_edit ?? false;
  const exec = executiveQ.data?.tiles;
  const inScope = inScopeQ.data;

  const refreshAll = () => {
    void overviewQ.refetch();
    void executiveQ.refetch();
    void inScopeQ.refetch();
    void queryClient.invalidateQueries({ queryKey: ['projects', 'list'] });
  };

  // Last executions: Run Tests' rows, narrowed to this project's scripts and devices.
  const projectFilter = useMemo(() => ({
    scriptNames: [...(inScope?.executables ?? []).map((e) => e.name), ...(inScope?.campaigns ?? []).map((c) => c.name)],
    devices: (inScope?.devices ?? []).map((d) => ({ host_name: d.host_name, device_id: d.device_id })),
  }), [inScope]);
  const historyRows = useExecutionHistoryRows(projectFilter);
  const historyFilters = useExecutionHistoryFilters(historyRows);
  const runningNow = historyRows.filter((r) => r.status === 'running').length;

  const [addKind, setAddKind] = useState<AddKind | null>(null);
  const [tagsOpen, setTagsOpen] = useState(false);
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);
  const [memberError, setMemberError] = useState<string | null>(null);

  // BUG-0577 — Rename dialog state. Keeping it as plain useState (the dialog
  // is short-lived and not a complex multi-step flow) means we don't need an
  // extra ConfirmDialog wrapper; the inner Submit / Cancel buttons drive the
  // rename mutation directly.
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameName, setRenameName] = useState('');
  const [renameError, setRenameError] = useState<string | null>(null);
  // The DELETE confirmation is a true confirm-once flow — that one uses the
  // shared `ConfirmDialog` so the destructive action stays unmistakably red.
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    // Seed the rename field whenever the dialog opens so the user sees the
    // current name pre-filled, but reset the error from a prior failed submit.
    if (renameOpen && project) {
      setRenameName(project.name);
      setRenameError(null);
    }
  }, [renameOpen, project]);

  const renameMutation = useMutation({
    mutationFn: async (newName: string) => {
      const trimmed = newName.trim();
      if (!trimmed) {
        throw new Error(t('Project name cannot be empty'));
      }
      if (trimmed.length > MAX_PROJECT_NAME_LEN) {
        throw new Error(t('Project name is too long'));
      }
      // apiClient is used directly because `api.*` only ships GET/POST/PUT/DELETE;
      // the projects route uses PATCH (PATCH /server/projects/<id>).
      const res = await apiClient(buildServerUrl(`/server/projects/${id}`), {
        method: 'PATCH',
        body: JSON.stringify({ name: trimmed }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.error || `HTTP ${res.status}`);
      }
      return res.json() as Promise<Project>;
    },
    onSuccess: async (updated) => {
      setRenameOpen(false);
      setRenameName('');
      setRenameError(null);
      // Refresh both the overview (which carries the project header) and the
      // projects list (the card on /projects) so both views pick up the new
      // name without a hard reload.
      await queryClient.invalidateQueries({ queryKey: ['project', 'overview', id] });
      await refreshProjectsList();
      // `updated` is returned for the caller; nothing else to do.
      void updated;
    },
    onError: (e: Error) => {
      const msg = e?.message ?? '';
      if (/409|duplicate|already exists/i.test(msg)) {
        setRenameError(t('A project with that name already exists in this team'));
      } else if (msg) {
        setRenameError(msg);
      } else {
        setRenameError(t('Failed to rename project'));
      }
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async () => {
      const res = await api.delete<{ message?: string }>(
        buildServerUrl(`/server/projects/${id}`),
      );
      return res;
    },
    onSuccess: async () => {
      setDeleteOpen(false);
      setDeleteError(null);
      // Drop the deleted project from localStorage (the selector otherwise
      // still claims it's selected) and refresh the list cache so the
      // /projects page reflects the new state.
      if (id) writeCurrentProjectId(null);
      if (id) setCurrentProject(null);
      await queryClient.invalidateQueries({ queryKey: ['projects', 'list'] });
      await refreshProjectsList();
      // Drop the overview query so a back-nav doesn't show stale data while
      // the navigation transition to /projects is in flight.
      queryClient.removeQueries({ queryKey: ['project', 'overview', id] });
      navigate('/projects', { replace: true });
    },
    onError: (e: Error) => {
      const msg = e?.message ?? '';
      if (/403|forbidden/i.test(msg)) {
        setDeleteError(t('Only admins and project owners can delete this project'));
      } else if (msg) {
        setDeleteError(msg);
      } else {
        setDeleteError(t('Failed to delete project'));
      }
    },
  });

  const openRename = () => {
    if (!project || !canEdit) return;
    setRenameName(project.name);
    setRenameError(null);
    setRenameOpen(true);
  };

  const closeRename = () => {
    if (renameMutation.isPending) return;
    setRenameOpen(false);
    setRenameName('');
    setRenameError(null);
  };

  const submitRename = () => {
    if (!canEdit) return;
    setRenameError(null);
    renameMutation.mutate(renameName);
  };

  const openDelete = () => {
    if (!canEdit) return;
    setDeleteError(null);
    setDeleteOpen(true);
  };

  const closeDelete = () => {
    if (deleteMutation.isPending) return;
    setDeleteOpen(false);
    setDeleteError(null);
  };

  const submitDelete = () => {
    if (!canEdit) return;
    setDeleteError(null);
    deleteMutation.mutate();
  };

  const removeMember = async (teamMemberId: string) => {
    setMemberError(null);
    try {
      const res = await apiClient(buildServerUrl(`/server/projects/${id}/members/${teamMemberId}`), { method: 'DELETE' });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.error || `HTTP ${res.status}`);
      }
      refreshAll();
    } catch (e) {
      setMemberError(e instanceof Error && e.message ? e.message : t('Failed to remove member'));
    }
  };

  const openReport = async (url: string) => {
    try {
      await openR2Url(url);
    } catch {
      showError(t('Failed to open file. Please try again.'));
    }
  };

  const handleRerun = async (payload: Parameters<typeof rerun>[0]) => {
    const outcome = await rerun(payload);
    if (outcome.started) showSuccess(t('Run started'));
    else showError(outcome.error || t('Could not start the run'));
  };

  const trend = exec?.pass_rate_trend ?? [];
  const runs30 = trend.reduce((sum, b) => sum + b.total, 0);
  const hasRuns = runs30 > 0;
  const members = useMemo(
    () => [...(exec?.members.owners ?? []), ...(exec?.members.viewers ?? [])],
    [exec],
  );
  const devices = inScope?.devices ?? [];
  const devicesOnline = devices.filter((d) => d.state === 'online').length;
  const summary = inScope?.summary;
  const trendData = useMemo(
    () => trend.map((b) => ({ label: b.day.slice(5), pass_rate: b.pass_rate, total: b.total })),
    [trend],
  );

  const statTiles = useMemo<StatTile[]>(() => {
    const health = exec?.health;
    return [
      {
        label: t('Pass rate 30 d'),
        value: hasRuns && health ? `${health.current.toFixed(1)}%` : DASH,
        extra: hasRuns && health ? formatDelta(health.delta_pp) : undefined,
      },
      {
        label: t('Devices online'),
        value: devices.length > 0 ? `${devicesOnline} / ${devices.length}` : DASH,
      },
      {
        label: t('Running now'),
        value: String(runningNow),
        footer: runningNow > 0 ? <StatusText level="info">{t('Running')}</StatusText> : undefined,
      },
      {
        label: t('AI tokens 30 d'),
        value: summary && summary.calls > 0 ? formatTokens(summary.tokens) : DASH,
      },
    ];
  }, [exec, hasRuns, devices.length, devicesOnline, runningNow, summary, t]);

  if (overviewQ.isLoading && !overviewQ.data) {
    return (
      <Box sx={{ ...(pageSurfaceSx(P) as object), py: 2, px: { xs: 1, sm: 0 }, minWidth: 0 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', py: 8 }}>
          <CircularProgress />
        </Box>
      </Box>
    );
  }

  if (overviewQ.error || !overviewQ.data || !project) {
    return (
      <Box sx={{ ...(pageSurfaceSx(P) as object), py: 2, px: { xs: 1, sm: 0 }, minWidth: 0 }}>
        <PageTitle title={t('Project not found')} />
        <Typography sx={{ color: P.textSecondary, py: 2 }}>
          {t('The project may have been deleted.')}{' '}
          <Link component={RouterLink} to="/projects">{t('Back to projects')}</Link>
        </Typography>
      </Box>
    );
  }

  const busy = renameMutation.isPending || deleteMutation.isPending;
  const cardSx = { p: 2, mb: 1.5, borderRadius: 3, border: `1px solid ${P.borderColor}`, boxShadow: 'none' } as const;
  const sectionTitleSx = { fontWeight: 600, mb: 1 } as const;
  const emptyTextSx = { color: P.textSecondary, fontSize: TYPOGRAPHY.body.size } as const;
  const headerButtonSx = { color: P.textSecondary, textTransform: 'none', '&:hover': { color: P.accent, backgroundColor: 'transparent' } } as const;

  const attention = (
    <Paper sx={cardSx}>
      <Typography sx={sectionTitleSx}>{t('Needs attention')}</Typography>
      {!exec || exec.top_failures.length === 0 ? (
        <Typography sx={emptyTextSx}>{t('No failures in this period.')}</Typography>
      ) : (
        exec.top_failures.map((f) => (
          <Stack
            key={f.script_name}
            direction="row"
            spacing={1}
            alignItems="center"
            sx={{ py: 0.75, borderBottom: `1px solid ${P.borderColor}`, '&:last-of-type': { borderBottom: 0 } }}
          >
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography noWrap sx={{ fontWeight: 500, fontSize: TYPOGRAPHY.body.size }}>{f.script_name}</Typography>
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
                {f.last_failure_at ? new Date(f.last_failure_at).toLocaleString() : DASH}
              </Typography>
            </Box>
            <StatusText ok={false}>{t('{count} failed', { count: f.failure_count })}</StatusText>
            {f.last_failure_report_url && (
              <Link
                component="button"
                underline="hover"
                onClick={() => { void openReport(f.last_failure_report_url!); }}
                sx={{ fontSize: TYPOGRAPHY.caption.size, display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
              >
                <AppIcon name="report" />
                {t('Report')}
              </Link>
            )}
          </Stack>
        ))
      )}
    </Paper>
  );

  const devicesCard = (
    <Paper sx={cardSx}>
      <Typography sx={sectionTitleSx}>{t('Devices')}</Typography>
      {devices.length === 0 ? (
        <Typography sx={emptyTextSx}>{t('No devices in this project.')}</Typography>
      ) : (
        devices.map((d) => (
          <Stack
            key={`${d.host_name}:${d.device_id}`}
            direction="row"
            spacing={1}
            alignItems="center"
            sx={{ py: 0.75, borderBottom: `1px solid ${P.borderColor}`, '&:last-of-type': { borderBottom: 0 } }}
          >
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography noWrap sx={{ fontSize: TYPOGRAPHY.body.size }}>{d.device_name || d.device_id}</Typography>
              <Typography noWrap sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>{d.host_name}</Typography>
            </Box>
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
              {d.pct_pass === null ? DASH : `${d.pct_pass}%`}
            </Typography>
            <StatusText level={d.state === 'online' ? 'success' : 'info'}>
              {d.state === 'online' ? t('Online') : t('Idle')}
            </StatusText>
            <Link
              component={RouterLink}
              to={`/device-control?device=${encodeURIComponent(`${d.host_name}/${d.device_id}`)}`}
              underline="hover"
              sx={{ fontSize: TYPOGRAPHY.caption.size, display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
            >
              <AppIcon name="device" />
              {t('Control')}
            </Link>
          </Stack>
        ))
      )}
    </Paper>
  );

  const getStarted = (
    <Paper sx={cardSx}>
      <Typography sx={sectionTitleSx}>{t('Get started')}</Typography>
      <Stack spacing={0.75} sx={{ mb: 1.5 }}>
        <StatusText level={(inScope?.totals.devices ?? 0) > 0 ? 'success' : 'info'}>{t('Add a device')}</StatusText>
        <StatusText level={(inScope?.totals.executables.total ?? 0) > 0 ? 'success' : 'info'}>{t('Add a script or testcase')}</StatusText>
        <StatusText level="info">{t('Run it')}</StatusText>
      </Stack>
      {canEdit && (
        <Button
          variant="contained"
          size="small"
          startIcon={<AddIcon />}
          sx={primaryButtonSx(P)}
          onClick={() => setAddKind((inScope?.totals.devices ?? 0) > 0 ? 'script' : 'device')}
        >
          {(inScope?.totals.devices ?? 0) > 0 ? t('Add a script') : t('Add a device')}
        </Button>
      )}
    </Paper>
  );

  const executionsCard = (
    <ExecutionHistorySection
      title={`${t('Last executions')} (${historyFilters.filteredRows.length})`}
      titleExtra={<ExecutionHistoryFilters filters={historyFilters} />}
      rows={historyFilters.filteredRows}
      scriptColumnLabel={t('Test')}
      richColumns
      emptyMessage={t('No executions yet')}
      onOpenUrl={(url) => { void openReport(url); }}
      onRerun={(payload) => { void handleRerun(payload); }}
      isCompact={isMobile}
      cardSx={{ '& .MuiCardContent-root': { p: 2, '&:last-child': { pb: 2 } } }}
      contentSx={{ p: 2, '&:last-child': { pb: 2 } }}
    />
  );

  const trendCard = hasRuns ? (
    <Accordion disableGutters elevation={0} sx={{ mt: 1.5, border: `1px solid ${P.borderColor}`, borderRadius: '12px !important', '&:before': { display: 'none' } }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography sx={{ fontWeight: 600 }}>{t('Stand-up trend')}</Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Box sx={{ width: '100%', height: 220 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={trendData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={P.borderColor} strokeDasharray="3 3" />
              <XAxis dataKey="label" stroke={P.textSecondary} fontSize="0.6875rem" tickLine={false} minTickGap={24} />
              <YAxis domain={[0, 100]} stroke={P.textSecondary} fontSize="0.6875rem" tickLine={false} tickFormatter={(v: number) => `${v}%`} width={40} />
              <ChartTooltip
                contentStyle={{ background: P.surface, border: `1px solid ${P.borderColor}`, borderRadius: 8, fontSize: TYPOGRAPHY.caption.size }}
                formatter={(value, _name, item) => {
                  if (value == null) return [t('No runs'), ''];
                  const total = (item as { payload?: { total?: number } })?.payload?.total ?? 0;
                  return [`${Number(value).toFixed(1)}% (${total} ${t('runs')})`, t('Pass rate')];
                }}
              />
              <Line type="monotone" dataKey="pass_rate" stroke={P.accent} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </Box>
        {exec && (
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
            {t('Previous period {previous}% · now {current}%', { previous: exec.health.previous.toFixed(1), current: exec.health.current.toFixed(1) })}
          </Typography>
        )}
      </AccordionDetails>
    </Accordion>
  ) : null;

  const usageTable = (rows: Array<{ key: string; label: string; tokens: number }>) => (
    rows.length === 0 ? (
      <Typography sx={emptyTextSx}>{DASH}</Typography>
    ) : (
      rows.map((r) => (
        <Stack key={r.key} direction="row" justifyContent="space-between" sx={{ py: 0.5, borderBottom: `1px solid ${P.borderColor}`, '&:last-of-type': { borderBottom: 0 } }}>
          <Typography noWrap sx={{ fontSize: TYPOGRAPHY.body.size }}>{r.label}</Typography>
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontVariantNumeric: 'tabular-nums' }}>{formatTokens(r.tokens)}</Typography>
        </Stack>
      ))
    )
  );

  return (
    <Box sx={{ ...(pageSurfaceSx(P) as object), py: 2, px: { xs: 1, sm: 0 }, minWidth: 0 }}>
      <PageTitle
        title={
          <Stack direction="row" spacing={1} alignItems="center">
            <Tooltip title={t('Back to projects')} placement="bottom" arrow>
              <span>
                <IconButton
                  size="small"
                  onClick={() => navigate('/projects')}
                  disabled={busy}
                  aria-label={t('Back to projects')}
                  data-testid="project-back-btn"
                  sx={{ color: P.textSecondary, mr: 0.25, '&:hover': { color: P.accent, backgroundColor: 'transparent' } }}
                >
                  <ArrowBackIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
            <FolderOutlinedIcon sx={{ color: project.color ?? P.accent }} />
            <Typography component="span" sx={{ fontWeight: 600 }}>{project.name}</Typography>
            {hasRuns && exec && (
              <Box component="span" sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 400 }}>
                <StatusText level={exec.health.level === 'green' ? 'success' : exec.health.level === 'yellow' ? 'warning' : 'error'}>
                  {exec.health.level === 'green' ? t('Healthy') : exec.health.level === 'yellow' ? t('Degraded') : t('Failing')}
                </StatusText>
              </Box>
            )}
          </Stack>
        }
        subtitle={project.description || undefined}
        right={
          <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap" useFlexGap>
            <Button size="small" startIcon={<LocalOfferOutlinedIcon />} onClick={() => setTagsOpen(true)} aria-label={t('Tags')} data-testid="project-tags-btn" sx={headerButtonSx}>
              {(project.tags || []).length}
            </Button>
            <Button size="small" startIcon={<PeopleOutlineIcon />} onClick={() => setTab('team')} aria-label={t('Members')} sx={headerButtonSx}>
              {project.owner_count + project.viewer_count}
            </Button>
            {canEdit && (
              <Button size="small" variant="outlined" startIcon={<AddIcon />} onClick={() => setAddKind('script')} sx={neutralButtonSx(P)} data-testid="project-add-btn">
                {t('Add')}
              </Button>
            )}
            <Button size="small" variant="contained" startIcon={<PlayArrowIcon />} onClick={() => navigate('/run/tests')} sx={primaryButtonSx(P)} data-testid="project-run-btn">
              {t('Run')}
            </Button>
            {canEdit && (
              <>
                <IconButton size="small" onClick={(e) => setMenuAnchor(e.currentTarget)} disabled={busy} aria-label={t('More')} data-testid="project-menu-btn" sx={{ color: P.textSecondary }}>
                  <MoreHorizIcon fontSize="small" />
                </IconButton>
                <Menu anchorEl={menuAnchor} open={!!menuAnchor} onClose={() => setMenuAnchor(null)}>
                  <MenuItem data-testid="project-rename-btn" onClick={() => { setMenuAnchor(null); openRename(); }}>
                    <EditOutlinedIcon fontSize="small" sx={{ mr: 1 }} />
                    {t('Rename project')}
                  </MenuItem>
                  <MenuItem data-testid="project-delete-btn" onClick={() => { setMenuAnchor(null); openDelete(); }} sx={{ color: P.dangerText }}>
                    <DeleteOutlineIcon fontSize="small" sx={{ mr: 1 }} />
                    {t('Delete project')}
                  </MenuItem>
                </Menu>
              </>
            )}
          </Stack>
        }
      />

      <Box sx={{ overflowX: 'auto', mb: 1.5 }}>
        <ToggleButtonGroup
          exclusive
          size="small"
          value={tab}
          onChange={(_e, v: TabId | null) => { if (v) setTab(v); }}
          sx={segmentedSx(P)}
        >
          <ToggleButton value="overview">{t('Overview')}</ToggleButton>
          <ToggleButton value="scope">{t('Scope')}</ToggleButton>
          <ToggleButton value="usage">{t('Usage')}</ToggleButton>
          <ToggleButton value="team">{t('Team')}</ToggleButton>
        </ToggleButtonGroup>
      </Box>

      {tab === 'overview' && (
        <>
          {hasRuns ? (
            <StatTiles tiles={statTiles} large centered columns={4} />
          ) : (
            getStarted
          )}
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: hasRuns ? '1fr 1fr' : '1fr' }, gap: 1.5 }}>
            {hasRuns && attention}
            {devicesCard}
          </Box>
          {executionsCard}
          {trendCard}
        </>
      )}

      {tab === 'scope' && id && (
        <ProjectInScope
          projectId={id}
          canEdit={canEdit}
          data={inScope}
          loading={inScopeQ.isLoading}
          onChanged={refreshAll}
          onAdd={(kind) => setAddKind(kind)}
        />
      )}

      {tab === 'usage' && (
        <>
          <Paper sx={cardSx}>
            <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
              <Typography sx={{ fontWeight: 600, flex: 1 }}>{t('AI tokens 30 d')}</Typography>
              <Link
                component={RouterLink}
                to={`/monitoring/ai-usage?period=168&project=${project.id}`}
                underline="hover"
                sx={{ fontSize: TYPOGRAPHY.body.size, display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
              >
                {t('Open AI usage')}
                <OpenInNewIcon sx={{ fontSize: TYPOGRAPHY.body.size }} />
              </Link>
            </Stack>
            {summary && summary.calls > 0 ? (
              <Typography sx={{ fontSize: TYPOGRAPHY.kpiValue.size, fontWeight: 600, lineHeight: 1.3 }}>
                {formatTokens(summary.tokens)}
                <Box component="span" sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 400, color: P.textSecondary, ml: 1 }}>
                  {t('{calls} calls · ${cost}', { calls: summary.calls, cost: summary.cost_usd.toFixed(2) })}
                </Box>
              </Typography>
            ) : (
              <Typography sx={emptyTextSx}>{DASH}</Typography>
            )}
          </Paper>
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 1.5 }}>
            <Paper sx={cardSx}>
              <Typography sx={sectionTitleSx}>{t('Top features')}</Typography>
              {usageTable((summary?.top_features ?? []).map((f) => ({ key: f.key, label: f.key, tokens: f.tokens })))}
            </Paper>
            <Paper sx={cardSx}>
              <Typography sx={sectionTitleSx}>{t('Top senders')}</Typography>
              {usageTable((summary?.top_senders ?? []).map((s) => ({ key: s.key, label: s.label, tokens: s.tokens })))}
            </Paper>
          </Box>
        </>
      )}

      {tab === 'team' && (
        <Paper sx={cardSx}>
          <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
            <Typography sx={{ fontWeight: 600, flex: 1 }}>{t('Members')}</Typography>
            {canEdit && (
              <Button size="small" variant="outlined" startIcon={<AddIcon />} onClick={() => setAddKind('user')} sx={neutralButtonSx(P)} data-testid="project-add-user-btn">
                {t('Add user')}
              </Button>
            )}
          </Stack>
          {memberError && <Box role="alert" sx={{ color: P.error, fontSize: TYPOGRAPHY.body.size, mb: 1 }}>{memberError}</Box>}
          {members.length === 0 ? (
            <Typography sx={emptyTextSx}>{DASH}</Typography>
          ) : (
            members.map((m) => (
              <Stack key={m.team_member_id} direction="row" spacing={1} alignItems="center" sx={{ py: 0.75, borderBottom: `1px solid ${P.borderColor}`, '&:last-of-type': { borderBottom: 0 } }}>
                <Typography noWrap sx={{ flex: 1, minWidth: 0, fontSize: TYPOGRAPHY.body.size }}>{m.display_name}</Typography>
                <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
                  {m.role === 'owner' ? t('Owner') : t('Viewer')}
                </Typography>
                {exec?.members.can_remove && (
                  <Tooltip title={t('Remove')} arrow>
                    <IconButton size="small" aria-label={t('Remove')} onClick={() => { void removeMember(m.team_member_id); }} sx={{ color: P.textMuted, '&:hover': { color: P.dangerText } }}>
                      <AppIcon name="close" />
                    </IconButton>
                  </Tooltip>
                )}
              </Stack>
            ))
          )}
        </Paper>
      )}

      <AddToProjectDialog
        open={addKind !== null}
        onClose={() => setAddKind(null)}
        projectId={project.id}
        teamId={project.team_id}
        initialKind={addKind ?? 'script'}
        inScope={inScope}
        memberIds={members.map((m) => m.team_member_id)}
        canEdit={canEdit}
        onAdded={refreshAll}
      />
      <ProjectTagsEditor
        open={tagsOpen}
        onClose={() => setTagsOpen(false)}
        projectId={project.id}
        canEdit={canEdit}
        tags={project.tags || []}
        onChanged={refreshAll}
      />

      {/* BUG-0577 — Rename dialog. Plain Dialog (not ConfirmDialog) because the
          user has to type a new name; the destructive action would be a delete.
          Submit is disabled until the name is non-empty, under the cap, and the
          mutation is idle. Errors from the server land on `renameError` and
          stay inside the dialog so the user can retry without losing the form. */}
      <Dialog
        open={renameOpen}
        onClose={closeRename}
        maxWidth="xs"
        fullWidth
        aria-labelledby="project-rename-dialog-title"
      >
        <DialogTitle id="project-rename-dialog-title">{t('Rename project')}</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, mt: 1 }}>
            <Tooltip
              title={t('Use 60 characters or fewer')}
              open={renameName.trim().length > MAX_PROJECT_NAME_LEN}
              placement="top"
              arrow
            >
              <TextField
                label={t('Project name')}
                value={renameName}
                onChange={(e) => setRenameName(e.target.value)}
                autoFocus
                fullWidth
                size="small"
                error={renameName.trim().length > MAX_PROJECT_NAME_LEN}
                helperText={
                  renameName.trim().length > MAX_PROJECT_NAME_LEN
                    ? t('Project name is too long')
                    : ' '
                }
                disabled={renameMutation.isPending}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !renameMutation.isPending) {
                    e.preventDefault();
                    submitRename();
                  }
                }}
              />
            </Tooltip>
            {renameError && (
              <Box sx={{ color: P.error, fontSize: TYPOGRAPHY.body.size }}>
                {renameError}
              </Box>
            )}
          </Box>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2, pt: 1, gap: 1 }}>
          <Button
            onClick={closeRename}
            disabled={renameMutation.isPending}
            size="small"
          >
            {t('Cancel')}
          </Button>
          <Button
            onClick={submitRename}
            variant="contained"
            color="primary"
            size="small"
            disabled={
              !renameName.trim() ||
              renameName.trim().length > MAX_PROJECT_NAME_LEN ||
              renameMutation.isPending ||
              // Don't bother sending a no-op rename when the name didn't change —
              // the server would 409 with a duplicate error if the caller's name
              // matches the current row (race-y but possible). Keep the button
              // disabled until the trimmed value diverges from the loaded project.
              renameName.trim() === project.name
            }
          >
            {renameMutation.isPending ? t('Saving…') : t('Save')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* BUG-0577 — Delete confirmation. Uses the shared `ConfirmDialog` so the
          destructive action stays unmistakably red (confirmColor="error"). The
          `deleteError` line is rendered below the message when the API call
          fails; the dialog stays open so the user can retry or close it
          themselves. */}
      <ConfirmDialog
        open={deleteOpen}
        title={t('Delete project')}
        message={
          `${t('This will permanently delete "{name}" and remove its scope tag from every script, testcase, virtual script, and campaign it owns.', { name: project.name })}\n\n` +
          t('This action cannot be undone.')
        }
        confirmText={deleteMutation.isPending ? t('Deleting…') : t('Delete')}
        confirmColor="error"
        onConfirm={submitDelete}
        onCancel={closeDelete}
      />
      {deleteError && deleteOpen && (
        <Box
          sx={{
            position: 'fixed',
            bottom: 24,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 1500,
            bgcolor: P.error,
            color: P.paperBackground,
            px: 2,
            py: 1,
            borderRadius: 2,
            fontSize: TYPOGRAPHY.body.size,
            maxWidth: 480,
          }}
          role="alert"
          data-testid="project-delete-error"
        >
          {deleteError}
        </Box>
      )}
    </Box>
  );
};

export default ProjectDetail;
