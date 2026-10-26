import {
  CheckCircle as PassIcon,
  Error as FailIcon,
  HourglassEmpty as RunningIcon,
  Block as AbortedIcon,
  DescriptionOutlined as ReportFileIcon,
  Terminal as LogsIcon,
  Person as ManualIcon,
  Help as UnknownIcon,
  Comment as CommentIcon,
  Visibility as DetailsIcon,
  VisibilityOff as HideDetailsIcon,
  CheckCircle as CheckedIcon,
  RemoveCircleOutline as SkippedIcon,
  OpenInNew,
  ViewColumn as ViewColumnIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  PlayArrow as ScriptIcon,
  RestartAlt as RerunIcon,
  InfoOutlined as InfoIcon,
  Share as ShareIcon,
  Summarize as SummaryIcon,
} from '@mui/icons-material';
import {
  Autocomplete,
  Box,
  Typography,
  Card,
  CardContent,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  CircularProgress,
  Alert,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Tooltip,
  IconButton,
  FormControlLabel,
  Popover,
  Checkbox,
  Chip,
  Collapse,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import React, { useState, useEffect, useMemo, useCallback, useRef, startTransition } from 'react';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';

import { AIIcon as AiIcon } from '../components/common/icons/CustomIcons';
import { useScriptResults, ScriptResult, ScriptResultFilters } from '../hooks/pages/useScriptResults';
import { useCampaignResults, CampaignResult } from '../hooks/pages/useCampaignResults';
import { useResizableColumns } from '../hooks/useResizableColumns';
import { useHostData } from '../hooks/useHostManager';
import { useServerManager } from '../hooks/useServerManager';
import { useWorkspaceContext } from '../contexts/workspace/WorkspaceContext';
import { formatToLocalTime } from '../utils/dateUtils';
import { openR2Url } from '../utils/infrastructure/cloudflareUtils';
import JevWhy, { analysisTypeLabel, getJev } from '../components/common/JevWhy';
import { StyledDialog } from '../components/common/StyledDialog';
import { formatScriptLabel, ensureScriptIdentityMap, buildRerunPayloadFromResult } from '../utils/executionUtils';
import { getResultOutcome, isSkippedResult, type ResultOutcome } from '../utils/resultOutcome';
import { useRerun } from '../hooks/script/useRerun';
import { useToast } from '../hooks/useToast';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { neutralButtonSx } from '../components/common/PageChrome';
import { TableRowsSkeleton, ValueSkeleton } from '../components/common/ReportSkeleton';
import { useReportSnapshots, type ReportSnapshotConfig } from '../hooks/useReportSnapshots';
import { ShareReportDialog } from '../components/reports/ShareReportDialog';
import { SharedLinksTab } from '../components/reports/SharedLinksTab';
import { getEnv } from '../config/constants';
import { withGrafanaWorkspace } from '../utils/grafanaUrl';
import { AssignmentDialog } from '../components/reports/AssignmentDialog';
import {
  useLabels,
  useMilestones,
  useQualityQuery,
  useReportPermissions,
  useRunGroups,
} from '../hooks/reports/useRunManagement';
import { QUALITY_DEFAULT_WINDOW, REPORT_ROUTES, type FlakyRow } from '../types/reports';
import { TYPOGRAPHY } from '../constants/typography';

// Target filter options are "<host_name> - <device_name>" so the dropdown
// shows the same identifier RunTests uses for a run target. Helpers below
// build/parse that combined key so the underlying host+device filtering
// can still be applied separately.
const TARGET_KEY_SEP = ' - ';
const buildTargetKey = (hostName: string, deviceName?: string | null) =>
  deviceName ? `${hostName}${TARGET_KEY_SEP}${deviceName}` : hostName;
const parseTargetKey = (key: string): { hostName: string; deviceName: string | null } => {
  const idx = key.indexOf(TARGET_KEY_SEP);
  return idx === -1
    ? { hostName: key, deviceName: null }
    : { hostName: key.slice(0, idx), deviceName: key.slice(idx + TARGET_KEY_SEP.length) };
};
// Display label for a target key. The underlying key is "<host> - <device>",
// and the cell carries the full label as its title, because the column is narrow
// enough to cut it ("Phone slot 1 - ho…").
// Note the device name here is whatever the run recorded. A paired phone records
// its own name ("samsung SM-G998B") rather than the slot label it sits in — see
// _resolved_device_name in controller_manager.py — so older rows can still show a
// slot label while newer ones name the phone.
// but we show the device first ("<device> - <host>"). A host's own implicit
// device is named "<host>_Host"; label it by its device id, "host - <host>",
// so it reads like every other target instead of naming the host twice. The
// underlying key (value) is unchanged so host+device filtering still works.
const formatTargetLabel = (key: string): string => {
  const { hostName, deviceName } = parseTargetKey(key);
  if (!deviceName) return hostName;
  const device = deviceName === `${hostName}_Host` ? 'host' : deviceName;
  return `${device}${TARGET_KEY_SEP}${hostName}`;
};

/** Show prefix + display_name from metadata when available, fall back to identity map. */
function getScriptLabel(result: ScriptResult): string {
  const meta = result.metadata;
  const identity = meta?.script_identity;
  const prefix = identity?.prefix;
  const displayName = identity?.display_name;
  if (prefix && displayName) return `[${prefix}] ${displayName}`;
  if (displayName) return displayName;
  if (prefix) return `[${prefix}] ${result.script_name}`;
  // Fall back to the shared identity map lookup
  return formatScriptLabel(result.script_name);
}

/** Who launched the run — same fields as the report's `Trigger:` line. */
function getTriggerLines(result: ScriptResult): string[] {
  const trigger = result.metadata?.trigger;
  if (!trigger?.type) return [];
  const lines = [`Trigger: ${trigger.type}`];
  if (trigger.caller_user) lines.push(`User: ${trigger.caller_user}`);
  if (trigger.caller_ip) lines.push(`IP: ${trigger.caller_ip}`);
  return lines;
}

/**
 * Key comparing a result row with a flaky-quality identity. Script result rows do not
 * carry `environment`, so the key omits it: a badge marks a row whose script/UI/target
 * is flaky in at least one environment (the tooltip names the environment).
 */
const flakyKey = (
  scriptName: string,
  uiName: string | null | undefined,
  hostName: string | null | undefined,
  deviceName: string | null | undefined,
) => [scriptName, uiName ?? '', hostName ?? '', deviceName ?? ''].join('|');

/** Search params carrying the server-side governance filters. */
const GOVERNANCE_PARAMS = { milestone_id: 'milestone', run_group_id: 'group', label_id: 'label' } as const;

/** Ticks instantly; the (heavy) table re-render for the selection runs as a low-priority update. */
const RowCheckbox: React.FC<{ id: string; label: string; checked: boolean; onToggle: (id: string) => void }> = ({ id, label, checked, onToggle }) => {
  const [local, setLocal] = useState(checked);
  useEffect(() => setLocal(checked), [checked]);
  return (
    <Checkbox
      size="small"
      inputProps={{ 'aria-label': label }}
      checked={local}
      onChange={() => {
        setLocal((v) => !v);
        startTransition(() => onToggle(id));
      }}
    />
  );
};

const TestReports: React.FC = () => {
  const P = useAgentChatPalette();
  // Get Grafana URL from environment variable
  const grafanaUrl = getEnv('VITE_GRAFANA_URL') || 'http://localhost/grafana';

  const { getAllScriptResults, updateCheckedStatus, updateDiscardStatus } = useScriptResults();
  const { getAllCampaignResults } = useCampaignResults();
  const { getAllHosts } = useHostData();
  const { selectedServer } = useServerManager();
  const { isDeviceAllowed, activeWorkspace } = useWorkspaceContext();
  const { rerun, rerunningIds } = useRerun();
  const { showInfo, showSuccess, showError } = useToast();
  const { getConfig: getShareConfig } = useReportSnapshots();
  const [shareConfig, setShareConfig] = useState<ReportSnapshotConfig | null>(null);
  const [shareTarget, setShareTarget] = useState<{ id: string; name: string } | null>(null);
  useEffect(() => {
    getShareConfig().then(setShareConfig).catch(() => setShareConfig(null));
  }, [getShareConfig]);
  const canShare = !!shareConfig?.enabled && !!shareConfig?.can_share;
  const [rawScriptResults, setRawScriptResults] = useState<ScriptResult[]>([]);
  const [rawCampaignResults, setRawCampaignResults] = useState<CampaignResult[]>([]);

  // Resolve a result's (host_name, device_name) to device_id via live host
  // data and apply the workspace's device filter. Results whose device
  // cannot be resolved (e.g. decommissioned device) are kept — we can't
  // verify them, so they remain visible to avoid hiding historical data.
  const isResultAllowed = useMemo(() => {
    if (!activeWorkspace) return (_h: string, _d: string) => true;
    const nameToId = new Map<string, string>();
    for (const host of getAllHosts()) {
      for (const device of host.devices || []) {
        nameToId.set(`${host.host_name}:${device.device_name}`, device.device_id);
      }
    }
    return (hostName: string, deviceName: string) => {
      const deviceId = nameToId.get(`${hostName}:${deviceName}`);
      if (!deviceId) return true; // unresolved — keep visible
      return isDeviceAllowed(hostName, deviceId);
    };
  }, [activeWorkspace, getAllHosts, isDeviceAllowed]);

  // Distinct host names of the active workspace (derived from its device_filter
  // `host:device_id` pairs). Sent to the server so the latest-N row limit is
  // applied per-workspace instead of globally — otherwise a high-frequency
  // workspace starves this one's rows out of the window before isResultAllowed
  // (client-side, device-level) ever runs. Undefined = no workspace = no scope.
  const workspaceHostFilter = useMemo(() => {
    const deviceFilter = activeWorkspace?.device_filter;
    if (!deviceFilter?.length) return undefined;
    return Array.from(new Set(deviceFilter.map((entry) => entry.split(':')[0]).filter(Boolean)));
  }, [activeWorkspace]);

  const scriptResults = useMemo(
    () => rawScriptResults.filter((r) => isResultAllowed(r.host_name, r.device_name)),
    [rawScriptResults, isResultAllowed],
  );
  const campaignResults = useMemo(
    () => rawCampaignResults.filter((r) => isResultAllowed(r.host_name, r.device_name)),
    [rawCampaignResults, isResultAllowed],
  );

  const setScriptResults = setRawScriptResults;
  const setCampaignResults = setRawCampaignResults;
  const [loading, setLoading] = useState(true);
  const [campaignLoading, setCampaignLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [discardModalOpen, setDiscardModalOpen] = useState(false);
  const [selectedDiscardComment, setSelectedDiscardComment] = useState<{
    comment: string;
    result: ScriptResult;
  } | null>(null);
  const [showDetailedColumns, setShowDetailedColumns] = useState(false);
  const [columnAnchor, setColumnAnchor] = useState<HTMLElement | null>(null);
  const [campaignColumnAnchor, setCampaignColumnAnchor] = useState<HTMLElement | null>(null);

  // Server-side filters (trigger refetch). `filterTarget` is the
  // "<host_name> - <device_name>" pair selected in the dropdown; the server
  // only filters by host_name so the device-name half is applied client-side.
  // ?host=&device=&script= pre-select these (Atlas Companion deep links) and follow later changes.
  const [filterScript, setFilterScript] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get('script'),
  );
  const [filterTarget, setFilterTarget] = useState<string | null>(() => {
    const q = new URLSearchParams(window.location.search);
    const host = q.get('host');
    return host ? buildTargetKey(host, q.get('device')) : null;
  });
  const [filterCampaign, setFilterCampaign] = useState<string | null>(null);

  // TASK-65 G7 — project scope. `filterProject` is the project the user picked
  // (id); `includeUntagged` controls whether projectless runs still show up.
  // The full project-filter UI lives in G9 (project context); for G7 we ship
  // the bare dropdown + toggle so the column chip has a working filter.
  const [filterProject, setFilterProject] = useState<string | null>(null);
  const [includeUntagged, setIncludeUntagged] = useState(true);

  // Known options for filter dropdowns (populated from initial load)
  const [knownScripts, setKnownScripts] = useState<string[]>([]);
  const [knownTargets, setKnownTargets] = useState<string[]>([]);
  const [knownCampaigns, setKnownCampaigns] = useState<string[]>([]);
  const [projectOptions, setProjectOptions] = useState<Array<{ id: string; name: string; color: string | null }>>([]);
  const initialLoadDone = useRef(false);
  // Suppress the loading spinner on auto-refresh / filter-change refetches when
  // we already have a populated table — only show it before the first load lands.
  // Ref (not state) so the loadScriptResults closure doesn't go stale.
  const hasLoadedScriptsRef = useRef(false);

  // Tab — persisted in URL ?tab=campaigns
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const browserTab = (tabParam === 'campaigns' ? 'campaigns' : tabParam === 'shared' && shareConfig?.enabled ? 'shared' : 'tests') as 'tests' | 'campaigns' | 'shared';
  const setBrowserTab = useCallback((tab: 'tests' | 'campaigns' | 'shared') => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (tab === 'tests') next.delete('tab'); else next.set('tab', tab);
      return next;
    }, { replace: true });
  }, [setSearchParams]);
  useEffect(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('host');
      next.delete('device');
      next.delete('script');
      if (filterTarget) {
        const { hostName, deviceName } = parseTargetKey(filterTarget);
        next.set('host', hostName);
        if (deviceName) next.set('device', deviceName);
      }
      if (filterScript) next.set('script', filterScript);
      return next;
    }, { replace: true });
  }, [filterTarget, filterScript, setSearchParams]);
  // Deep link from the report page's Share button (?share=<script_result_id>): open the
  // dialog for that run directly, so an old run never has to be found in the list first.
  const shareParam = searchParams.get('share');
  useEffect(() => {
    if (!shareParam || !shareConfig) return;
    if (canShare) setShareTarget({ id: shareParam, name: 'this run' });
    else showError('Sharing is not enabled for your account on this server.');
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('share');
      return next;
    }, { replace: true });
  }, [shareParam, shareConfig, canShare, setSearchParams, showError]);
  // Dashboard deep links (TASK-123): ?status=passed|failed|aborted and ?range=24h|7d|30d are sent to the server (applied
  // before the row limit, same verdict as the dashboard's counts) and re-applied client-side on the loaded rows.
  const statusParam = searchParams.get('status');
  const rangeParam = searchParams.get('range');
  const deepLinkStatus = statusParam === 'passed' || statusParam === 'failed' || statusParam === 'aborted' ? statusParam : undefined;
  const deepLinkRange = rangeParam === '24h' || rangeParam === '7d' || rangeParam === '30d' ? rangeParam : undefined;
  // Governance filters (milestone / group / label) — URL-keyed, applied server-side.
  const filterMilestoneId = searchParams.get(GOVERNANCE_PARAMS.milestone_id);
  const filterGroupId = searchParams.get(GOVERNANCE_PARAMS.run_group_id);
  const filterLabelId = searchParams.get(GOVERNANCE_PARAMS.label_id);
  const governanceFilters = useMemo(() => {
    const filters: Pick<ScriptResultFilters, 'milestone_id' | 'run_group_id' | 'label_id' | 'status' | 'range' | 'limit'> = {};
    if (filterMilestoneId) filters.milestone_id = filterMilestoneId;
    if (filterGroupId) filters.run_group_id = filterGroupId;
    if (filterLabelId) filters.label_id = filterLabelId;
    if (deepLinkStatus) filters.status = deepLinkStatus;
    if (deepLinkRange) filters.range = deepLinkRange;
    // A dashboard count covers the whole range; the default latest-100 window would hide most of it.
    if (deepLinkStatus || deepLinkRange) filters.limit = 1000;
    return filters;
  }, [filterMilestoneId, filterGroupId, filterLabelId, deepLinkStatus, deepLinkRange]);
  const setGovernanceFilter = useCallback(
    (key: keyof typeof GOVERNANCE_PARAMS, value: string | null) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(GOVERNANCE_PARAMS[key], value);
        else next.delete(GOVERNANCE_PARAMS[key]);
        return next;
      }, { replace: true });
    },
    [setSearchParams],
  );
  const { canEdit: canAssign } = useReportPermissions();
  const milestonesQuery = useMilestones(false);
  const groupsQuery = useRunGroups(false);
  const labelsQuery = useLabels();
  const milestoneOptions = milestonesQuery.data?.items ?? [];
  const groupOptions = groupsQuery.data?.items ?? [];
  const labelOptions = labelsQuery.data?.items ?? [];

  // Row selection for bulk assignment.
  const [selectedResultIds, setSelectedResultIds] = useState<Set<string>>(new Set());
  const [assignOpen, setAssignOpen] = useState(false);
  const toggleSelected = useCallback((id: string) => {
    setSelectedResultIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  // Flaky badges: ONE scoped quality query for the whole table, never per row. A failed
  // call shows no badges — they are an optional hint, not evidence.
  const flakyQuery = useQualityQuery('flaky', { windowDays: QUALITY_DEFAULT_WINDOW.flaky });
  const flakyByKey = useMemo(() => {
    const map = new Map<string, FlakyRow>();
    for (const row of flakyQuery.data?.rows ?? []) {
      const key = flakyKey(row.identity.script_name, row.identity.userinterface_name, row.identity.host_name, row.identity.device_name);
      const prev = map.get(key);
      if (!prev || (row.flaky_score ?? 0) > (prev.flaky_score ?? 0)) map.set(key, row);
    }
    return map;
  }, [flakyQuery.data]);
  const flakyWindowDays = flakyQuery.data?.window_days ?? QUALITY_DEFAULT_WINDOW.flaky;

  const [expandedCampaignId, setExpandedCampaignId] = useState<string | null>(null);
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);

  // Resizable columns — Tests tab
  const resizeCols = useResizableColumns([
    { key: 'script', initialWidth: 250, minWidth: 120 },
    { key: 'uiName', initialWidth: 120, minWidth: 80 },
    { key: 'host', initialWidth: 120, minWidth: 80 },
    { key: 'device', initialWidth: 100, minWidth: 80 },
    { key: 'status', initialWidth: 60, minWidth: 50 },
    { key: 'duration', initialWidth: 80, minWidth: 60 },
    { key: 'started', initialWidth: 150, minWidth: 100 },
    // The 'report' cell renders an Open-Report IconButton + a Share IconButton
    // (each ~28px with p:0.5 padding) and needs ~75 px to show both glyphs
    // uncompressed. The previous 55/45 squashed the share glyph to "...".
    { key: 'report', initialWidth: 80, minWidth: 65 },
    { key: 'logs', initialWidth: 55, minWidth: 45 },
    { key: 'rerun', initialWidth: 55, minWidth: 45 },
    { key: 'checked', initialWidth: 60, minWidth: 50 },
    { key: 'discard', initialWidth: 60, minWidth: 50 },
    { key: 'analyzedBy', initialWidth: 80, minWidth: 60 },
    { key: 'comment', initialWidth: 60, minWidth: 50 },
  ]);

  // Resizable columns — Campaigns tab
  const campaignResizeCols = useResizableColumns([
    { key: 'campaign', initialWidth: 250, minWidth: 120 },
    { key: 'host', initialWidth: 120, minWidth: 80 },
    { key: 'device', initialWidth: 100, minWidth: 80 },
    { key: 'status', initialWidth: 60, minWidth: 50 },
    { key: 'scripts', initialWidth: 80, minWidth: 60 },
    { key: 'duration', initialWidth: 80, minWidth: 60 },
    { key: 'started', initialWidth: 150, minWidth: 100 },
    // Same reasoning as the Tests tab: 80 px to fit the Open-Report + Share
    // IconButtons side by side, with a 65 px floor to keep the share glyph
    // legible even after a user resize.
    { key: 'report', initialWidth: 80, minWidth: 65 },
    { key: 'logs', initialWidth: 55, minWidth: 45 },
  ]);

  // Column visibility — persisted to localStorage
  const COLUMN_VISIBILITY_KEY = 'test_reports_column_visibility_v1';
  type ColumnId = 'uiName' | 'host' | 'device' | 'status' | 'duration' | 'started' | 'report' | 'logs' | 'rerun';
  const ALL_COLUMNS: { id: ColumnId; label: string }[] = [
    { id: 'uiName', label: 'UI Name' },
    { id: 'host', label: 'Target' },
    { id: 'device', label: 'Device' },
    { id: 'status', label: 'Status' },
    { id: 'duration', label: 'Duration' },
    { id: 'started', label: 'Started' },
    { id: 'report', label: 'Report' },
    { id: 'logs', label: 'Logs' },
    { id: 'rerun', label: 'Rerun' },
  ];
  const DEFAULT_HIDDEN: ColumnId[] = ['uiName', 'device'];

  const [hiddenColumns, setHiddenColumns] = useState<Set<ColumnId>>(() => {
    try {
      const stored = localStorage.getItem(COLUMN_VISIBILITY_KEY);
      if (stored) return new Set(JSON.parse(stored) as ColumnId[]);
    } catch { /* ignore */ }
    return new Set(DEFAULT_HIDDEN);
  });

  const isColumnVisible = (id: ColumnId) => {
    if (showDetailedColumns && (id === 'duration' || id === 'started')) return false;
    return !hiddenColumns.has(id);
  };

  const toggleColumnVisibility = (id: ColumnId) => {
    setHiddenColumns((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      try { localStorage.setItem(COLUMN_VISIBILITY_KEY, JSON.stringify([...next])); } catch { /* ignore */ }
      return next;
    });
  };

  const visibleColumnCount = useMemo(() => {
    let count = 1; // Script is always visible
    ALL_COLUMNS.forEach((col) => { if (isColumnVisible(col.id)) count++; });
    if (showDetailedColumns) count += 4;
    if (canAssign) count += 1; // selection column
    return count;
  }, [hiddenColumns, showDetailedColumns, canAssign]);

  // Skeleton column widths, in the same order as the real cells below. Built from the same
  // visibility predicates so the grey rows line up under the header whatever the user hid.
  // `null` marks a cell that holds an icon or a button rather than text.
  const skeletonColumnWidths = useMemo(() => {
    const w: Array<number | string | null> = [];
    if (canAssign) w.push(null); // selection checkbox
    w.push('58%'); // Test — the name column takes the remaining width
    ALL_COLUMNS.forEach((col) => {
      if (!isColumnVisible(col.id)) return;
      if (col.id === 'report' || col.id === 'logs' || col.id === 'rerun') w.push(null);
      else if (col.id === 'host' || col.id === 'device' || col.id === 'uiName') w.push('62%');
      else w.push('72%');
    });
    if (showDetailedColumns) w.push('72%', '72%', '58%', '45%'); // Checked/Discard/AnalyzedBy/Comment
    return w;
  }, [hiddenColumns, showDetailedColumns, canAssign]);

  // Campaign column visibility — persisted to localStorage
  const CAMPAIGN_COL_VISIBILITY_KEY = 'campaign_reports_column_visibility_v1';
  type CampaignColumnId = 'host' | 'device' | 'status' | 'scripts' | 'duration' | 'started' | 'report' | 'logs';
  const ALL_CAMPAIGN_COLUMNS: { id: CampaignColumnId; label: string }[] = [
    { id: 'host', label: 'Target' },
    { id: 'device', label: 'Device' },
    { id: 'status', label: 'Status' },
    { id: 'scripts', label: 'Scripts' },
    { id: 'duration', label: 'Duration' },
    { id: 'started', label: 'Started' },
    { id: 'report', label: 'Report' },
    { id: 'logs', label: 'Logs' },
  ];

  const [hiddenCampaignColumns, setHiddenCampaignColumns] = useState<Set<CampaignColumnId>>(() => {
    try {
      const stored = localStorage.getItem(CAMPAIGN_COL_VISIBILITY_KEY);
      if (stored) return new Set(JSON.parse(stored) as CampaignColumnId[]);
    } catch { /* ignore */ }
    return new Set<CampaignColumnId>();
  });

  const isCampaignColumnVisible = (id: CampaignColumnId) => !hiddenCampaignColumns.has(id);

  const toggleCampaignColumnVisibility = (id: CampaignColumnId) => {
    setHiddenCampaignColumns((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      try { localStorage.setItem(CAMPAIGN_COL_VISIBILITY_KEY, JSON.stringify([...next])); } catch { /* ignore */ }
      return next;
    });
  };

  const visibleCampaignColumnCount = useMemo(() => {
    let count = 1; // Campaign name is always visible
    ALL_CAMPAIGN_COLUMNS.forEach((col) => { if (isCampaignColumnVisible(col.id)) count++; });
    return count;
  }, [hiddenCampaignColumns]);

  // Campaign skeleton widths — same order as the campaign cells, `null` for icon cells.
  const campaignSkeletonWidths = useMemo(() => {
    const w: Array<number | string | null> = ['58%']; // Campaign name
    ALL_CAMPAIGN_COLUMNS.forEach((col) => {
      if (!isCampaignColumnVisible(col.id)) return;
      if (col.id === 'report' || col.id === 'logs') w.push(null);
      else if (col.id === 'status') w.push('78%');
      else w.push('62%');
    });
    return w;
  }, [hiddenCampaignColumns]);

  // Load script results (refetches when server-side filters change)
  const loadScriptResults = useCallback(async (filters?: ScriptResultFilters) => {
    try {
      ensureScriptIdentityMap();
      if (!hasLoadedScriptsRef.current) setLoading(true);
      setError(null);
      const results = await getAllScriptResults(filters);
      setScriptResults(results);
      hasLoadedScriptsRef.current = true;

      // On first (unfiltered) load, populate dropdown options
      if (!initialLoadDone.current) {
        initialLoadDone.current = true;
        const scripts = new Set<string>();
        const targets = new Set<string>();
        const projectMap = new Map<string, { id: string; name: string; color: string | null }>();
        for (const r of results) {
          if (r.script_name) scripts.add(r.script_name);
          if (r.host_name) targets.add(buildTargetKey(r.host_name, r.device_name));
          // TASK-65 G7 — collect every project that any row points at so the
          // filter dropdown can show them. Backend `get_script_results` only
          // ships a project tag for tagged scripts; projectless rows are
          // ignored here and stay addressable through the "include untagged"
          // toggle.
          for (const p of r.projects ?? []) {
            if (!projectMap.has(p.id)) projectMap.set(p.id, p);
          }
        }
        setKnownScripts(Array.from(scripts).sort());
        setKnownTargets(Array.from(targets).sort());
        setProjectOptions(
          Array.from(projectMap.values()).sort((a, b) => a.name.localeCompare(b.name)),
        );
      }
    } catch (err) {
      console.error('[@component:TestReports] Error loading script results:', err);
      setError(err instanceof Error ? err.message : 'Failed to load script results');
    } finally {
      setLoading(false);
    }
  }, [getAllScriptResults]);

  // Relaunch a stored run on its original target with its original config.
  // The new run lands in script_results like any other, so the table just
  // refetches rather than tracking it locally.
  const handleRerun = useCallback(async (result: ScriptResult) => {
    const payload = buildRerunPayloadFromResult(result);
    if (!payload) return;

    const label = getScriptLabel(result);
    showInfo(`Rerunning "${label}" on ${formatTargetLabel(buildTargetKey(result.host_name, result.device_name))}`);

    const outcome = await rerun(payload, result.id);
    if (!outcome.started) {
      showError(`Rerun of "${label}" failed: ${outcome.error || 'unknown error'}`);
      return;
    }
    showSuccess(`Rerun of "${label}" finished`);

    const filters: ScriptResultFilters = { ...governanceFilters };
    if (filterScript) filters.script_name = filterScript;
    if (filterTarget) filters.host_name = parseTargetKey(filterTarget).hostName;
    if (workspaceHostFilter) filters.host_filter = workspaceHostFilter;
    void loadScriptResults(Object.keys(filters).length > 0 ? filters : undefined);
  }, [rerun, showInfo, showError, showSuccess, filterScript, filterTarget, workspaceHostFilter, governanceFilters, loadScriptResults]);

  useEffect(() => {
    const filters: ScriptResultFilters = { ...governanceFilters };
    if (filterScript) filters.script_name = filterScript;
    if (filterTarget) filters.host_name = parseTargetKey(filterTarget).hostName;
    if (workspaceHostFilter) filters.host_filter = workspaceHostFilter;
    loadScriptResults(Object.keys(filters).length > 0 ? filters : undefined);
  }, [filterScript, filterTarget, workspaceHostFilter, governanceFilters, loadScriptResults]);

  // Load campaign results when Campaigns tab is selected
  const campaignLoadDone = useRef(false);
  const loadCampaignResults = useCallback(async (silent = false) => {
    try {
      if (!silent) setCampaignLoading(true);
      const results = await getAllCampaignResults();
      setCampaignResults(results);
      campaignLoadDone.current = true;
      // Populate campaign filter options and merge hosts
      const campaignTargets = new Set(
        results
          .filter((r) => r.host_name)
          .map((r) => buildTargetKey(r.host_name, r.device_name)),
      );
      if (campaignTargets.size > 0) {
        setKnownTargets((prev) => {
          const merged = new Set(prev);
          campaignTargets.forEach((t) => merged.add(t));
          return Array.from(merged).sort();
        });
      }
      const campaignNames = new Set(results.map((r) => r.campaign_name).filter(Boolean));
      setKnownCampaigns(Array.from(campaignNames).sort());
    } catch (err) {
      console.error('[@component:TestReports] Error loading campaign results:', err);
      if (!silent) setError(err instanceof Error ? err.message : 'Failed to load campaign results');
    } finally {
      if (!silent) setCampaignLoading(false);
    }
  }, [getAllCampaignResults]);

  // Eagerly load campaign data on mount (not just when tab is selected) to avoid flash
  useEffect(() => {
    if (campaignLoadDone.current) return;
    loadCampaignResults(browserTab !== 'campaigns'); // silent if not active tab
  }, [browserTab, loadCampaignResults]);

  // When the selected backend server changes, drop cached results and dropdown
  // options so the page reflects the new server's data instead of the previous
  // server's, then refetch from the newly-selected server.
  const prevServerRef = useRef<string | null>(null);
  useEffect(() => {
    if (prevServerRef.current === null) {
      prevServerRef.current = selectedServer;
      return;
    }
    if (prevServerRef.current === selectedServer) return;
    prevServerRef.current = selectedServer;

    setRawScriptResults([]);
    setRawCampaignResults([]);
    setKnownScripts([]);
    setKnownTargets([]);
    setKnownCampaigns([]);
    setProjectOptions([]);
    setFilterScript(null);
    setFilterTarget(null);
    setFilterCampaign(null);
    setFilterProject(null);
    setSelectedFolder(null);
    initialLoadDone.current = false;
    campaignLoadDone.current = false;
    hasLoadedScriptsRef.current = false;
    setLoading(true);

    loadScriptResults();
    void loadCampaignResults(browserTab !== 'campaigns');
  }, [selectedServer, loadScriptResults, loadCampaignResults, browserTab]);

  // When the active workspace changes, the visible device set changes too.
  // The dropdown options (targets/scripts/campaigns) are only populated on the
  // first load, and the selected filters can reference devices the new
  // workspace hides — so drop both and repopulate from the new workspace's
  // data. Mirrors the server-change reset above. The row refetch itself is
  // driven by `workspaceHostFilter` in the load effect below; here we just
  // reset the derived filter UI so it doesn't show the previous workspace.
  const prevWorkspaceRef = useRef<string | null>(null);
  useEffect(() => {
    const workspaceId = activeWorkspace?.id ?? null;
    if (prevWorkspaceRef.current === null) {
      prevWorkspaceRef.current = workspaceId;
      return;
    }
    if (prevWorkspaceRef.current === workspaceId) return;
    prevWorkspaceRef.current = workspaceId;

    setKnownScripts([]);
    setKnownTargets([]);
    setKnownCampaigns([]);
    setProjectOptions([]);
    setFilterScript(null);
    setFilterTarget(null);
    setFilterCampaign(null);
    setFilterProject(null);
    setSelectedFolder(null);
    initialLoadDone.current = false;
    campaignLoadDone.current = false;

    // Explicit reload so options repopulate from the new workspace even when no
    // filter was selected (a cleared filterTarget wouldn't retrigger the load
    // effect). Scope to the new workspace's hosts.
    const workspaceFilters: ScriptResultFilters = { ...governanceFilters };
    if (workspaceHostFilter) workspaceFilters.host_filter = workspaceHostFilter;
    loadScriptResults(Object.keys(workspaceFilters).length > 0 ? workspaceFilters : undefined);
    void loadCampaignResults(browserTab !== 'campaigns');
  }, [activeWorkspace?.id, workspaceHostFilter, governanceFilters, loadScriptResults, loadCampaignResults, browserTab]);

  // Auto-refresh data every 20s
  useEffect(() => {
    const interval = setInterval(() => {
      if (browserTab === 'campaigns') {
        void loadCampaignResults(true);
      } else {
        const filters: ScriptResultFilters = { ...governanceFilters };
        if (filterScript) filters.script_name = filterScript;
        if (filterTarget) filters.host_name = parseTargetKey(filterTarget).hostName;
        void loadScriptResults(Object.keys(filters).length > 0 ? filters : undefined);
      }
    }, 20_000);
    return () => clearInterval(interval);
  }, [browserTab, filterScript, filterTarget, governanceFilters, loadCampaignResults, loadScriptResults]);

  // Filter campaign results by search
  const filteredCampaignResults = useMemo(() => {
    let items = campaignResults;
    if (filterCampaign) {
      items = items.filter((r) => r.campaign_name === filterCampaign);
    }
    if (filterTarget) {
      const { hostName, deviceName } = parseTargetKey(filterTarget);
      items = items.filter(
        (r) => r.host_name === hostName && (!deviceName || r.device_name === deviceName),
      );
    }
    return items;
  }, [campaignResults, filterCampaign, filterTarget]);

  // Calculate stats. `null` means "nothing to compute from" — true both before the first load
  // lands and on an empty result set. That is neither a rate of zero nor a failure, so it must
  // not fall through the rate thresholds into the error colour (UI_STYLE §10 S6).
  const totalReports = scriptResults.length;
  const passedReports = scriptResults.filter((result) => result.success).length;
  const successRate: number | null =
    totalReports > 0 ? (passedReports / totalReports) * 100 : null;

  // Calculate average duration
  const validDurations = scriptResults.filter((result) => result.execution_time_ms !== null);
  const avgDuration: string | null =
    validDurations.length > 0
      ? formatDuration(
          validDurations.reduce((sum, result) => sum + (result.execution_time_ms || 0), 0) /
            validDurations.length,
        )
      : null;

  // Extract unique script folders (tests tab only)
  const folderOptions = useMemo(() => {
    const folders = new Set<string>();
    for (const r of scriptResults) {
      if (r.script_name) {
        const stripped = r.script_name.replace(/^test_scripts\//, '');
        const slashIdx = stripped.indexOf('/');
        if (slashIdx > 0) folders.add(stripped.substring(0, slashIdx));
      }
    }
    return Array.from(folders).sort();
  }, [scriptResults]);

  // Filter results by folder and search (tests tab only)
  const filteredResults = useMemo(() => {
    let results = scriptResults;

    // Target filter: server already narrows to host_name; apply the
    // device_name half of the "<host> - <device>" target key client-side.
    if (filterTarget) {
      const { hostName, deviceName } = parseTargetKey(filterTarget);
      results = results.filter(
        (r) => r.host_name === hostName && (!deviceName || r.device_name === deviceName),
      );
    }

    // TASK-65 G7 — project scope. When a project is picked the row must be
    // tagged with it; the `includeUntagged` toggle adds the projectless rows
    // back so the user can still find them. A projectless row is "no
    // `project_ids`", or an empty `projects` list.
    if (filterProject) {
      results = results.filter((r) => {
        const ids = r.project_ids ?? [];
        if (ids.includes(filterProject)) return true;
        if (includeUntagged && ids.length === 0) return true;
        return false;
      });
    } else if (!includeUntagged) {
      // No project picked + "hide untagged" → only show rows that belong to
      // at least one project. This is the path the G9 project-scope will own.
      results = results.filter((r) => (r.project_ids ?? []).length > 0);
    }

    // Dashboard deep links: verdict and time window.
    if (statusParam === 'passed' || statusParam === 'failed') {
      results = results.filter((r) => getExecutionStatus(r) === statusParam);
    } else if (statusParam === 'aborted') {
      results = results.filter((r) => !r.success && /abort/i.test(r.error_msg ?? ''));
    }
    const rangeMs = rangeParam ? { '24h': 86_400_000, '7d': 7 * 86_400_000, '30d': 30 * 86_400_000 }[rangeParam] : undefined;
    if (rangeMs) {
      const since = Date.now() - rangeMs;
      results = results.filter((r) => new Date(r.created_at).getTime() >= since);
    }

    // Folder filter
    if (selectedFolder) {
      results = results.filter((r) => {
        if (!r.script_name) return false;
        const stripped = r.script_name.replace(/^test_scripts\//, '');
        return stripped.startsWith(selectedFolder + '/');
      });
    }

    return results;
  }, [scriptResults, browserTab, selectedFolder, filterTarget, filterProject, includeUntagged, statusParam, rangeParam]);

  // Format duration helper
  function formatDuration(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const minutes = Math.floor(ms / 60000);
    const seconds = ((ms % 60000) / 1000).toFixed(1);
    return `${minutes}m ${seconds}s`;
  }

  // Format date helper
  function formatDate(dateString: string): string {
    return formatToLocalTime(dateString);
  }

  // Get logs URL/path from result — prefer direct DB fields, fall back to deriving from report URL
  function getLogsUrlOrPath(result: ScriptResult): string | null {
    // Prefer direct logs URL/path from DB
    if (result.logs_r2_url) return result.logs_r2_url;
    if (result.logs_r2_path) return result.logs_r2_path;

    // Fall back: derive from report URL/path
    const reportRef = result.html_report_r2_path || result.html_report_r2_url;
    if (!reportRef) return null;

    let path = reportRef;
    try {
      if (path.startsWith('http')) {
        const url = new URL(path);
        path = url.pathname.substring(1); // remove leading /
      }
    } catch { /* use as-is */ }
    // Remove /minio/{bucket}/ prefix (any bucket name)
    const minioMatch = path.match(/^minio\/[^/]+\/(.*)/);
    if (minioMatch) {
      path = minioMatch[1];
    }
    // Remove {bucket}/ prefix if it doesn't start with script-
    if (!path.startsWith('script-') && path.includes('/')) {
      const firstSlash = path.indexOf('/');
      const afterFirst = path.substring(firstSlash + 1);
      if (afterFirst.startsWith('script-')) {
        path = afterFirst;
      }
    }
    return path.replace('script-reports', 'script-logs').replace('report.html', 'execution.txt');
  }

  // Open R2 URL with automatic signed URL generation (handles both public and private modes)
  const handleOpenR2Url = async (url: string) => {
    try {
      await openR2Url(url);
    } catch (error) {
      console.error('[@TestReports] Failed to open R2 URL:', error);
      setError('Failed to open file. Please try again.');
    }
  };

  // Determine execution status helper
  //
  // The rule lives in utils/resultOutcome.ts: a row that carries the `skipped`
  // flag never executed, so it is a skip and not a failure — the reports have
  // to show it as one, or a nightly campaign reads as broken for a check that
  // never ran (BUG-0756).
  function getExecutionStatus(result: ScriptResult): ResultOutcome {
    return getResultOutcome(result);
  }

  // Note: handleDiscardToggle removed - discard status is now managed by AI analysis
  // Users can view AI analysis results but cannot manually toggle discard status

  // Handle discard comment modal
  const handleDiscardCommentClick = (result: ScriptResult) => {
    if (result.discard_comment) {
      setSelectedDiscardComment({
        comment: result.discard_comment,
        result: result,
      });
      setDiscardModalOpen(true);
    }
  };

  const handleCloseDiscardModal = () => {
    setDiscardModalOpen(false);
    setSelectedDiscardComment(null);
  };

  // Note: toggleRowExpansion removed - not needed for this implementation

  // Handle checked status toggle
  const handleCheckedToggle = async (result: ScriptResult) => {
    try {
      const newChecked = !result.checked;
      await updateCheckedStatus(result.id, newChecked);
      
      // Update local state
      setScriptResults(prev => 
        prev.map(r => r.id === result.id ? { ...r, checked: newChecked, check_type: 'manual' } : r)
      );
    } catch (error) {
      console.error('Failed to update checked status:', error);
      setError('Failed to update checked status');
    }
  };

  // Handle discard status toggle
  const handleDiscardToggle = async (result: ScriptResult) => {
    try {
      const newDiscard = !result.discard;
      const checkType = result.check_type === 'ai' ? 'ai_and_human' : 'manual';
      
      await updateDiscardStatus(result.id, newDiscard, undefined, checkType);
      
      // Update local state
      setScriptResults(prev => 
        prev.map(r => r.id === result.id ? { ...r, discard: newDiscard, check_type: checkType } : r)
      );
    } catch (error) {
      console.error('Failed to update discard status:', error);
      setError('Failed to update discard status');
    }
  };

  // Get individual discard analysis components
  const getCheckedStatus = (result: ScriptResult) => {
    if (result.check_type === 'ai_strategy_skip') {
      return (
        <Tooltip title="Analysis skipped by strategy">
          <IconButton size="small" sx={{ p: 0.5 }} disableRipple>
            <SkippedIcon fontSize="small" color="disabled" />
          </IconButton>
        </Tooltip>
      );
    }
    if (result.checked === undefined || result.checked === null) {
      return (
        <Tooltip title="Mark as checked">
          <IconButton
            size="small"
            onClick={() => handleCheckedToggle(result)}
            sx={{ p: 0.5 }}
          >
            <UnknownIcon fontSize="small" color="disabled" />
          </IconButton>
        </Tooltip>
      );
    }
    return (
      <Tooltip title={result.checked ? 'Checked' : 'Not checked'}>
        <IconButton
          size="small"
          onClick={() => handleCheckedToggle(result)}
          sx={{ p: 0.5 }}
        >
          <CheckedIcon fontSize="small" color={result.checked ? 'success' : 'disabled'} />
        </IconButton>
      </Tooltip>
    );
  };

  const getDiscardStatus = (result: ScriptResult) => {
    if (result.check_type === 'ai_strategy_skip') {
      return (
        <Typography variant="body2" color="text.disabled">
          -
        </Typography>
      );
    }
    if (!result.checked) {
      return (
        <Typography variant="body2" color="text.disabled">
          -
        </Typography>
      );
    }
    return (
      <Tooltip title={result.discard ? 'Discarded (Invalid/False Positive)' : 'Valid (Legitimate Result)'}>
        <Typography
          variant="body2"
          onClick={() => handleDiscardToggle(result)}
          sx={{
            fontWeight: 'bold',
            color: result.discard ? 'error.main' : 'success.main',
            cursor: 'pointer',
            '&:hover': {
              opacity: 0.7,
            },
          }}
        >
          {result.discard ? 'YES' : 'NO'}
        </Typography>
      </Tooltip>
    );
  };

  const getCheckType = (result: ScriptResult) => {
    if (!result.check_type) {
      return (
        <Typography variant="body2" color="text.disabled">
          -
        </Typography>
      );
    }
    if (result.check_type === 'ai_strategy_skip') {
      return (
        <Tooltip title="Skipped by strategy">
          <Typography variant="body2" color="text.disabled" sx={{ fontStyle: 'italic' }}>
            Skipped
          </Typography>
        </Tooltip>
      );
    }
    const isAI = result.check_type === 'ai' || result.check_type === 'ai_agent' || result.check_type === 'ai_and_human';
    const isHuman = result.check_type === 'ai_and_human';
    return (
      <Tooltip title={isHuman ? 'AI & Human' : isAI ? 'AI Agent' : 'Manual'}>
        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
          {isAI && <AiIcon fontSize="small" color="primary" />}
          {(result.check_type === 'manual' || isHuman) && <ManualIcon fontSize="small" color="primary" />}
        </Box>
      </Tooltip>
    );
  };


  const getDiscardComment = (result: ScriptResult) => {
    if (!result.discard_comment) {
      return (
        <Typography variant="body2" color="text.disabled">
          -
        </Typography>
      );
    }
    return (
      <Tooltip title="View full comment">
        <IconButton
          size="small"
          onClick={() => handleDiscardCommentClick(result)}
          sx={{ p: 0.25 }}
        >
          <CommentIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    );
  };

  // Note: EmptyState component removed - now handled inline with dynamic colspan

  return (
    <Box
      sx={{
        // One card look and palette tables for the whole page (overrides the global table colours).
        '& .MuiCard-root': { borderRadius: 3, border: `1px solid ${P.borderColor}`, boxShadow: 'none' },
        '& .MuiTableContainer-root': { borderRadius: 2, borderColor: P.borderColor },
        '& .MuiTableCell-root': { borderColor: P.borderColor },
        '& thead .MuiTableCell-root': { fontSize: TYPOGRAPHY.caption.size, color: `${P.textSecondary} !important`, bgcolor: `${P.hoverBg} !important` },
        '& tbody .MuiIconButton-colorPrimary, & tbody .MuiIconButton-colorSecondary': {
          color: P.textSecondary, '&:hover': { color: P.accentText, bgcolor: P.hoverBg },
        },
        '& tbody .MuiSvgIcon-colorSuccess': { color: P.success },
        '& tbody .MuiSvgIcon-colorError': { color: P.error },
        '& tbody .MuiSvgIcon-colorWarning': { color: P.accentText },
      }}
    >
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5, gap: 1, flexWrap: 'wrap' }}>
        <Typography component="h1" sx={{ fontSize: TYPOGRAPHY.pageTitle.size, fontWeight: 600 }}>
          Test Reports
        </Typography>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={browserTab}
          onChange={(_e, v) => v && setBrowserTab(v)}
          sx={{
            bgcolor: P.hoverBg, p: 0.375, borderRadius: 2, gap: 0.375,
            '& .MuiToggleButton-root': {
              border: '1px solid transparent !important', borderRadius: '6px !important',
              textTransform: 'none', fontSize: TYPOGRAPHY.body.size, fontWeight: 500, color: P.textSecondary, py: 0.4, px: 2,
            },
            '& .MuiToggleButton-root.Mui-selected': {
              bgcolor: P.surface, color: P.accentText, fontWeight: 600,
              borderColor: `${P.borderColor} !important`, '&:hover': { bgcolor: P.surface },
            },
          }}
        >
          <ToggleButton value="tests">Tests</ToggleButton>
          <ToggleButton value="campaigns">Campaigns</ToggleButton>
          {shareConfig?.enabled && <ToggleButton value="shared">Shared links</ToggleButton>}
        </ToggleButtonGroup>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Quick Stats — two tiles and the Grafana link */}
      <Box sx={{ display: 'flex', alignItems: 'stretch', gap: 1, mb: 1.5, flexWrap: 'wrap' }}>
        {[
          {
            label: 'Success rate',
            value: successRate === null ? '—' : `${successRate.toFixed(1)}%`,
            color: successRate === null ? P.textMuted : successRate >= 80 ? P.success : successRate >= 50 ? P.warning : P.error,
            skeletonWidth: 64,
          },
          {
            label: 'Avg duration',
            value: avgDuration ?? '—',
            color: avgDuration ? P.textPrimary : P.textMuted,
            skeletonWidth: 52,
          },
        ].map((k) => (
          <Box key={k.label} sx={{ px: 1.5, py: 0.75, minWidth: 150, borderRadius: 2, bgcolor: P.surface, border: `1px solid ${P.borderColor}` }}>
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{k.label}</Typography>
            {/* Before the first load lands the value is unknown, not wrong — a grey bar in the
                value slot, never the red "N/A" this used to show (see ReportSkeleton.tsx). */}
            {loading ? (
              <ValueSkeleton width={k.skeletonWidth} height={24} />
            ) : (
              <Typography sx={{ fontSize: TYPOGRAPHY.pageSubtitle.size, fontWeight: 600, lineHeight: 1.3, color: k.color }}>{k.value}</Typography>
            )}
          </Box>
        ))}
        <Box sx={{ flex: 1 }} />
        <Tooltip title="Open Script Results Dashboard">
          <Button
            size="small"
            endIcon={<OpenInNew fontSize="small" />}
            onClick={() => window.open(withGrafanaWorkspace(`${grafanaUrl}/d/2a3b060a-7820-4a6e-aa2a-adcbf5408bd3/script-results?orgId=1&from=now-30d&to=now&timezone=browser&var-user_interface=$__all&var-host=$__all&var-device_name=$__all&var-script_name=$__all`, activeWorkspace?.id), '_blank')}
            sx={{ alignSelf: 'center', textTransform: 'none', color: P.accentText }}
          >
            Grafana dashboard
          </Button>
        </Tooltip>
      </Box>

      {/* Recent Test Reports / Campaign Reports */}
      <Card>
        <CardContent>
          {/* ===== CAMPAIGNS TABLE ===== */}
          <Box sx={{ display: browserTab === 'campaigns' ? 'block' : 'none' }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                  <Autocomplete
                    size="small"
                    value={filterCampaign}
                    onChange={(_e, v) => setFilterCampaign(v)}
                    options={knownCampaigns}
                    renderInput={(params) => (
                      <TextField
                        {...params}
                        label="Campaign"
                        InputLabelProps={{ shrink: true, sx: { px: 0.5 } }}
                      />
                    )}
                    slotProps={{ paper: { sx: { fontSize: TYPOGRAPHY.body.size } } }}
                    sx={{ minWidth: 340, '& .MuiInputBase-root': { height: 32, fontSize: TYPOGRAPHY.body.size } }}
                  />
                  <Autocomplete
                    size="small"
                    value={filterTarget}
                    onChange={(_e, v) => setFilterTarget(v)}
                    options={knownTargets}
                    getOptionLabel={(option) => formatTargetLabel(option)}
                    renderInput={(params) => (
                      <TextField
                        {...params}
                        label="Target"
                        InputLabelProps={{ shrink: true, sx: { px: 0.5 } }}
                      />
                    )}
                    slotProps={{ paper: { sx: { fontSize: TYPOGRAPHY.body.size } } }}
                    sx={{ minWidth: 380, '& .MuiInputBase-root': { height: 32, fontSize: TYPOGRAPHY.body.size } }}
                  />
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Tooltip title="Toggle columns">
                    <IconButton size="small" onClick={(e) => setCampaignColumnAnchor(e.currentTarget)}>
                      <ViewColumnIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Popover
                    open={Boolean(campaignColumnAnchor)}
                    anchorEl={campaignColumnAnchor}
                    onClose={() => setCampaignColumnAnchor(null)}
                    anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                    transformOrigin={{ vertical: 'top', horizontal: 'right' }}
                  >
                    <Box sx={{ p: 1, minWidth: 160 }}>
                      <Typography variant="caption" color="text.secondary" sx={{ px: 1 }}>Show/Hide Columns</Typography>
                      {ALL_CAMPAIGN_COLUMNS.map((col) => (
                        <FormControlLabel
                          key={col.id}
                          control={<Checkbox size="small" checked={isCampaignColumnVisible(col.id)} onChange={() => toggleCampaignColumnVisibility(col.id)} />}
                          label={<Typography variant="body2">{col.label}</Typography>}
                          sx={{ display: 'flex', mx: 0, py: 0 }}
                        />
                      ))}
                    </Box>
                  </Popover>
                </Box>
              </Box>

              <TableContainer component={Paper} variant="outlined">
                <Table size="small" sx={{
                  tableLayout: 'fixed',
                  '& .MuiTableCell-root': {
                    px: 1,
                    py: 0.25,
                    fontSize: TYPOGRAPHY.body.size,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }
                }}>
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ py: 0.5, ...campaignResizeCols.headerCellSx('campaign') }}>
                        <strong>Campaign</strong>
                        <Box component="span" onMouseDown={campaignResizeCols.onMouseDown('campaign')} sx={campaignResizeCols.resizeHandleSx} />
                      </TableCell>
                      {isCampaignColumnVisible('host') && (
                        <TableCell sx={{ py: 0.5, ...campaignResizeCols.headerCellSx('host') }}>
                          <strong>Target</strong>
                          <Box component="span" onMouseDown={campaignResizeCols.onMouseDown('host')} sx={campaignResizeCols.resizeHandleSx} />
                        </TableCell>
                      )}
                      {isCampaignColumnVisible('device') && (
                        <TableCell sx={{ py: 0.5, ...campaignResizeCols.headerCellSx('device') }}>
                          <strong>Device</strong>
                          <Box component="span" onMouseDown={campaignResizeCols.onMouseDown('device')} sx={campaignResizeCols.resizeHandleSx} />
                        </TableCell>
                      )}
                      {isCampaignColumnVisible('status') && (
                        <TableCell sx={{ py: 0.5, ...campaignResizeCols.headerCellSx('status') }}>
                          <strong>Status</strong>
                          <Box component="span" onMouseDown={campaignResizeCols.onMouseDown('status')} sx={campaignResizeCols.resizeHandleSx} />
                        </TableCell>
                      )}
                      {isCampaignColumnVisible('scripts') && (
                        <TableCell sx={{ py: 0.5, ...campaignResizeCols.headerCellSx('scripts') }}>
                          <strong>Scripts</strong>
                          <Box component="span" onMouseDown={campaignResizeCols.onMouseDown('scripts')} sx={campaignResizeCols.resizeHandleSx} />
                        </TableCell>
                      )}
                      {isCampaignColumnVisible('duration') && (
                        <TableCell sx={{ py: 0.5, ...campaignResizeCols.headerCellSx('duration') }}>
                          <strong>Duration</strong>
                          <Box component="span" onMouseDown={campaignResizeCols.onMouseDown('duration')} sx={campaignResizeCols.resizeHandleSx} />
                        </TableCell>
                      )}
                      {isCampaignColumnVisible('started') && (
                        <TableCell sx={{ py: 0.5, ...campaignResizeCols.headerCellSx('started') }}>
                          <strong>Started</strong>
                          <Box component="span" onMouseDown={campaignResizeCols.onMouseDown('started')} sx={campaignResizeCols.resizeHandleSx} />
                        </TableCell>
                      )}
                      {isCampaignColumnVisible('report') && (
                        <TableCell sx={{ py: 0.5, ...campaignResizeCols.headerCellSx('report') }}>
                          <strong>Report</strong>
                          <Box component="span" onMouseDown={campaignResizeCols.onMouseDown('report')} sx={campaignResizeCols.resizeHandleSx} />
                        </TableCell>
                      )}
                      {isCampaignColumnVisible('logs') && (
                        <TableCell sx={{ py: 0.5, ...campaignResizeCols.headerCellSx('logs') }}>
                          <strong>Logs</strong>
                          <Box component="span" onMouseDown={campaignResizeCols.onMouseDown('logs')} sx={campaignResizeCols.resizeHandleSx} />
                        </TableCell>
                      )}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {campaignLoading ? (
                      <TableRowsSkeleton rows={8} widths={campaignSkeletonWidths} />
                    ) : filteredCampaignResults.length === 0 ? (
                      <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                        <TableCell colSpan={visibleCampaignColumnCount} sx={{ textAlign: 'center', py: 4 }}>
                          <Typography variant="body2" color="textSecondary">
                            No campaign results available yet
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ) : (
                      filteredCampaignResults.map((result) => {
                        const scriptCount = result.script_configurations?.length || result.script_result_ids?.length || result.script_results?.length || 0;
                        const passedCount = result.script_results?.filter((s) => s.success).length || 0;
                        // A check that never ran is neither a pass nor a failure:
                        // it is counted apart, so the nightly row says how many
                        // were skipped instead of hiding them in "not passed".
                        const skippedCount = result.script_results?.filter((s) => isSkippedResult(s)).length || 0;
                        const hasScripts = (result.script_results?.length ?? 0) > 0;
                        const isExpanded = expandedCampaignId === result.id;
                        return (
                          <React.Fragment key={result.id}>
                          <TableRow
                            sx={{
                              '&:hover': {
                                backgroundColor: `${P.hoverBg} !important`,
                              },
                              opacity: result.discard ? 0.5 : 1,
                              cursor: hasScripts ? 'pointer' : 'default',
                            }}
                            onClick={() => hasScripts && setExpandedCampaignId(isExpanded ? null : result.id)}
                          >
                            <TableCell sx={{ py: 0.5, ...campaignResizeCols.bodyCellSx('campaign') }}>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                {hasScripts && (
                                  <IconButton size="small" sx={{ p: 0 }}>
                                    {isExpanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                                  </IconButton>
                                )}
                                <Tooltip title={result.campaign_name} placement="top-start">
                                  <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{result.campaign_name}</Box>
                                </Tooltip>
                                {result.id && (
                                  <Tooltip title="Run summary">
                                    <IconButton
                                      size="small"
                                      component={RouterLink}
                                      to={REPORT_ROUTES.summary('campaign', result.id)}
                                      onClick={(e: React.MouseEvent) => e.stopPropagation()}
                                      aria-label="Open run summary"
                                      sx={{ p: 0.25, flexShrink: 0 }}
                                    >
                                      <SummaryIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
                                    </IconButton>
                                  </Tooltip>
                                )}
                              </Box>
                            </TableCell>
                            {isCampaignColumnVisible('host') && (
                              <TableCell sx={{ py: 0.5, ...campaignResizeCols.bodyCellSx('host') }}>
                                <Tooltip title={formatTargetLabel(buildTargetKey(result.host_name, result.device_name))} placement="top-start">
                                  <span>{formatTargetLabel(buildTargetKey(result.host_name, result.device_name))}</span>
                                </Tooltip>
                              </TableCell>
                            )}
                            {isCampaignColumnVisible('device') && (
                              <TableCell sx={{ py: 0.5, ...campaignResizeCols.bodyCellSx('device') }}>{result.device_name}</TableCell>
                            )}
                            {isCampaignColumnVisible('status') && (
                            <TableCell sx={{ py: 0.5, ...campaignResizeCols.bodyCellSx('status') }}>
                              {result.status === 'running' ? (
                                <Tooltip title="Running">
                                  <RunningIcon color="warning" fontSize="small" />
                                </Tooltip>
                              ) : result.status === 'aborted' || result.status === 'cancelled' ? (
                                // An aborted or cancelled campaign never reached a
                                // verdict: it is not a test failure, so it wears the
                                // neutral grey of a stop, never the red of a failure.
                                <Tooltip title={result.status === 'aborted' ? 'Aborted' : 'Cancelled'}>
                                  <AbortedIcon color="disabled" fontSize="small" />
                                </Tooltip>
                              ) : result.success ? (
                                <Tooltip title="Pass">
                                  <PassIcon color="success" fontSize="small" />
                                </Tooltip>
                              ) : (
                                <Tooltip title="Fail">
                                  <FailIcon color="error" fontSize="small" />
                                </Tooltip>
                              )}
                            </TableCell>
                            )}
                            {isCampaignColumnVisible('scripts') && (
                            <TableCell sx={{ py: 0.5, ...campaignResizeCols.bodyCellSx('scripts') }}>
                              <Tooltip title={`${passedCount}/${scriptCount} passed${skippedCount ? `, ${skippedCount} skipped` : ''}`}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                  <span>{passedCount}/{scriptCount}</span>
                                  {skippedCount > 0 && (
                                    <Chip
                                      label={`${skippedCount} skipped`}
                                      size="small"
                                      sx={{ height: '16px', fontSize: TYPOGRAPHY.microMeta.size, flexShrink: 0 }}
                                    />
                                  )}
                                </Box>
                              </Tooltip>
                            </TableCell>
                            )}
                            {isCampaignColumnVisible('duration') && (
                            <TableCell sx={{ py: 0.5, ...campaignResizeCols.bodyCellSx('duration') }}>
                              {result.execution_time_ms
                                ? formatDuration(result.execution_time_ms)
                                : 'N/A'}
                            </TableCell>
                            )}
                            {isCampaignColumnVisible('started') && (
                              <TableCell sx={{ py: 0.5, ...campaignResizeCols.bodyCellSx('started') }}>{formatDate(result.started_at)}</TableCell>
                            )}
                            {isCampaignColumnVisible('report') && (
                            <TableCell sx={{ py: 0.5, textAlign: 'center', ...campaignResizeCols.bodyCellSx('report') }}>
                              {result.html_report_r2_url ? (
                                <Tooltip title="Open Report">
                                  <IconButton
                                    size="small"
                                    onClick={(e) => { e.stopPropagation(); handleOpenR2Url(result.html_report_r2_url!); }}
                                    color="primary"
                                    sx={{ p: 0.5 }}
                                  >
                                    <ReportFileIcon fontSize="small" />
                                  </IconButton>
                                </Tooltip>
                              ) : (
                                <Typography variant="body2" color="text.disabled">-</Typography>
                              )}
                            </TableCell>
                            )}
                            {isCampaignColumnVisible('logs') && (
                            <TableCell sx={{ py: 0.5, textAlign: 'center', ...campaignResizeCols.bodyCellSx('logs') }}>
                              {result.logs_r2_url ? (
                                <Tooltip title="Open Logs">
                                  <IconButton
                                    size="small"
                                    onClick={(e) => { e.stopPropagation(); handleOpenR2Url(result.logs_r2_url!); }}
                                    sx={{ ...(neutralButtonSx(P) as object),  p: 0.5 }}
                                  >
                                    <LogsIcon fontSize="small" />
                                  </IconButton>
                                </Tooltip>
                              ) : (
                                <Typography variant="body2" color="text.disabled">-</Typography>
                              )}
                            </TableCell>
                            )}
                          </TableRow>
                          {hasScripts && (
                            <TableRow sx={{
                              '&:hover': {
                                backgroundColor: `${P.hoverBg} !important`,
                              },
                            }}>
                              <TableCell colSpan={visibleCampaignColumnCount} sx={{ py: 0, borderBottom: isExpanded ? undefined : 'none' }}>
                                <Collapse in={isExpanded}>
                                  <Box sx={{ my: 0.5 }}>
                                    {result.script_results.map((script) => (
                                      <Box
                                        key={script.id}
                                        sx={{
                                          display: 'flex',
                                          alignItems: 'center',
                                          py: 0.5,
                                          pl: 6,
                                          pr: 0,
                                          gap: 1,
                                          '&:hover': { bgcolor: P.hoverBg },
                                        }}
                                      >
                                        <ScriptIcon fontSize="small" sx={{ flexShrink: 0, opacity: 0.6 }} />
                                        <Tooltip title={script.script_name} placement="top-start">
                                          <Typography variant="body2" sx={{ minWidth: 120, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {script.script_name}
                                          </Typography>
                                        </Tooltip>
                                        <Typography variant="body2" sx={{ opacity: 0.5, flexShrink: 0 }}>•</Typography>
                                        <Chip
                                          icon={script.skipped ? <SkippedIcon /> : (script.success ? <PassIcon /> : <FailIcon />)}
                                          label={script.skipped ? 'SKIP' : (script.success ? 'PASS' : 'FAIL')}
                                          color={script.skipped ? 'default' : (script.success ? 'success' : 'error')}
                                          size="small"
                                          sx={{ height: '16px', fontSize: TYPOGRAPHY.microMeta.size, flexShrink: 0 }}
                                        />
                                        <Typography variant="body2" sx={{ opacity: 0.5, flexShrink: 0 }}>•</Typography>
                                        <Typography variant="caption" sx={{ minWidth: 60, flexShrink: 0, opacity: 0.8 }}>
                                          {script.execution_time_ms ? formatDuration(script.execution_time_ms) : '-'}
                                        </Typography>
                                        <Box sx={{ ml: 'auto', display: 'flex', flexShrink: 0 }}>
                                          <Box sx={{ width: 78, px: 0.5, textAlign: 'center', boxSizing: 'border-box' }}>
                                            {script.testrail_sync ? (
                                              <Tooltip title={script.testrail_sync.status === 'published'
                                                ? `Published to TestRail run ${script.testrail_sync.run_id}`
                                                : script.testrail_sync.status === 'not_mapped'
                                                  ? 'Link this VirtualPyTest case to a TestRail case to include future runs'
                                                  : `TestRail sync ${script.testrail_sync.status}${script.testrail_sync.error ? `: ${script.testrail_sync.error}` : ''}`}>
                                                {script.testrail_sync.url ? (
                                                  <Chip
                                                    component="a"
                                                    href={script.testrail_sync.url}
                                                    target="_blank"
                                                    rel="noreferrer"
                                                    clickable
                                                    label="TestRail"
                                                    size="small"
                                                    color={script.testrail_sync.status === 'published' ? 'success' : 'error'}
                                                    onClick={(e) => e.stopPropagation()}
                                                    sx={{ height: 20, fontSize: TYPOGRAPHY.microMeta.size }}
                                                  />
                                                ) : (
                                                  <Chip label={script.testrail_sync.status === 'not_mapped' ? 'Needs link' : `TR ${script.testrail_sync.status}`} size="small"
                                                    color={script.testrail_sync.status === 'publishing' ? 'info' : script.testrail_sync.status === 'not_mapped' ? 'default' : 'error'}
                                                    sx={{ height: 20, fontSize: TYPOGRAPHY.microMeta.size }} />
                                                )}
                                              </Tooltip>
                                            ) : null}
                                          </Box>
                                          <Box sx={{ width: 55, px: 1, textAlign: 'center', boxSizing: 'border-box' }}>
                                            {script.html_report_r2_url ? (
                                              <Tooltip title="Open Report">
                                                <IconButton size="small" onClick={(e) => { e.stopPropagation(); handleOpenR2Url(script.html_report_r2_url!); }} color="primary" sx={{ p: 0.5 }}>
                                                  <ReportFileIcon fontSize="small" />
                                                </IconButton>
                                              </Tooltip>
                                            ) : null}
                                          </Box>
                                          {canShare && (
                                            <Box sx={{ width: 40, textAlign: 'center', boxSizing: 'border-box' }}>
                                              {script.html_report_r2_url ? (
                                                <Tooltip title="Share report">
                                                  <IconButton size="small" onClick={(e) => { e.stopPropagation(); setShareTarget({ id: script.id, name: script.script_name }); }} sx={{ p: 0.5 }}>
                                                    <ShareIcon fontSize="small" />
                                                  </IconButton>
                                                </Tooltip>
                                              ) : null}
                                            </Box>
                                          )}
                                          <Box sx={{ width: 55, px: 1, textAlign: 'center', boxSizing: 'border-box' }}>
                                            {script.logs_r2_url ? (
                                              <Tooltip title="Open Logs">
                                                <IconButton size="small" onClick={(e) => { e.stopPropagation(); handleOpenR2Url(script.logs_r2_url!); }} sx={{ ...(neutralButtonSx(P) as object),  p: 0.5 }}>
                                                  <LogsIcon fontSize="small" />
                                                </IconButton>
                                              </Tooltip>
                                            ) : null}
                                          </Box>
                                        </Box>
                                      </Box>
                                    ))}
                                  </Box>
                                </Collapse>
                              </TableCell>
                            </TableRow>
                          )}
                          </React.Fragment>
                        );
                      })
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
          </Box>
          {browserTab === 'shared' && <SharedLinksTab />}
          {/* ===== TESTS TABLE ===== */}
          <Box sx={{ display: browserTab === 'tests' ? 'block' : 'none' }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'nowrap', flex: 1, minWidth: 0, mr: 1 }}>
              <Autocomplete
                size="small"
                value={filterScript}
                onChange={(_e, v) => setFilterScript(v)}
                options={knownScripts}
                getOptionLabel={(option) => formatScriptLabel(option)}
                renderInput={(params) => (
                  <TextField
                    {...params}
                    label="Test"
                    InputLabelProps={{ shrink: true, sx: { px: 0.5 } }}
                  />
                )}
                slotProps={{ paper: { sx: { fontSize: TYPOGRAPHY.body.size } } }}
                sx={{ flex: '2 1 200px', minWidth: 140, '& .MuiInputBase-root': { height: 32, fontSize: TYPOGRAPHY.body.size } }}
              />
              <Autocomplete
                size="small"
                value={filterTarget}
                onChange={(_e, v) => setFilterTarget(v)}
                options={knownTargets}
                getOptionLabel={(option) => formatTargetLabel(option)}
                renderInput={(params) => (
                  <TextField
                    {...params}
                    label="Target"
                    InputLabelProps={{ shrink: true, sx: { px: 0.5 } }}
                  />
                )}
                slotProps={{ paper: { sx: { fontSize: TYPOGRAPHY.body.size } } }}
                sx={{ flex: '2 1 200px', minWidth: 140, '& .MuiInputBase-root': { height: 32, fontSize: TYPOGRAPHY.body.size } }}
              />
              {folderOptions.length > 1 && (
                <Box sx={{ display: 'flex', gap: 0.5 }}>
                  {folderOptions.map((folder) => (
                    <Chip
                      key={folder}
                      label={folder}
                      size="small"
                      variant={selectedFolder === folder ? 'filled' : 'outlined'}
                      color={selectedFolder === folder ? 'primary' : 'default'}
                      onClick={() => setSelectedFolder(selectedFolder === folder ? null : folder)}
                    />
                  ))}
                </Box>
              )}
              {([
                { key: 'milestone_id', label: 'Milestone', options: milestoneOptions, value: filterMilestoneId },
                { key: 'run_group_id', label: 'Group', options: groupOptions, value: filterGroupId },
                { key: 'label_id', label: 'Label', options: labelOptions, value: filterLabelId },
              ] as const).map((filter) => (
                <Autocomplete
                  key={filter.key}
                  size="small"
                  value={(filter.options as ReadonlyArray<{ id: string; name: string }>).find((o) => o.id === filter.value) ?? null}
                  onChange={(_e, v) => setGovernanceFilter(filter.key, v ? v.id : null)}
                  options={filter.options as ReadonlyArray<{ id: string; name: string }>}
                  getOptionLabel={(option) => option.name}
                  isOptionEqualToValue={(option, current) => option.id === current.id}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      label={filter.label}
                      InputLabelProps={{ shrink: true, sx: { px: 0.5 } }}
                    />
                  )}
                  slotProps={{ paper: { sx: { fontSize: TYPOGRAPHY.body.size } } }}
                  sx={{ flex: '1 1 110px', minWidth: 90, '& .MuiInputBase-root': { height: 32, fontSize: TYPOGRAPHY.body.size } }}
                />
              ))}
              {/* TASK-65 G7 — project scope. The full picker (chips + per-project
                  actions) lives in G9; here we just expose an `All + toggle`
                  filter so the chip column has a working scope. */}
              {projectOptions.length > 0 && (
                <>
                  <Autocomplete
                    size="small"
                    value={projectOptions.find((p) => p.id === filterProject) ?? null}
                    onChange={(_e, v) => setFilterProject(v ? v.id : null)}
                    options={projectOptions}
                    getOptionLabel={(option) => option.name}
                    isOptionEqualToValue={(option, current) => option.id === current.id}
                    renderOption={(props, option) => (
                      <li {...props} key={option.id} data-testid="project-filter-option">
                        {option.color && (
                          <Box
                            component="span"
                            sx={{
                              display: 'inline-block',
                              width: 10,
                              height: 10,
                              borderRadius: '50%',
                              backgroundColor: option.color,
                              marginRight: 1,
                              flexShrink: 0,
                            }}
                          />
                        )}
                        {option.name}
                      </li>
                    )}
                    renderInput={(params) => (
                      <TextField
                        {...params}
                        label="Project"
                        placeholder="All"
                        InputLabelProps={{ shrink: true, sx: { px: 0.5 } }}
                      />
                    )}
                    slotProps={{ paper: { sx: { fontSize: TYPOGRAPHY.body.size } } }}
                    sx={{ flex: '1 1 140px', minWidth: 110, '& .MuiInputBase-root': { height: 32, fontSize: TYPOGRAPHY.body.size } }}
                  />
                  <FormControlLabel
                    control={
                      <Checkbox
                        size="small"
                        checked={includeUntagged}
                        onChange={(_e, v) => setIncludeUntagged(v)}
                        data-testid="include-untagged"
                      />
                    }
                    label={<Typography variant="caption">Untagged</Typography>}
                    sx={{ flexShrink: 0, m: 0 }}
                  />
                </>
              )}
              {canAssign && (
                <Button
                  size="small"
                  variant="outlined"
                  sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}
                  disabled={selectedResultIds.size === 0}
                  onClick={() => setAssignOpen(true)}
                >
                  Assign ({selectedResultIds.size})
                </Button>
              )}
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Tooltip title="Toggle columns">
                <IconButton size="small" onClick={(e) => setColumnAnchor(e.currentTarget)}>
                  <ViewColumnIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              <Popover
                open={Boolean(columnAnchor)}
                anchorEl={columnAnchor}
                onClose={() => setColumnAnchor(null)}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                transformOrigin={{ vertical: 'top', horizontal: 'right' }}
              >
                <Box sx={{ p: 1, minWidth: 160 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ px: 1 }}>Show/Hide Columns</Typography>
                  {ALL_COLUMNS.map((col) => (
                    <FormControlLabel
                      key={col.id}
                      control={<Checkbox size="small" checked={isColumnVisible(col.id)} onChange={() => toggleColumnVisibility(col.id)} />}
                      label={<Typography variant="body2">{col.label}</Typography>}
                      sx={{ display: 'flex', mx: 0, py: 0 }}
                    />
                  ))}
                </Box>
              </Popover>
              <Tooltip title={showDetailedColumns ? 'Hide Analysis' : 'Show Analysis'}>
                <IconButton size="small" onClick={() => setShowDetailedColumns((prev) => !prev)}>
                  {showDetailedColumns ? <HideDetailsIcon fontSize="small" /> : <DetailsIcon fontSize="small" />}
                </IconButton>
              </Tooltip>
            </Box>
          </Box>

          <TableContainer component={Paper} variant="outlined">
            <Table size="small" sx={{
              tableLayout: 'fixed',
              '& .MuiTableCell-root': {
                px: 1,
                py: 0.25,
                fontSize: TYPOGRAPHY.body.size,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              },
              '& .MuiTableCell-paddingCheckbox': { px: 0, textAlign: 'center', overflow: 'visible' },
            }}>
              <TableHead>
                <TableRow>
                  {canAssign && (
                    <TableCell padding="checkbox" sx={{ width: 48, minWidth: 48 }}>
                      <Checkbox
                        size="small"
                        inputProps={{ 'aria-label': 'Select all results' }}
                        checked={filteredResults.length > 0 && filteredResults.every((r) => selectedResultIds.has(r.id))}
                        indeterminate={
                          filteredResults.some((r) => selectedResultIds.has(r.id)) &&
                          !filteredResults.every((r) => selectedResultIds.has(r.id))
                        }
                        onChange={(e) =>
                          setSelectedResultIds(e.target.checked ? new Set(filteredResults.map((r) => r.id)) : new Set())
                        }
                      />
                    </TableCell>
                  )}
                  <TableCell sx={{ py: 0.5, ...resizeCols.headerCellSx('script') }}>
                    <strong>Test</strong>
                    <Box component="span" onMouseDown={resizeCols.onMouseDown('script')} sx={resizeCols.resizeHandleSx} />
                  </TableCell>
                  {isColumnVisible('uiName') && (
                    <TableCell sx={{ py: 0.5, ...resizeCols.headerCellSx('uiName') }}>
                      <strong>UI Name</strong>
                      <Box component="span" onMouseDown={resizeCols.onMouseDown('uiName')} sx={resizeCols.resizeHandleSx} />
                    </TableCell>
                  )}
                  {isColumnVisible('host') && (
                    <TableCell sx={{ py: 0.5, ...resizeCols.headerCellSx('host') }}>
                      <strong>Target</strong>
                      <Box component="span" onMouseDown={resizeCols.onMouseDown('host')} sx={resizeCols.resizeHandleSx} />
                    </TableCell>
                  )}
                  {isColumnVisible('device') && (
                    <TableCell sx={{ py: 0.5, ...resizeCols.headerCellSx('device') }}>
                      <strong>Device</strong>
                      <Box component="span" onMouseDown={resizeCols.onMouseDown('device')} sx={resizeCols.resizeHandleSx} />
                    </TableCell>
                  )}
                  {isColumnVisible('status') && (
                    <TableCell sx={{ py: 0.5, ...resizeCols.headerCellSx('status') }}>
                      <strong>Status</strong>
                      <Box component="span" onMouseDown={resizeCols.onMouseDown('status')} sx={resizeCols.resizeHandleSx} />
                    </TableCell>
                  )}
                  {isColumnVisible('duration') && (
                    <TableCell sx={{ py: 0.5, ...resizeCols.headerCellSx('duration') }}>
                      <strong>Duration</strong>
                      <Box component="span" onMouseDown={resizeCols.onMouseDown('duration')} sx={resizeCols.resizeHandleSx} />
                    </TableCell>
                  )}
                  {isColumnVisible('started') && (
                    <TableCell sx={{ py: 0.5, ...resizeCols.headerCellSx('started') }}>
                      <strong>Started</strong>
                      <Box component="span" onMouseDown={resizeCols.onMouseDown('started')} sx={resizeCols.resizeHandleSx} />
                    </TableCell>
                  )}
                  {isColumnVisible('report') && (
                    <TableCell sx={{ py: 0.5, ...resizeCols.headerCellSx('report') }}>
                      <strong>Report</strong>
                      <Box component="span" onMouseDown={resizeCols.onMouseDown('report')} sx={resizeCols.resizeHandleSx} />
                    </TableCell>
                  )}
                  {isColumnVisible('logs') && (
                    <TableCell sx={{ py: 0.5, ...resizeCols.headerCellSx('logs') }}>
                      <strong>Logs</strong>
                      <Box component="span" onMouseDown={resizeCols.onMouseDown('logs')} sx={resizeCols.resizeHandleSx} />
                    </TableCell>
                  )}
                  {isColumnVisible('rerun') && (
                    <TableCell sx={{ py: 0.5, ...resizeCols.headerCellSx('rerun') }}>
                      <strong>Rerun</strong>
                      <Box component="span" onMouseDown={resizeCols.onMouseDown('rerun')} sx={resizeCols.resizeHandleSx} />
                    </TableCell>
                  )}
                  {showDetailedColumns && (
                    <>
                      <TableCell sx={{ py: 0.5, ...resizeCols.headerCellSx('checked') }}>
                        <strong>Checked</strong>
                        <Box component="span" onMouseDown={resizeCols.onMouseDown('checked')} sx={resizeCols.resizeHandleSx} />
                      </TableCell>
                      <TableCell sx={{ py: 0.5, ...resizeCols.headerCellSx('discard') }}>
                        <strong>Discard</strong>
                        <Box component="span" onMouseDown={resizeCols.onMouseDown('discard')} sx={resizeCols.resizeHandleSx} />
                      </TableCell>
                      <TableCell sx={{ py: 0.5, ...resizeCols.headerCellSx('analyzedBy') }}>
                        <strong>Analyzed By</strong>
                        <Box component="span" onMouseDown={resizeCols.onMouseDown('analyzedBy')} sx={resizeCols.resizeHandleSx} />
                      </TableCell>
                      <TableCell sx={{ py: 0.5, ...resizeCols.headerCellSx('comment') }}>
                        <strong>Comment</strong>
                        <Box component="span" onMouseDown={resizeCols.onMouseDown('comment')} sx={resizeCols.resizeHandleSx} />
                      </TableCell>
                    </>
                  )}
                </TableRow>
              </TableHead>
              <TableBody>
                {loading ? (
                  <TableRowsSkeleton rows={8} widths={skeletonColumnWidths} />
                ) : filteredResults.length === 0 ? (
                  <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                    <TableCell colSpan={visibleColumnCount} sx={{ textAlign: 'center', py: 4 }}>
                      <Typography variant="body2" color="textSecondary">
                        No script results available yet
                      </Typography>
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredResults.map((result) => (
                    <TableRow
                      key={result.id}
                      sx={{
                        '&:hover': {
                          backgroundColor: `${P.hoverBg} !important`,
                        },
                        opacity: result.discard ? 0.5 : 1,
                      }}
                    >
                      {canAssign && (
                        <TableCell padding="checkbox" sx={{ width: 48, minWidth: 48 }}>
                          <RowCheckbox
                            id={result.id}
                            label={`Select ${result.script_name}`}
                            checked={selectedResultIds.has(result.id)}
                            onToggle={toggleSelected}
                          />
                        </TableCell>
                      )}
                      <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('script') }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0 }}>
                          <Tooltip title={result.script_name} placement="top-start">
                            <Box component={RouterLink} to={REPORT_ROUTES.summary('script', result.id)} sx={{ overflow: 'hidden', textOverflow: 'ellipsis', color: 'inherit', textDecoration: 'none', '&:hover': { textDecoration: 'underline' } }}>{getScriptLabel(result)}</Box>
                          </Tooltip>
                          {(() => {
                            const flaky = flakyByKey.get(flakyKey(result.script_name, result.userinterface_name, result.host_name, result.device_name));
                            if (!flaky) return null;
                            return (
                              <Tooltip
                                title={`Flaky in the last ${flakyWindowDays} days: score ${flaky.flaky_score === null ? 'n/a' : flaky.flaky_score.toFixed(2)}, ${flaky.transitions} pass/fail flips over ${flaky.attempts} attempts${flaky.identity.environment ? ` (${flaky.identity.environment})` : ''}`}
                              >
                                <Chip
                                  label="Flaky"
                                  size="small"
                                  color="warning"
                                  variant="outlined"
                                  data-testid="flaky-badge"
                                  sx={{ height: 18, fontSize: TYPOGRAPHY.microMeta.size, flexShrink: 0 }}
                                />
                              </Tooltip>
                            );
                          })()}
                          {(result.labels ?? []).slice(0, 3).map((label) => (
                            <Chip
                              key={label.id}
                              label={label.name}
                              size="small"
                              variant="outlined"
                              data-testid="result-label"
                              sx={{ height: 18, fontSize: TYPOGRAPHY.microMeta.size, flexShrink: 0, borderColor: label.color ?? undefined }}
                            />
                          ))}
                          {(result.labels ?? []).length > 3 && (
                            <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0 }}>
                              +{(result.labels ?? []).length - 3}
                            </Typography>
                          )}
                          {/* TASK-65 G7 — project chips. One Chip per project the
                              run belongs to (a row can have several). Project
                              name is data (never localized); the colour, when
                              set, paints the chip border to match the project
                              in the picker. */}
                          {(result.projects ?? []).map((project) => (
                            <Chip
                              key={project.id}
                              label={project.name}
                              size="small"
                              variant="outlined"
                              data-testid="project-chip"
                              data-project-id={project.id}
                              onClick={() => setFilterProject(project.id)}
                              sx={{
                                height: 18,
                                fontSize: TYPOGRAPHY.microMeta.size,
                                flexShrink: 0,
                                borderColor: project.color ?? undefined,
                                borderWidth: project.color ? 1.5 : undefined,
                                cursor: 'pointer',
                              }}
                            />
                          ))}
                          {getTriggerLines(result).length > 0 && (
                            <Tooltip
                              title={<Box sx={{ whiteSpace: 'pre-line' }}>{getTriggerLines(result).join('\n')}</Box>}
                              placement="top-start"
                            >
                              <InfoIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size, flexShrink: 0, color: 'text.secondary', cursor: 'help' }} />
                            </Tooltip>
                          )}
                        </Box>
                      </TableCell>
                      {isColumnVisible('uiName') && (
                        <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('uiName') }}>{result.userinterface_name || 'N/A'}</TableCell>
                      )}
                      {isColumnVisible('host') && (
                        <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('host') }}>
                          <Tooltip title={formatTargetLabel(buildTargetKey(result.host_name, result.device_name))} placement="top-start">
                            <span>{formatTargetLabel(buildTargetKey(result.host_name, result.device_name))}</span>
                          </Tooltip>
                        </TableCell>
                      )}
                      {isColumnVisible('device') && (
                        <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('device') }}>{result.device_name}</TableCell>
                      )}
                      {isColumnVisible('status') && (
                        <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('status') }}>
                          {(() => {
                            const status = getExecutionStatus(result);
                            switch (status) {
                              case 'running':
                                return (
                                  <Tooltip title="Running">
                                    <RunningIcon color="warning" fontSize="small" />
                                  </Tooltip>
                                );
                              case 'passed':
                                return (
                                  <Tooltip title="Pass">
                                    <PassIcon color="success" fontSize="small" />
                                  </Tooltip>
                                );
                              case 'failed':
                                return (
                                  <Tooltip title="Fail">
                                    <FailIcon color="error" fontSize="small" />
                                  </Tooltip>
                                );
                              case 'skipped':
                                // The run never executed (it was not configured):
                                // the muted grey of a skip, never the red of a
                                // failure.
                                return (
                                  <Tooltip title="Skipped">
                                    <SkippedIcon color="disabled" fontSize="small" />
                                  </Tooltip>
                                );
                              default:
                                return (
                                  <Tooltip title="Unknown">
                                    <UnknownIcon color="disabled" fontSize="small" />
                                  </Tooltip>
                                );
                            }
                          })()}
                        </TableCell>
                      )}
                      {isColumnVisible('duration') && (
                        <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('duration') }}>
                          {result.execution_time_ms
                            ? formatDuration(result.execution_time_ms)
                            : 'N/A'}
                        </TableCell>
                      )}
                      {isColumnVisible('started') && (
                        <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('started') }}>{formatDate(result.started_at)}</TableCell>
                      )}
                      {isColumnVisible('report') && (
                        <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('report'), overflow: 'visible', textOverflow: 'clip' }}>
                          {result.html_report_r2_url ? (
                            <Tooltip title="Open Report">
                              <IconButton
                                size="small"
                                onClick={() => handleOpenR2Url(result.html_report_r2_url!)}
                                color="primary"
                                sx={{ p: 0.5 }}
                              >
                                <ReportFileIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          ) : (
                            <Typography variant="body2" color="text.disabled">-</Typography>
                          )}
                          {canShare && (result.html_report_r2_url || result.html_report_r2_path) && (
                            <Tooltip title="Share report">
                              <IconButton
                                size="small"
                                onClick={() => setShareTarget({ id: result.id, name: getScriptLabel(result) })}
                                sx={{ p: 0.5 }}
                              >
                                <ShareIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          )}
                        </TableCell>
                      )}
                      {isColumnVisible('logs') && (
                        <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('logs') }}>
                          {(() => { const logsRef = getLogsUrlOrPath(result); return logsRef; })() ? (
                            <Tooltip title="Open Logs">
                              <IconButton
                                size="small"
                                onClick={() => { const logsRef = getLogsUrlOrPath(result); if (logsRef) handleOpenR2Url(logsRef); }}
                                sx={{ ...(neutralButtonSx(P) as object),  p: 0.5 }}
                              >
                                <LogsIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          ) : (
                            <Typography variant="body2" color="text.disabled">-</Typography>
                          )}
                        </TableCell>
                      )}
                      {isColumnVisible('rerun') && (
                        <TableCell sx={{ py: 0.5, textAlign: 'center', ...resizeCols.bodyCellSx('rerun') }}>
                          {(() => {
                            // Manual runs record human outcomes; they are never replayed as scripts.
                            const payload = result.script_type === 'manual' ? null : buildRerunPayloadFromResult(result);
                            // No payload = the run never recorded a launch config
                            // (an unsaved testcase graph, or a row predating the
                            // executor persisting one). Nothing to replay.
                            if (!payload) {
                              return <Typography variant="body2" color="text.disabled">-</Typography>;
                            }
                            const busy = rerunningIds.includes(result.id);
                            return (
                              <Tooltip title="Rerun on the same target with the same config">
                                <span>
                                  <IconButton
                                    size="small"
                                    color="primary"
                                    disabled={busy}
                                    onClick={() => void handleRerun(result)}
                                    sx={{ p: 0.5 }}
                                  >
                                    {busy ? <CircularProgress size={16} /> : <RerunIcon fontSize="small" />}
                                  </IconButton>
                                </span>
                              </Tooltip>
                            );
                          })()}
                        </TableCell>
                      )}
                      {showDetailedColumns && (
                        <>
                          <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('checked') }}>
                            {getCheckedStatus(result)}
                          </TableCell>
                          <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('discard') }}>
                            {getDiscardStatus(result)}
                          </TableCell>
                          <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('analyzedBy') }}>
                            {getCheckType(result)}
                          </TableCell>
                          <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('comment') }}>
                            {getDiscardComment(result)}
                          </TableCell>
                        </>
                      )}
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>
          </Box>
        </CardContent>
      </Card>

      {canAssign && (
        <AssignmentDialog
          open={assignOpen}
          resultIds={Array.from(selectedResultIds)}
          onClose={() => setAssignOpen(false)}
          onDone={() => {
            setAssignOpen(false);
            setSelectedResultIds(new Set());
            showSuccess('Assignment saved');
            const filters: ScriptResultFilters = { ...governanceFilters };
            if (filterScript) filters.script_name = filterScript;
            if (filterTarget) filters.host_name = parseTargetKey(filterTarget).hostName;
            if (workspaceHostFilter) filters.host_filter = workspaceHostFilter;
            void loadScriptResults(Object.keys(filters).length > 0 ? filters : undefined);
          }}
        />
      )}

      {/* Discard Comment Modal */}
      <StyledDialog 
        open={discardModalOpen} 
        onClose={handleCloseDiscardModal}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <CommentIcon />
            AI Analysis Comment
          </Box>
        </DialogTitle>
        <DialogContent>
          {selectedDiscardComment && (
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.secondary' }}>
                Script: {getScriptLabel(selectedDiscardComment.result)}
              </Typography>
              <Typography variant="subtitle2" sx={{ mb: 2, color: 'text.secondary' }}>
                Analysis Type: {analysisTypeLabel(selectedDiscardComment.result.check_type)}
                {selectedDiscardComment.result.discard_type && ` • Category: ${selectedDiscardComment.result.discard_type}`}
              </Typography>
              {getJev(selectedDiscardComment.result) && <JevWhy jev={getJev(selectedDiscardComment.result)!} />}
              <Typography variant="body1" sx={{ whiteSpace: 'pre-wrap' }}>
                {selectedDiscardComment.comment}
              </Typography>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDiscardModal} color="primary">
            Close
          </Button>
        </DialogActions>
      </StyledDialog>
      {shareTarget && (
        <ShareReportDialog
          open
          onClose={() => setShareTarget(null)}
          scriptResultId={shareTarget.id}
          scriptName={shareTarget.name}
        />
      )}
    </Box>
  );
};

export default TestReports;
