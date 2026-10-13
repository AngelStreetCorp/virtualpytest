import React, { useState, useEffect, useCallback, useRef } from 'react';
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
  Skeleton,
} from '@mui/material';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { PAGE_TITLE_SX, pageSurfaceSx } from '../components/common/PageChrome';
import { ExpandMore as ExpandMoreIcon } from '@mui/icons-material';

import { ServiceLogsModal } from '../components/common/ServiceLogsModal';
import { buildServerUrl, buildPrimaryServerUrl } from '../utils/buildUrlUtils';
import { useServerManager } from '../hooks/useServerManager';
import { getCached, setCached } from '../utils/pageCache';
import { useI18n } from '../i18n/useI18n';

// ─── Types ────────────────────────────────────────────────────────────────────

// 'stopped' and 'not_installed' are known, neutral states for optional units;
// 'unknown' means the probe could not determine the unit state.
type ServiceStatus = 'ok' | 'degraded' | 'error' | 'stopped' | 'not_installed' | 'unknown' | 'loading';

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

// A host whose CPU, RAM or disk usage is above this is flagged as an error.
const RESOURCE_ERROR_PERCENT = 90;

const resourcesRow = (id: string, metrics: { name: string; value?: number }[]): ServiceInfo | null => {
  const known = metrics.filter((m): m is { name: string; value: number } => m.value !== undefined);
  if (known.length === 0) return null;
  const overloaded = known.filter((m) => m.value > RESOURCE_ERROR_PERCENT);
  return {
    id,
    label: 'Resources',
    status: overloaded.length > 0 ? 'error' : 'ok',
    detail: overloaded.length > 0
      ? `${overloaded.map((m) => m.name).join(', ')} over ${RESOURCE_ERROR_PERCENT}%`
      : `all under ${RESOURCE_ERROR_PERCENT}%`,
    extra: known.map((m) => `${m.name} ${m.value.toFixed(0)}%`).join(' · '),
  };
};

const StatTile: React.FC<{ label: string; value: number }> = ({ label, value }) => {
  const over = value > RESOURCE_ERROR_PERCENT;
  return (
    <Grid item xs={12} sm={6} md={3}>
      <Paper variant="outlined" sx={{ p: 2, textAlign: 'center', borderColor: over ? 'error.main' : undefined }}>
        <Typography sx={{ fontSize: '1.5rem', fontWeight: 600 }} color={over ? 'error.main' : undefined}>
          {value.toFixed(0)}%
        </Typography>
        <Typography variant="caption" color={over ? 'error.main' : 'text.secondary'}>
          {label}
        </Typography>
      </Paper>
    </Grid>
  );
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

const statusColor = (s: ServiceStatus): 'success' | 'warning' | 'error' | 'default' => {
  if (s === 'ok') return 'success';
  if (s === 'degraded') return 'warning';
  if (s === 'error') return 'error';
  return 'default';
};

const StatusDot: React.FC<{ status: ServiceStatus; size?: number }> = ({ status, size = 14 }) => {
  const P = useAgentChatPalette();
  const color = {
    ok: P.success,
    degraded: P.warning,
    error: P.error,
    stopped: P.textMuted, // palette: known-off, distinct from unknown
    not_installed: P.textMuted,
    unknown: P.textMuted,
    loading: P.textMuted,
  }[status];
  return (
    <DotIcon sx={{ fontSize: size, color, flexShrink: 0 }} />
  );
};


const overallStatus = (services: ServiceInfo[]): ServiceStatus => {
  if (services.some((s) => s.status === 'error')) return 'error';
  if (services.some((s) => s.status === 'degraded' || s.status === 'unknown')) return 'degraded';
  // Stopped optional services and optional units that aren't installed are
  // expected states; only active services count toward the section ratio.
  if (services.every((s) => s.status === 'ok' || s.status === 'stopped' || s.status === 'not_installed')) return 'ok';
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
        label={service.status === 'loading' ? 'checking…' : service.status === 'not_installed' ? 'not installed' : service.status}
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
  subtitleError?: boolean;
  services: ServiceInfo[];
  onViewLogs: (s: ServiceInfo) => void;
  /** Stable id used by the summary block above to scroll to / open this section. */
  sectionId: string;
  expanded: boolean;
  onToggle: (open: boolean) => void;
  /** Ref callback the parent collects for scrollIntoView. */
  sectionRef?: (el: HTMLDivElement | null) => void;
}> = ({ title, subtitle, subtitleError, services, onViewLogs, sectionId, expanded, onToggle, sectionRef }) => {
  const overall = overallStatus(services.filter((s) => s.status !== 'loading'));
  const okCount = services.filter((s) => s.status === 'ok').length;
  const total = services.filter((s) => s.status !== 'loading' && s.status !== 'not_installed').length;

  return (
    <Box ref={sectionRef} data-section-id={sectionId} sx={{ scrollMarginTop: 16 }}>
      <Accordion
        sx={accordionSx}
        expanded={expanded}
        onChange={(_e, isOpen) => onToggle(isOpen)}
      >
      <AccordionSummary
        expandIcon={<ExpandMoreIcon />}
        sx={{ minHeight: 40, '& .MuiAccordionSummary-content': { margin: '6px 0', alignItems: 'center', gap: 1 } }}
      >
        <StatusDot status={overall} size={10} />
        <Typography variant="subtitle2" sx={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: '0.72rem' }}>
          {title}
        </Typography>
        {subtitle && (
          <Typography variant="caption" color={subtitleError ? 'error.main' : 'text.secondary'} sx={{ fontFamily: 'monospace' }}>
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
    </Box>
  );
};

interface HostStats {
  cpu_percent?: number;
  memory_percent?: number;
  disk_percent?: number;
  load_average_1m?: number;
}

// ─── VM Summary Block ─────────────────────────────────────────────────────────

// One row in the at-a-glance summary that sits above the accordions. Each
// machine the page already shows (server, frontend, proxy, database, storage,
// every connected host) gets one. Rows with no metric data (frontend / proxy /
// database / storage) still appear with a status dot so the user can see
// "everything is up" without expanding anything.
type SummaryStatus = 'ok' | 'warn' | 'down' | 'unknown';

interface SummaryRow {
  id: string;
  name: string;
  status: SummaryStatus;
  cpu?: number;     // %
  load1?: number;   // 1-min load average
  ram?: number;     // %
  disk?: number;    // %
}

const STATUS_RANK: Record<SummaryStatus, number> = { ok: 0, unknown: 1, warn: 2, down: 3 };

/** Combine multiple statuses — the worst one wins. */
const worstStatus = (...s: SummaryStatus[]): SummaryStatus =>
  s.reduce((acc, cur) => (STATUS_RANK[cur] > STATUS_RANK[acc] ? cur : acc), 'ok' as SummaryStatus);

/** Map a service-level status to the summary's 4-state scheme. */
const serviceToSummary = (s: ServiceStatus | undefined): SummaryStatus => {
  if (s === 'ok') return 'ok';
  if (s === 'error') return 'down';
  if (s === 'degraded' || s === 'unknown' || s === 'loading') return 'warn';
  // stopped / not_installed are healthy on optional units; treat as unknown here.
  return 'unknown';
};

/** Threshold a single metric to the 4-state scheme. Undefined → 'ok': a missing
 *  value is shown as '—' and must not downgrade an otherwise healthy machine. */
const metricToStatus = (v: number | undefined): SummaryStatus => {
  if (v === undefined) return 'ok';
  if (v >= 90) return 'down';
  if (v >= 80) return 'warn';
  return 'ok';
};

// Fixed pixel widths for the metric cells — same in dark and light, and on
// every refresh, so a 45% and a — never shift the columns.
const COL_DOT = 24;
const COL_NAME_MD = 200;
const COL_CPU = 56;
const COL_LOAD = 64;
const COL_RAM = 56;
const COL_DISK = 56;
// header row layout: dot + (label / value). The MetricCell width includes its suffix.
const METRIC_FONT = '0.85rem';
const METRIC_GAP = 12;
const COL_GROUP = COL_CPU + COL_LOAD + COL_RAM + COL_DISK + 3 * METRIC_GAP;

const SummaryDot: React.FC<{ status: SummaryStatus; size?: number }> = ({ status, size = 12 }) => {
  const P = useAgentChatPalette();
  const color =
    status === 'ok' ? P.success
    : status === 'warn' ? P.warning
    : status === 'down' ? P.error
    : P.textMuted;
  return <DotIcon sx={{ fontSize: size, color, flexShrink: 0 }} />;
};

/** A single metric cell. Fixed width; tabular-nums keeps digits from jumping
 *  when the value changes. Missing values show '—', never 0. */
const MetricCell: React.FC<{
  value: number | undefined;
  status: SummaryStatus;
  width: number;
  /** Tooltip explaining the metric (English key, translated at render). */
  label: string;
  /** 'pct' shows integers with a % suffix; 'load' shows two decimals, no suffix. */
  format: 'pct' | 'load';
}> = ({ value, status, width, label, format }) => {
  const P = useAgentChatPalette();
  // Missing values show '—', never 0 (per brief). The block itself renders
  // a skeleton during the very first load before any data arrives — by the
  // time we get here the row has either a real number or '—' for fields
  // the data source didn't carry (e.g. frontend/proxy/database/storage
  // don't have CPU, so those cells render '—' forever).
  const text =
    value === undefined ? '—'
    : format === 'load' ? value.toFixed(2)
    : `${Math.round(value)}%`;
  const color =
    value === undefined ? P.textMuted
    : status === 'down' ? P.error
    : status === 'warn' ? P.warning
    : P.textPrimary;
  return (
    <Tooltip title={label}>
      <Box
        sx={{
          width: { xs: 'auto', md: width },
          flex: { xs: 1, md: 'none' },
          minWidth: 0,
          flexShrink: 0,
          display: 'flex',
          flexDirection: { xs: 'column', md: 'row' },
          alignItems: { xs: 'flex-start', md: 'center' },
          justifyContent: 'flex-end',
        }}
      >
        {/* Phones have no column header: caption each value instead. */}
        <Typography
          sx={{
            display: { xs: 'block', md: 'none' },
            fontSize: '0.65rem',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: P.textMuted,
            lineHeight: 1.2,
          }}
        >
          {label}
        </Typography>
        <Box
          sx={{
            width: { xs: 'auto', md: '100%' },
            textAlign: { xs: 'left', md: 'right' },
            fontVariantNumeric: 'tabular-nums',
            fontSize: METRIC_FONT,
            fontWeight: 500,
            color,
            // Reserve the line height even when the value is missing, so a
            // refreshing block doesn't jitter between refreshes.
            minHeight: '1.25rem',
          }}
        >
          {text}
        </Box>
      </Box>
    </Tooltip>
  );
};

const StatusSummaryBlock: React.FC<{
  rows: SummaryRow[];
  /** True when initial load has not finished yet — show a full skeleton. */
  loading: boolean;
  onJump: (id: string) => void;
}> = ({ rows, loading, onJump }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();

  // Header — hidden on phones (the row title carries enough info there).
  const HeaderLabel: React.FC<{ children: React.ReactNode; width: number; align?: 'left' | 'right' }> = ({
    children, width, align = 'left',
  }) => (
    <Typography
      sx={{
        width,
        flexShrink: 0,
        textAlign: align,
        fontSize: '0.7rem',
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
        color: P.textMuted,
        display: { xs: 'none', md: 'block' },
      }}
    >
      {children}
    </Typography>
  );

  // Skeleton for the very first render — same height as real rows so the
  // block doesn't pop in once data arrives. 5 placeholder rows matches the
  // five core VMs the page always shows (server / frontend / proxy /
  // database / storage). Host rows come on top of that.
  if (loading) {
    return (
      <Box sx={{
        border: `1px solid ${P.borderColor}`,
        borderRadius: 2,
        bgcolor: P.surface,
        overflow: 'hidden',
        mb: 2,
      }}>
        {[0, 1, 2, 3, 4].map((i) => (
          <Box
            key={i}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1.5,
              px: 1.5, py: 0.875,
              borderBottom: i === 4 ? 'none' : `1px solid ${P.borderColor}`,
            }}
          >
            <Skeleton variant="circular" width={12} height={12} sx={{ width: COL_DOT }} />
            <Skeleton width={140} height={16} />
            <Box sx={{ flex: 1, display: 'flex', justifyContent: 'flex-end', gap: 2 }}>
              <Skeleton width={COL_CPU - 16} height={16} />
              <Skeleton width={COL_LOAD - 16} height={16} />
              <Skeleton width={COL_RAM - 16} height={16} />
              <Skeleton width={COL_DISK - 16} height={16} />
            </Box>
          </Box>
        ))}
      </Box>
    );
  }

  if (rows.length === 0) return null;

  return (
    <Box sx={{
      border: `1px solid ${P.borderColor}`,
      borderRadius: 2,
      bgcolor: P.surface,
      overflow: 'hidden',
      mb: 2,
    }}>
      {/* Header — visible only at md+. Mobile users get a vertical card layout
          and the header would just duplicate what each row already says. */}
      <Box sx={{
        display: { xs: 'none', md: 'flex' },
        alignItems: 'center',
        gap: 1.5,
        px: 1.5, py: 0.75,
        bgcolor: P.hoverBg,
        borderBottom: `1px solid ${P.borderColor}`,
      }}>
        <Box sx={{ width: COL_DOT, flexShrink: 0 }} />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <HeaderLabel width={COL_NAME_MD}>{t('Machine')}</HeaderLabel>
        </Box>
        <Box sx={{ width: COL_GROUP, flexShrink: 0, display: 'flex', gap: `${METRIC_GAP}px` }}>
          <HeaderLabel width={COL_CPU} align="right">{t('CPU')}</HeaderLabel>
          <HeaderLabel width={COL_LOAD} align="right">{t('Load')}</HeaderLabel>
          <HeaderLabel width={COL_RAM} align="right">{t('RAM')}</HeaderLabel>
          <HeaderLabel width={COL_DISK} align="right">{t('Disk')}</HeaderLabel>
        </Box>
      </Box>

      {/* Rows */}
      <Box role="list">
        {rows.map((row, i) => {
          const cpuStatus = metricToStatus(row.cpu);
          const ramStatus = metricToStatus(row.ram);
          const diskStatus = metricToStatus(row.disk);
          // Load (1m): we don't know core counts, so we can't compare against
          // them. Stay neutral on load — the metric is informational only.
          const loadStatus: SummaryStatus = 'ok';
          return (
            <Box
              key={row.id}
              role="listitem"
              tabIndex={0}
              onClick={() => onJump(row.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onJump(row.id);
                }
              }}
              aria-label={`${row.name} — ${row.status}`}
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1.5,
                flexWrap: 'wrap',
                px: 1.5, py: 0.875,
                borderBottom: i === rows.length - 1 ? 'none' : `1px solid ${P.borderColor}`,
                cursor: 'pointer',
                outline: 'none',
                transition: 'background-color 0.15s',
                '&:hover': { bgcolor: P.hoverBg },
                '&:focus-visible': { boxShadow: `inset 0 0 0 2px ${P.accent}` },
              }}
            >
              {/* Dot — fixed width, never shrinks */}
              <Box sx={{ width: COL_DOT, flexShrink: 0, display: 'flex', alignItems: 'center' }}>
                <SummaryDot status={row.status} />
              </Box>

              {/* Name — fixed width at md+, full row minus dot at xs. */}
              <Typography
                sx={{
                  width: { xs: 'calc(100% - 36px)', md: 'auto' },
                  flex: { xs: 'none', md: 1 },
                  minWidth: 0,
                  fontSize: '0.85rem',
                  fontWeight: 500,
                  color: P.textPrimary,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {row.name}
              </Typography>

              {/* Metric group — wraps below the name on phones. `flex: 1`
                  + the name's explicit width makes the container wrap to a
                  new flex line at xs, where the name fills the row. */}
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: `${METRIC_GAP}px`,
                  width: { xs: 'calc(100% - 36px)', md: COL_GROUP },
                  ml: { xs: '36px', md: 0 },
                  flexShrink: 0,
                }}
              >
                <MetricCell value={row.cpu} status={cpuStatus} width={COL_CPU} format="pct" label={t('CPU')} />
                <MetricCell value={row.load1} status={loadStatus} width={COL_LOAD} format="load" label={t('Load')} />
                <MetricCell value={row.ram} status={ramStatus} width={COL_RAM} format="pct" label={t('RAM')} />
                <MetricCell value={row.disk} status={diskStatus} width={COL_DISK} format="pct" label={t('Disk')} />
              </Box>
            </Box>
          );
        })}
      </Box>
    </Box>
  );
};

// ─── Main Page ────────────────────────────────────────────────────────────────

const Status: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { serverHostsData } = useServerManager();

  // Track which accordion sections are open. Clicking a summary row below
  // opens the matching section and scrolls to it — this Set holds the
  // section IDs the user has chosen to expand.
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set());
  const toggleSection = useCallback((id: string, open: boolean) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (open) next.add(id); else next.delete(id);
      return next;
    });
  }, []);
  const sectionRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const jumpToSection = useCallback((id: string) => {
    setExpandedSections((prev) => {
      if (prev.has(id)) return prev;
      const next = new Set(prev);
      next.add(id);
      return next;
    });
    // Defer the scroll one tick so the accordion has a chance to render
    // expanded before we try to align it with the viewport.
    requestAnimationFrame(() => {
      const el = sectionRefs.current[id];
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }, []);

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
  // Per-host status + resource stats from the getAllHosts?include_system_stats=true call this
  // page already makes (checkServerServices). The shared host context only carries stats when
  // another page asked for them, so the summary reads the page's own fetch.
  const [hostLive, setHostLive] = useState<Record<string, { status?: string; system_stats?: HostStats }>>({});
  const [hostGroups, setHostGroups] = useState<{ label: string; subtitle: string; subtitleError: boolean; services: ServiceInfo[] }[]>([]);
  const [runnerServices, setRunnerServices] = useState<ServiceInfo[]>([]);

  // Live CPU/RAM/disk/load per infra VM (frontend, proxy, database, storage,
  // …), keyed by the vm_metrics.vm name. Comes from GET /server/system/vmMetrics
  // which reads the latest row per VM the collector wrote (TASK-60 goal 4).
  // Empty object until the first response lands — summary cells render '—'.
  const [vmMetrics, setVmMetrics] = useState<Record<string, HostStats>>({});

  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [checking, setChecking] = useState(false);
  const checkingRef = React.useRef(false);
  const [serverStats, setServerStats] = useState<{ cpu?: number; ram?: number; disk?: number; load?: number; uptime?: string } | null>(() => getCached('status-stats'));

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
              load: ss.load_average_1m,
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
          if (Array.isArray(d.hosts)) {
            const live: Record<string, { status?: string; system_stats?: HostStats }> = {};
            for (const h of d.hosts) live[h.host_name] = { status: h.status, system_stats: h.system_stats };
            setHostLive(live);
          }
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

    // ── 6. VM metrics (frontend / proxy / database / storage / …) ─────────
    // The infra VMs have no in-browser probe — their CPU/RAM/disk comes from
    // the VM agent (infra/vm_agent), pulled by the backend server's collector
    // every 5 minutes into vm_metrics. Read the latest row per VM and feed
    // the summary block's "no number yet" cells.
    const checkVmMetrics = async () => {
      try {
        const res = await fetch(buildServerUrl('/server/system/vmMetrics'), { signal: AbortSignal.timeout(8000) });
        if (res.ok) {
          const d = await res.json();
          if (d && typeof d.metrics === 'object' && d.metrics !== null) {
            const mapped: Record<string, HostStats> = {};
            for (const [vm, row] of Object.entries(d.metrics as Record<string, HostStats>)) {
              mapped[vm] = row;
            }
            setVmMetrics(mapped);
          }
        }
      } catch {
        // Endpoint down or table empty — leave the previous value (no cache
        // for vm_metrics; the next successful check self-corrects).
      }
    };

    await Promise.all([checkServer(), checkDbBackup(), checkStorage(), checkServerServices(), checkRunners(), checkVmMetrics()]);

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
        const disk = host.system_stats?.disk_percent;
        const resources = resourcesRow(`host-${host.host_name}-resources`, [
          { name: 'CPU', value: cpu },
          { name: 'RAM', value: ram },
          { name: 'Disk', value: disk },
        ]);
        const extra = resources?.extra ?? '';

        const hostServiceHealth = host.system_stats?.service_health?.services || [];
        const services: ServiceInfo[] = hostServiceHealth.map((svc: { label: string; name: string; resolved_name?: string; status: string; optional?: boolean }) => ({
          id: `host-${host.host_name}-${svc.name}`,
          label: svc.label,
          logService: svc.resolved_name || svc.name,
          logHostName: host.host_name,
          status: svc.status === 'active' ? 'ok' as ServiceStatus
            : (svc.status === 'stopped' || svc.status === 'inactive') ? (svc.optional ? 'stopped' as ServiceStatus : 'degraded' as ServiceStatus)
            : svc.status === 'not_installed' ? (svc.optional ? 'not_installed' as ServiceStatus : 'degraded' as ServiceStatus)
            : (svc.status === 'stuck' || svc.status === 'error') ? 'error' as ServiceStatus
            : svc.status === 'unknown' ? 'unknown' as ServiceStatus
            : 'degraded' as ServiceStatus,
          detail: svc.status === 'not_installed' && svc.optional ? 'optional service' : svc.status,
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

        if (resources) services.push(resources);

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
          subtitleError: resources?.status === 'error',
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
  const serverResources = resourcesRow('server-resources', [
    { name: 'CPU', value: serverStats?.cpu },
    { name: 'RAM', value: serverStats?.ram },
    { name: 'Disk', value: serverStats?.disk },
  ]);
  const serverVmServices = serverResources ? [...systemdServices, serverResources] : systemdServices;
  const allServices = [...coreServices, ...serverVmServices, ...hostGroups.flatMap(g => g.services), ...runnerServices];
  const overall = overallStatus(allServices.filter((s) => s.status !== 'loading'));
  const healthyCount = allServices.filter((s) => s.status === 'ok').length;
  const totalCount = allServices.filter((s) => s.status !== 'loading' && s.status !== 'not_installed').length;

  // ── At-a-glance summary rows ────────────────────────────────────────────────
  // One row per machine the page shows. All values come from data the page
  // already loads (serverStats, coreServices, hostGroups) — no new endpoints.
  const frontendSvc = coreServices.find((s) => s.id === 'frontend');
  const proxySvc = coreServices.find((s) => s.id === 'nginx');
  const dbSvc = coreServices.find((s) => s.id === 'supabase');
  const storageServices = coreServices.filter((s) => ['minio', 'redis', 'db-backup'].includes(s.id));
  const serverSummaryStatus = worstStatus(
    serviceToSummary(serverResources?.status),
    metricToStatus(serverStats?.cpu),
    metricToStatus(serverStats?.ram),
    metricToStatus(serverStats?.disk),
  );
  const storageSummaryStatus = worstStatus(...storageServices.map((s) => serviceToSummary(s.status)));

  const summaryRows: SummaryRow[] = [
    {
      id: 'server',
      name: t('Server VM'),
      status: serverSummaryStatus,
      cpu: serverStats?.cpu,
      load1: serverStats?.load,
      ram: serverStats?.ram,
      disk: serverStats?.disk,
    },
    {
      id: 'frontend',
      name: t('Frontend VM'),
      // Combine the service-level status with the VM metric thresholds
      // (vm_metrics for `frontend`). A row with no metrics yet still shows
      // its service dot — only the cells stay '—'.
      status: worstStatus(
        serviceToSummary(frontendSvc?.status),
        metricToStatus(vmMetrics['frontend']?.cpu_percent),
        metricToStatus(vmMetrics['frontend']?.memory_percent),
        metricToStatus(vmMetrics['frontend']?.disk_percent),
      ),
      cpu: vmMetrics['frontend']?.cpu_percent,
      load1: vmMetrics['frontend']?.load_average_1m,
      ram: vmMetrics['frontend']?.memory_percent,
      disk: vmMetrics['frontend']?.disk_percent,
    },
    {
      id: 'proxy',
      name: t('Proxy VM'),
      status: worstStatus(
        serviceToSummary(proxySvc?.status),
        metricToStatus(vmMetrics['proxy']?.cpu_percent),
        metricToStatus(vmMetrics['proxy']?.memory_percent),
        metricToStatus(vmMetrics['proxy']?.disk_percent),
      ),
      cpu: vmMetrics['proxy']?.cpu_percent,
      load1: vmMetrics['proxy']?.load_average_1m,
      ram: vmMetrics['proxy']?.memory_percent,
      disk: vmMetrics['proxy']?.disk_percent,
    },
    {
      id: 'database',
      name: t('Database VM'),
      status: worstStatus(
        serviceToSummary(dbSvc?.status),
        metricToStatus(vmMetrics['database']?.cpu_percent),
        metricToStatus(vmMetrics['database']?.memory_percent),
        metricToStatus(vmMetrics['database']?.disk_percent),
      ),
      cpu: vmMetrics['database']?.cpu_percent,
      load1: vmMetrics['database']?.load_average_1m,
      ram: vmMetrics['database']?.memory_percent,
      disk: vmMetrics['database']?.disk_percent,
    },
    {
      id: 'storage',
      name: t('Storage VM'),
      status: worstStatus(
        storageSummaryStatus,
        metricToStatus(vmMetrics['storage']?.cpu_percent),
        metricToStatus(vmMetrics['storage']?.memory_percent),
        metricToStatus(vmMetrics['storage']?.disk_percent),
      ),
      cpu: vmMetrics['storage']?.cpu_percent,
      load1: vmMetrics['storage']?.load_average_1m,
      ram: vmMetrics['storage']?.memory_percent,
      disk: vmMetrics['storage']?.disk_percent,
    },
    ...hostGroups.map<SummaryRow>((g) => {
      // Metrics come from the page's own getAllHosts?include_system_stats=true call
      // (hostLive); the shared host context is only a fallback.
      const hostRecord = serverHostsData
        .flatMap((sd) => sd.hosts)
        .find((h) => h.host_name === g.label);
      const live = hostLive[g.label];
      const ss: HostStats | undefined = live?.system_stats ?? hostRecord?.system_stats;
      const hostStatus = live?.status ?? hostRecord?.status;
      return {
        id: `host-${g.label}`,
        name: t('Host: {name}', { name: g.label }),
        status: worstStatus(
          // host record status
          (hostStatus === 'online' ? 'ok'
            : hostStatus === 'offline' ? 'down'
            : 'unknown') as SummaryStatus,
          // resource metrics
          metricToStatus(ss?.cpu_percent),
          metricToStatus(ss?.memory_percent),
          metricToStatus(ss?.disk_percent),
        ),
        cpu: ss?.cpu_percent,
        load1: ss?.load_average_1m,
        ram: ss?.memory_percent,
        disk: ss?.disk_percent,
      };
    }),
  ];

  // Skeleton on the very first render — `lastChecked` flips to a Date after
  // the first checkAll() resolves. While null, the block shows skeletons.
  const summaryLoading = lastChecked === null;

  return (
    <Box sx={pageSurfaceSx(P)}>
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <Box display="flex" alignItems="center" justifyContent="space-between" mb={2}>
        <Box display="flex" alignItems="center" gap={1}>
          <StatusDot status={overall} size={12} />
          <Typography component="h1" sx={PAGE_TITLE_SX}>
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
            <Typography sx={{ fontSize: '1.5rem', fontWeight: 600 }}>
              {totalCount > 0 ? `${healthyCount}/${totalCount}` : '—'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Services healthy
            </Typography>
          </Paper>
        </Grid>
        {serverStats?.cpu !== undefined && <StatTile label="Server CPU" value={serverStats.cpu} />}
        {serverStats?.ram !== undefined && <StatTile label="Server RAM" value={serverStats.ram} />}
        {serverStats?.disk !== undefined && <StatTile label="Server Disk" value={serverStats.disk} />}
      </Grid>

      {/* ── At-a-glance VM summary ─────────────────────────────────────────── */}
      <StatusSummaryBlock rows={summaryRows} loading={summaryLoading} onJump={jumpToSection} />

      {/* ── Server VM (192.168.x.103) ──────────────────────────────────────── */}
      {/* "Server API" (systemd vpt-server) is authoritative; the old core
          HTTP probe row was a flaky duplicate of the same process. */}
      <AccordionSection
        sectionId="server"
        expanded={expandedSections.has('server')}
        onToggle={(open) => toggleSection('server', open)}
        sectionRef={(el) => { sectionRefs.current['server'] = el; }}
        title={t('Server VM')}
        subtitle="192.168.x.103 · vpt-server · :5109"
        subtitleError={serverResources?.status === 'error'}
        services={serverVmServices}
        onViewLogs={openLogs}
      />

      {/* ── Frontend VM (192.168.x.105) ────────────────────────────────────── */}
      <AccordionSection
        sectionId="frontend"
        expanded={expandedSections.has('frontend')}
        onToggle={(open) => toggleSection('frontend', open)}
        sectionRef={(el) => { sectionRefs.current['frontend'] = el; }}
        title={t('Frontend VM')}
        subtitle="192.168.x.105 · vpt-frontend · :3000"
        services={coreServices.filter((s) => s.id === 'frontend')}
        onViewLogs={openLogs}
      />

      {/* ── Proxy VM (192.168.x.107) ───────────────────────────────────────── */}
      <AccordionSection
        sectionId="proxy"
        expanded={expandedSections.has('proxy')}
        onToggle={(open) => toggleSection('proxy', open)}
        sectionRef={(el) => { sectionRefs.current['proxy'] = el; }}
        title={t('Proxy VM')}
        subtitle="192.168.x.107 · nginx · :443"
        services={coreServices.filter((s) => s.id === 'nginx')}
        onViewLogs={openLogs}
      />

      {/* ── Database VM (192.168.x.102) ────────────────────────────────────── */}
      <AccordionSection
        sectionId="database"
        expanded={expandedSections.has('database')}
        onToggle={(open) => toggleSection('database', open)}
        sectionRef={(el) => { sectionRefs.current['database'] = el; }}
        title={t('Database VM')}
        subtitle="192.168.x.102 · Supabase / PostgreSQL"
        services={coreServices.filter((s) => s.id === 'supabase')}
        onViewLogs={openLogs}
      />

      {/* ── Storage VM (192.168.x.101) ─────────────────────────────────────── */}
      <AccordionSection
        sectionId="storage"
        expanded={expandedSections.has('storage')}
        onToggle={(open) => toggleSection('storage', open)}
        sectionRef={(el) => { sectionRefs.current['storage'] = el; }}
        title={t('Storage VM')}
        subtitle="192.168.x.101 · MinIO · Redis · DB Backup"
        services={coreServices.filter((s) => ['minio', 'redis', 'db-backup'].includes(s.id))}
        onViewLogs={openLogs}
      />

      {/* ── CI Runners (VMs 163/164/165) ──────────────────────────────────── */}
      {runnerServices.length > 0 && (
        <AccordionSection
          sectionId="runners"
          expanded={expandedSections.has('runners')}
          onToggle={(open) => toggleSection('runners', open)}
          sectionRef={(el) => { sectionRefs.current['runners'] = el; }}
          title={t('CI Runners')}
          subtitle=".100/.164/.165 · VMs 163/164/165 · GitHub Actions self-hosted"
          services={runnerServices}
          onViewLogs={openLogs}
        />
      )}

      {/* ── One accordion per connected host VM ───────────────────────────── */}
      {hostGroups.map((group) => (
        <AccordionSection
          key={group.label}
          sectionId={`host-${group.label}`}
          expanded={expandedSections.has(`host-${group.label}`)}
          onToggle={(open) => toggleSection(`host-${group.label}`, open)}
          sectionRef={(el) => { sectionRefs.current[`host-${group.label}`] = el; }}
          title={t('Host: {name}', { name: group.label })}
          subtitle={group.subtitle}
          subtitleError={group.subtitleError}
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
