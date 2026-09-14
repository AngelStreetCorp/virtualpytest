import React, { useState, useEffect, useCallback } from 'react';
import {
  Refresh as RefreshIcon,
  Terminal as LogsIcon,
  Circle as DotIcon,
} from '@mui/icons-material';
import {
  Box,
  Typography,
  Chip,
  IconButton,
  Tooltip,
  CircularProgress,
  Paper,
  Grid,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material';
import { ExpandMore as ExpandMoreIcon } from '@mui/icons-material';

import { ServiceLogsModal } from '../components/common/ServiceLogsModal';
import { buildServerUrl, buildPrimaryServerUrl } from '../utils/buildUrlUtils';
import { useServerManager } from '../hooks/useServerManager';
import { getCached, setCached } from '../utils/pageCache';

// ─── Types ────────────────────────────────────────────────────────────────────

// 'stopped' is distinct from 'unknown': we KNOW the unit is stopped (an
// expected state for optional/disabled services), vs 'unknown' = couldn't
// determine (probe failed). Conflating them mislabels and false-degrades.
type ServiceStatus = 'ok' | 'degraded' | 'error' | 'stopped' | 'unknown' | 'loading';

interface ServiceInfo {
  id: string;
  label: string;
  port?: number | string;
  logService?: string; // systemd service name for /server/logs/view
  logHostName?: string; // host_name for host file-based logs (e.g. deployments)
  status: ServiceStatus;
  detail?: string;
  extra?: string; // e.g. CPU%, version, etc.
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const statusColor = (s: ServiceStatus): 'success' | 'warning' | 'error' | 'default' => {
  if (s === 'ok') return 'success';
  if (s === 'degraded') return 'warning';
  if (s === 'error') return 'error';
  return 'default';
};

const StatusDot: React.FC<{ status: ServiceStatus; size?: number }> = ({ status, size = 14 }) => {
  const color = {
    ok: '#4caf50',
    degraded: '#ff9800',
    error: '#f44336',
    stopped: '#607d8b', // blue-grey: known-off, distinct from unknown
    unknown: '#9e9e9e',
    loading: '#9e9e9e',
  }[status];
  return (
    <DotIcon sx={{ fontSize: size, color, flexShrink: 0 }} />
  );
};


const overallStatus = (services: ServiceInfo[]): ServiceStatus => {
  if (services.some((s) => s.status === 'error')) return 'error';
  if (services.some((s) => s.status === 'degraded' || s.status === 'unknown')) return 'degraded';
  // 'stopped' is an accepted resting state — it doesn't block a group from
  // being "ok" (only 'loading' leaves it indeterminate).
  if (services.every((s) => s.status === 'ok' || s.status === 'stopped')) return 'ok';
  return 'unknown';
};


// ─── Service Row ──────────────────────────────────────────────────────────────

const ServiceRow: React.FC<{
  service: ServiceInfo;
  onViewLogs: (s: ServiceInfo) => void;
  isLast?: boolean;
}> = ({ service, onViewLogs, isLast }) => (
  <Box
    sx={{
      display: 'flex',
      alignItems: 'center',
      py: 1,
      px: 0,
      borderBottom: isLast ? 'none' : '1px solid',
      borderColor: 'divider',
    }}
  >
    {/* LED dot — 24px */}
    <Box sx={{ width: 24, flexShrink: 0, display: 'flex', alignItems: 'center' }}>
      <StatusDot status={service.status} />
    </Box>

    {/* Label — 180px */}
    <Typography variant="body2" sx={{ fontWeight: 500, width: 180, flexShrink: 0 }}>
      {service.label}
    </Typography>

    {/* Port — 60px */}
    <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary', width: 60, flexShrink: 0 }}>
      {service.port ? `:${service.port}` : ''}
    </Typography>

    {/* Status chip — 90px */}
    <Box sx={{ width: 90, flexShrink: 0 }}>
      <Chip
        label={service.status === 'loading' ? 'checking…' : service.status}
        size="small"
        color={statusColor(service.status)}
        variant="outlined"
        sx={{ fontSize: '0.7rem', height: 20 }}
      />
    </Box>

    {/* Detail — fills remaining space */}
    <Typography variant="caption" color="text.secondary" sx={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
      {service.detail ?? ''}
    </Typography>

    {/* Extra (CPU/RAM) — 160px */}
    <Typography variant="caption" color="text.secondary" sx={{ width: 160, flexShrink: 0, textAlign: 'right' }}>
      {service.extra ?? ''}
    </Typography>

    {/* Logs button — 36px */}
    <Box sx={{ width: 36, flexShrink: 0, display: 'flex', justifyContent: 'center' }}>
      {service.logService ? (
        <Tooltip title={`View ${service.logService} logs`}>
          <IconButton size="small" onClick={() => onViewLogs(service)}>
            <LogsIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      ) : null}
    </Box>
  </Box>
);

// ─── Accordion Section ────────────────────────────────────────────────────────

const accordionSx = {
  mb: 1.5,
  boxShadow: 'none',
  border: '1px solid',
  borderColor: 'divider',
  '&:before': { display: 'none' },
  '&.Mui-expanded': { mt: 0 },
};

const AccordionSection: React.FC<{
  title: string;
  subtitle?: string;
  services: ServiceInfo[];
  onViewLogs: (s: ServiceInfo) => void;
  defaultExpanded?: boolean;
}> = ({ title, subtitle, services, onViewLogs, defaultExpanded = false }) => {
  const overall = overallStatus(services.filter((s) => s.status !== 'loading'));
  const okCount = services.filter((s) => s.status === 'ok').length;
  const total = services.filter((s) => s.status !== 'loading').length;

  return (
    <Accordion defaultExpanded={defaultExpanded} sx={accordionSx}>
      <AccordionSummary
        expandIcon={<ExpandMoreIcon />}
        sx={{ minHeight: 40, '& .MuiAccordionSummary-content': { margin: '6px 0', alignItems: 'center', gap: 1 } }}
      >
        <StatusDot status={overall} size={10} />
        <Typography variant="subtitle2" sx={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: '0.72rem' }}>
          {title}
        </Typography>
        {subtitle && (
          <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
            {subtitle}
          </Typography>
        )}
        <Chip
          label={`${okCount}/${total}`}
          size="small"
          color={statusColor(overall)}
          variant="filled"
          sx={{ ml: 'auto', mr: 1, fontSize: '0.65rem', height: 18 }}
        />
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 0, pb: 0.5, px: 2 }}>
        {services.map((svc, i) => (
          <ServiceRow
            key={svc.id}
            service={svc}
            onViewLogs={onViewLogs}
            isLast={i === services.length - 1}
          />
        ))}
      </AccordionDetails>
    </Accordion>
  );
};

// ─── Main Page ────────────────────────────────────────────────────────────────

const Status: React.FC = () => {
  const { serverHostsData } = useServerManager();

  // Service groups
  const DEFAULT_CORE: ServiceInfo[] = [
    { id: 'server',    label: 'Backend Server',  port: 5109, logService: 'vpt-server',   status: 'loading' },
    // Frontend (VM105) & Nginx (VM107) run no backend agent the server can
    // reach, so logs aren't fetchable without a frontend-only SSH special
    // case — no log button. Status still shows 'ok' (page loading = up).
    // 'self' was a placeholder — dropped.
    { id: 'frontend',  label: 'Frontend',        port: 3000, logService: undefined, status: 'ok', extra: 'online' },
    { id: 'nginx',     label: 'Nginx',           port: 443,  logService: undefined, status: 'loading' },
    { id: 'supabase',  label: 'Supabase',        port: 5432, logService: undefined,      status: 'loading' },
    { id: 'minio',     label: 'MinIO / R2',                  logService: undefined,      status: 'loading' },
    { id: 'redis',     label: 'Redis',           port: 6379, logService: undefined,      status: 'loading' },
    { id: 'db-backup', label: 'DB Backup',                   logService: undefined,      status: 'loading' },
  ];

  // Do NOT seed core/runners from pageCache: these are volatile health
  // probes and a stale cached "unknown / GITHUB_TOKEN not set" would show
  // on load until refreshed. The probes are sub-second, so start fresh
  // ('loading' → real) — a brief "checking…" beats a persistent lie.
  const [coreServices, setCoreServices] = useState<ServiceInfo[]>(DEFAULT_CORE);
  const [systemdServices, setSystemdServices] = useState<ServiceInfo[]>(() => getCached<ServiceInfo[]>('status-systemd') ?? []);
  const [hostGroups, setHostGroups] = useState<{ label: string; subtitle: string; services: ServiceInfo[] }[]>([]);
  const [runnerServices, setRunnerServices] = useState<ServiceInfo[]>([]);

  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [checking, setChecking] = useState(false);
  const checkingRef = React.useRef(false);
  const [serverStats, setServerStats] = useState<{ cpu?: number; ram?: number; disk?: number; uptime?: string } | null>(() => getCached('status-stats'));

  // Logs dialog state — the fetch, filters and loading state live inside
  // <ServiceLogsModal/>; this only tracks which service is open.
  const [logsState, setLogsState] = useState<{
    open: boolean;
    serviceLabel: string;
    logService: string;
    logHostName?: string;
  }>({ open: false, serviceLabel: '', logService: '' });

  const openLogs = useCallback((service: ServiceInfo) => {
    if (!service.logService) return;
    setLogsState({
      open: true,
      serviceLabel: service.label,
      logService: service.logService,
      logHostName: service.logHostName,
    });
  }, []);

  const checkAll = useCallback(async () => {
    if (checkingRef.current) return;
    checkingRef.current = true;
    setChecking(true);

    // ── 1. Backend Server + Supabase + Redis + Nginx ─────────────────────
    const checkServer = async () => {
      try {
        const [coreRes, sysRes] = await Promise.allSettled([
          fetch(buildServerUrl('/server/health'), { signal: AbortSignal.timeout(8000) }),
          fetch(buildServerUrl('/server/system/health'), { signal: AbortSignal.timeout(8000) }),
        ]);

        // Default to 'unknown' (grey), NOT 'error' (red). A single failed/
        // aborted probe means "couldn't determine", not "server is down" —
        // the endpoint does a live Supabase+Redis round-trip and a deploy
        // restart or brief blip would otherwise show a sticky red error.
        let serverStatus: ServiceStatus = 'unknown';
        let supabaseStatus: ServiceStatus = 'unknown';
        let supabaseDetail = '';
        let redisStatus: ServiceStatus = 'unknown';
        let redisDetail = '';
        let serverDetail = '';
        let serverProbeOk = false;

        if (coreRes.status === 'fulfilled' && coreRes.value.ok) {
          const d = await coreRes.value.json();
          serverProbeOk = true;
          serverStatus = d.status === 'ok' ? 'ok' : 'degraded';
          supabaseStatus = d.supabase === 'connected' ? 'ok' : d.supabase === 'disconnected' ? 'error' : 'degraded';
          supabaseDetail = d.supabase;
          redisStatus = d.redis === 'connected' ? 'ok' : d.redis === 'disconnected' ? 'error' : d.redis ? 'degraded' : 'unknown';
          redisDetail = d.redis || '';
          serverDetail = d.team_id ? `team: ${d.team_id}` : '';
        } else {
          serverDetail = 'health check unreachable — retrying';
        }

        if (sysRes.status === 'fulfilled' && sysRes.value.ok) {
          const d = await sysRes.value.json();
          if (d.system_stats) {
            const ss = d.system_stats;
            setServerStats({
              cpu: ss.cpu_percent,
              ram: ss.memory_percent,
              disk: ss.disk_percent,
            });
          }
        }

        // Nginx is ok only if we actually reached the server through it.
        // A failed probe is indeterminate (unknown), not proof nginx is down.
        const nginxStatus: ServiceStatus = serverProbeOk ? 'ok' : 'unknown';
        setCoreServices((prev) =>
          prev.map((s) => {
            if (s.id === 'server')   return { ...s, status: serverStatus, detail: serverDetail };
            if (s.id === 'supabase') return { ...s, status: supabaseStatus, detail: supabaseDetail };
            if (s.id === 'redis')    return { ...s, status: redisStatus, detail: redisDetail };
            if (s.id === 'nginx')    return { ...s, status: nginxStatus, detail: nginxStatus === 'ok' ? 'reachable' : 'probe inconclusive' };
            return s;
          })
        );
      } catch {
        setCoreServices((prev) =>
          prev.map((s) =>
            ['server', 'supabase', 'redis', 'nginx'].includes(s.id)
              ? { ...s, status: 'unknown' as ServiceStatus, detail: 'health check unreachable — retrying' }
              : s
          )
        );
      }
    };

    // ── 2. DB Backup ────────────────────────────────────────────────────────
    // Backs up the ONE shared database VM — a global fact, not a property of
    // whichever server happens to be selected in the dropdown. Always the
    // primary server (see buildPrimaryServerUrl), so a customer who has a
    // secondary/slave server selected still sees the real backup status
    // instead of "no backup status" just because that secondary host never
    // ran the (single, shared) backup cron itself.
    const checkDbBackup = async () => {
      try {
        const res = await fetch(buildPrimaryServerUrl('/server/system/backup/status'), { signal: AbortSignal.timeout(8000) });
        if (res.ok) {
          const d = await res.json();
          const s: ServiceStatus = d.status === 'ok' ? 'ok' : 'error';
          const extra = d.age_hours !== null && d.age_hours !== undefined ? `${d.age_hours}h ago` : undefined;
          setCoreServices((prev) => prev.map((sv) => sv.id === 'db-backup' ? { ...sv, status: s, detail: d.detail, extra } : sv));
        } else {
          setCoreServices((prev) => prev.map((sv) => sv.id === 'db-backup' ? { ...sv, status: 'error' as ServiceStatus, detail: 'Could not reach backup status endpoint' } : sv));
        }
      } catch {
        setCoreServices((prev) => prev.map((sv) => sv.id === 'db-backup' ? { ...sv, status: 'error' as ServiceStatus, detail: 'Backup status unavailable' } : sv));
      }
    };

    // ── 3. Storage ──────────────────────────────────────────────────────────
    const checkStorage = async () => {
      try {
        const res = await fetch(buildServerUrl('/server/storage/health'), { signal: AbortSignal.timeout(8000) });
        if (res.ok) {
          const d = await res.json();
          const s: ServiceStatus = d.status === 'healthy' ? (d.r2_configured ? 'ok' : 'degraded') : 'error';
          const detail = d.r2_configured ? 'R2 configured' : 'R2 not configured';
          setCoreServices((prev) => prev.map((sv) => sv.id === 'minio' ? { ...sv, status: s, detail } : sv));
        } else {
          setCoreServices((prev) => prev.map((sv) => sv.id === 'minio' ? { ...sv, status: 'error' as ServiceStatus } : sv));
        }
      } catch {
        setCoreServices((prev) => prev.map((sv) => sv.id === 'minio' ? { ...sv, status: 'error' as ServiceStatus } : sv));
      }
    };

    // ── 4. Server services (systemd service health from getAllHosts)
    const checkServerServices = async () => {
      try {
        const res = await fetch(buildServerUrl('/server/system/getAllHosts?include_system_stats=true'), { signal: AbortSignal.timeout(10000) });
        if (res.ok) {
          const d = await res.json();
          const services = d.server_info?.service_health?.services;
          if (Array.isArray(services)) {
            const mapped: ServiceInfo[] = services.map((svc: { label: string; name: string; resolved_name: string; status: string }) => ({
              id: `server-svc-${svc.resolved_name || svc.name}`,
              label: svc.label,
              logService: svc.resolved_name || svc.name,
              status: svc.status === 'active' ? 'ok' : svc.status === 'stopped' || svc.status === 'inactive' ? 'stopped' : svc.status === 'not_installed' ? 'unknown' : svc.status === 'stuck' ? 'error' : 'degraded',
              detail: svc.status,
            } as ServiceInfo));
            setSystemdServices(mapped);
          }
        }
      } catch {
        // dashboard endpoint not available — leave empty
      }
    };

    // ── 5. CI Runners ───────────────────────────────────────────────────────
    const checkRunners = async () => {
      try {
        // The runner pool belongs to the one GitHub repo, not to whichever
        // server is selected — GITHUB_TOKEN only lives on the primary server's
        // env, so a secondary/slave server always answered "GITHUB_TOKEN not
        // set" regardless of the real runner state. Always ask the primary.
        // Hits the external GitHub API (browser -> server -> GitHub); 8s was
        // too tight, so a slow call timed out and showed a stale row.
        // Served by the optional `cicd` feature (docs/technical/FEATURES.md). With the
        // feature disabled this 404s and the catch below leaves the section empty —
        // core must not depend on a feature being deployed.
        const res = await fetch(buildPrimaryServerUrl('/server/cicd/runners'), { signal: AbortSignal.timeout(20000) });
        if (res.ok) {
          const d = await res.json();
          if (d.success && Array.isArray(d.runners)) {
            const mapped: ServiceInfo[] = d.runners
              // Drop the synthetic "github-hosted" row: it is a dispatch target on the
              // Run CI/CD page, not a machine whose health this page reports.
              .filter((r: { target?: string }) => r.target !== 'github-hosted')
              .map(
                (r: { name: string; status: string; busy: boolean }) =>
                  ({
                    id: `runner-${r.name}`,
                    label: r.name,
                    logService: undefined,
                    status: r.status === 'online' ? 'ok' : 'error',
                    detail: r.status === 'online' ? (r.busy ? 'running a job' : 'idle') : 'offline',
                  }) as ServiceInfo,
              );
            setRunnerServices(mapped);
          } else if (!d.success && d.error?.includes('GITHUB_TOKEN')) {
            // Token genuinely not configured — show single placeholder row
            setRunnerServices([{ id: 'runner-token', label: 'GitHub Runners', status: 'degraded', detail: 'GITHUB_TOKEN not set' } as ServiceInfo]);
          }
        }
      } catch {
        // CI runner endpoint unavailable / slow — leave prior state (not
        // cached, so it self-corrects on the next successful check).
      }
    };

    await Promise.all([checkServer(), checkDbBackup(), checkStorage(), checkServerServices(), checkRunners()]);

    setLastChecked(new Date());
    checkingRef.current = false;
    setChecking(false);
    // Persist latest state so re-navigation shows data immediately.
    // core/runners are intentionally NOT cached (volatile health probes —
    // see their useState; a stale cached value would show a lie on load).
    setSystemdServices((prev) => { setCached('status-systemd', prev); return prev; });
    setServerStats((prev) => { setCached('status-stats', prev); return prev; });
  }, []);

  // Sync host services from ServerManager context — expand individual services per host
  useEffect(() => {
    const groups = serverHostsData.flatMap((serverData) =>
      serverData.hosts.map((host) => {
        const cpu = host.system_stats?.cpu_percent;
        const ram = host.system_stats?.memory_percent;
        const extra = cpu !== undefined && ram !== undefined ? `CPU ${cpu.toFixed(0)}% · RAM ${ram.toFixed(0)}%` : '';

        const hostServiceHealth = host.system_stats?.service_health?.services || [];
        const services: ServiceInfo[] = hostServiceHealth.map((svc: { label: string; name: string; resolved_name?: string; status: string; optional?: boolean }) => ({
          id: `host-${host.host_name}-${svc.name}`,
          label: svc.label,
          logService: svc.resolved_name || svc.name,
          logHostName: host.host_name,
          status: svc.status === 'active' ? 'ok' as ServiceStatus
            : (svc.status === 'stopped' || svc.status === 'inactive') ? (svc.optional ? 'stopped' as ServiceStatus : 'degraded' as ServiceStatus)
            : svc.status === 'stuck' ? 'error' as ServiceStatus
            : 'degraded' as ServiceStatus,
          detail: svc.status,
        }));

        // Fallback if no service_health data available
        if (services.length === 0) {
          const opStatus = host.system_stats?.operational_status || (host.status === 'online' ? 'online' : 'error');
          const s: ServiceStatus = opStatus === 'online' ? 'ok' : opStatus === 'degraded' ? 'degraded' : 'error';
          services.push({
            id: `host-${host.host_name}`,
            label: host.host_name,
            port: host.host_url ? host.host_url.split(':').pop() : 6109,
            logService: 'vpt-host',
            status: s,
            detail: host.host_url,
            extra,
          });
        }

        // Deployment scheduler log entry
        services.push({
          id: `host-${host.host_name}-deployments`,
          label: 'Deployment Scheduler',
          logService: 'deployments',
          logHostName: host.host_name,
          status: host.status === 'online' ? 'ok' : 'unknown',
          detail: 'deployments.log',
        });

        return {
          label: host.host_name,
          subtitle: `${host.host_api_url || host.host_url}${extra ? ` · ${extra}` : ''}`,
          services,
        };
      })
    );
    setHostGroups(groups);
  }, [serverHostsData]);

  // Initial check + 15s polling
  useEffect(() => {
    checkAll();
    const interval = setInterval(checkAll, 15_000);
    return () => clearInterval(interval);
  }, [checkAll]);

  // ── Derived overall status ────────────────────────────────────────────────
  const allServices = [...coreServices, ...systemdServices, ...hostGroups.flatMap(g => g.services), ...runnerServices];
  const overall = overallStatus(allServices.filter((s) => s.status !== 'loading'));
  const healthyCount = allServices.filter((s) => s.status === 'ok').length;
  const totalCount = allServices.filter((s) => s.status !== 'loading').length;

  return (
    <Box>
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <Box display="flex" alignItems="center" justifyContent="space-between" mb={2}>
        <Box display="flex" alignItems="center" gap={1}>
          <StatusDot status={overall} size={12} />
          <Typography variant="h4" component="h1">
            System Status
          </Typography>
        </Box>
        <Box display="flex" alignItems="center" gap={1}>
          {lastChecked && (
            <Typography variant="caption" color="text.secondary">
              Last checked: {lastChecked.toLocaleTimeString()}
            </Typography>
          )}
          <Tooltip title="Refresh now">
            <span>
              <IconButton size="small" onClick={checkAll} disabled={checking}>
                {checking ? <CircularProgress size={16} /> : <RefreshIcon fontSize="small" />}
              </IconButton>
            </span>
          </Tooltip>
        </Box>
      </Box>

      {/* ── Summary cards ─────────────────────────────────────────────────── */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={3}>
          <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
            <Typography variant="h4" fontWeight={700}>
              {totalCount > 0 ? `${healthyCount}/${totalCount}` : '—'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Services healthy
            </Typography>
          </Paper>
        </Grid>
        {serverStats?.cpu !== undefined && (
          <Grid item xs={12} sm={6} md={3}>
            <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
              <Typography variant="h4" fontWeight={700}>
                {serverStats.cpu.toFixed(0)}%
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Server CPU
              </Typography>
            </Paper>
          </Grid>
        )}
        {serverStats?.ram !== undefined && (
          <Grid item xs={12} sm={6} md={3}>
            <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
              <Typography variant="h4" fontWeight={700}>
                {serverStats.ram.toFixed(0)}%
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Server RAM
              </Typography>
            </Paper>
          </Grid>
        )}
        {serverStats?.disk !== undefined && (
          <Grid item xs={12} sm={6} md={3}>
            <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
              <Typography variant="h4" fontWeight={700}>
                {serverStats.disk.toFixed(0)}%
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Server Disk
              </Typography>
            </Paper>
          </Grid>
        )}
      </Grid>

      {/* ── Server VM (192.168.0.103) ──────────────────────────────────────── */}
      {/* "Server API" (systemd vpt-server) is authoritative; the old core
          HTTP probe row was a flaky duplicate of the same process. */}
      <AccordionSection
        title="Server VM"
        subtitle="192.168.0.103 · vpt-server · :5109"
        services={systemdServices}
        onViewLogs={openLogs}
        defaultExpanded
      />

      {/* ── Frontend VM (192.168.0.105) ────────────────────────────────────── */}
      <AccordionSection
        title="Frontend VM"
        subtitle="192.168.0.105 · vpt-frontend · :3000"
        services={coreServices.filter((s) => s.id === 'frontend')}
        onViewLogs={openLogs}
        defaultExpanded
      />

      {/* ── Proxy VM (192.168.0.107) ───────────────────────────────────────── */}
      <AccordionSection
        title="Proxy VM"
        subtitle="192.168.0.107 · nginx · :443"
        services={coreServices.filter((s) => s.id === 'nginx')}
        onViewLogs={openLogs}
        defaultExpanded
      />

      {/* ── Database VM (192.168.0.102) ────────────────────────────────────── */}
      <AccordionSection
        title="Database VM"
        subtitle="192.168.0.102 · Supabase / PostgreSQL"
        services={coreServices.filter((s) => s.id === 'supabase')}
        onViewLogs={openLogs}
        defaultExpanded
      />

      {/* ── Storage VM (192.168.0.101) ─────────────────────────────────────── */}
      <AccordionSection
        title="Storage VM"
        subtitle="192.168.0.101 · MinIO · Redis · DB Backup"
        services={coreServices.filter((s) => ['minio', 'redis', 'db-backup'].includes(s.id))}
        onViewLogs={openLogs}
        defaultExpanded
      />

      {/* ── CI Runners (VMs 163/164/165) ──────────────────────────────────── */}
      {runnerServices.length > 0 && (
        <AccordionSection
          title="CI Runners"
          subtitle=".100/.164/.165 · VMs 163/164/165 · GitHub Actions self-hosted"
          services={runnerServices}
          onViewLogs={openLogs}
          defaultExpanded
        />
      )}

      {/* ── One accordion per connected host VM ───────────────────────────── */}
      {hostGroups.map((group) => (
        <AccordionSection
          key={group.label}
          title={`Host: ${group.label}`}
          subtitle={group.subtitle}
          services={group.services}
          onViewLogs={openLogs}
        />
      ))}

      {/* ── Logs modal ────────────────────────────────────────────────────── */}
      <ServiceLogsModal
        open={logsState.open}
        serviceLabel={logsState.serviceLabel}
        logService={logsState.logService}
        logHostName={logsState.logHostName}
        onClose={() => setLogsState((prev) => ({ ...prev, open: false }))}
      />
    </Box>
  );
};

export default Status;
