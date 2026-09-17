import {
  Assessment as ReportsIcon,
  CheckCircle as PassIcon,
  Error as FailIcon,
  HourglassEmpty as RunningIcon,
  Link as LinkIcon,
  SmartToy as AiIcon,
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
} from '@mui/material';
import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';

import { useScriptResults, ScriptResult, ScriptResultFilters } from '../hooks/pages/useScriptResults';
import { useCampaignResults, CampaignResult } from '../hooks/pages/useCampaignResults';
import { useResizableColumns } from '../hooks/useResizableColumns';
import { useHostData } from '../hooks/useHostManager';
import { useServerManager } from '../hooks/useServerManager';
import { useWorkspaceContext } from '../contexts/workspace/WorkspaceContext';
import { formatToLocalTime } from '../utils/dateUtils';
import { openR2Url } from '../utils/infrastructure/cloudflareUtils';
import { StyledDialog } from '../components/common/StyledDialog';
import { formatScriptLabel, ensureScriptIdentityMap } from '../utils/executionUtils';
import { getEnv } from '../config/constants';

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
// device is named "<host>_Host", so "<host> - <host>_Host" shows the host
// twice — collapse it to just the host name. The underlying key (value) is
// unchanged so host+device filtering still works.
const formatTargetLabel = (key: string): string => {
  const { hostName, deviceName } = parseTargetKey(key);
  return !deviceName || deviceName === `${hostName}_Host`
    ? hostName
    : `${deviceName}${TARGET_KEY_SEP}${hostName}`;
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

const TestReports: React.FC = () => {
  // Get Grafana URL from environment variable
  const grafanaUrl = getEnv('VITE_GRAFANA_URL') || 'http://localhost/grafana';

  const { getAllScriptResults, updateCheckedStatus, updateDiscardStatus } = useScriptResults();
  const { getAllCampaignResults } = useCampaignResults();
  const { getAllHosts } = useHostData();
  const { selectedServer } = useServerManager();
  const { isDeviceAllowed, activeWorkspace } = useWorkspaceContext();
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
  const [filterScript, setFilterScript] = useState<string | null>(null);
  const [filterTarget, setFilterTarget] = useState<string | null>(null);
  const [filterCampaign, setFilterCampaign] = useState<string | null>(null);

  // Known options for filter dropdowns (populated from initial load)
  const [knownScripts, setKnownScripts] = useState<string[]>([]);
  const [knownTargets, setKnownTargets] = useState<string[]>([]);
  const [knownCampaigns, setKnownCampaigns] = useState<string[]>([]);
  const initialLoadDone = useRef(false);
  // Suppress the loading spinner on auto-refresh / filter-change refetches when
  // we already have a populated table — only show it before the first load lands.
  // Ref (not state) so the loadScriptResults closure doesn't go stale.
  const hasLoadedScriptsRef = useRef(false);

  // Tab — persisted in URL ?tab=campaigns
  const [searchParams, setSearchParams] = useSearchParams();
  const browserTab = (searchParams.get('tab') === 'campaigns' ? 'campaigns' : 'tests') as 'tests' | 'campaigns';
  const setBrowserTab = useCallback((tab: 'tests' | 'campaigns') => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (tab === 'tests') next.delete('tab'); else next.set('tab', tab);
      return next;
    }, { replace: true });
  }, [setSearchParams]);
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
    { key: 'report', initialWidth: 55, minWidth: 45 },
    { key: 'logs', initialWidth: 55, minWidth: 45 },
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
    { key: 'report', initialWidth: 55, minWidth: 45 },
    { key: 'logs', initialWidth: 55, minWidth: 45 },
  ]);

  // Column visibility — persisted to localStorage
  const COLUMN_VISIBILITY_KEY = 'test_reports_column_visibility_v1';
  type ColumnId = 'uiName' | 'host' | 'device' | 'status' | 'duration' | 'started' | 'report' | 'logs';
  const ALL_COLUMNS: { id: ColumnId; label: string }[] = [
    { id: 'uiName', label: 'UI Name' },
    { id: 'host', label: 'Target' },
    { id: 'device', label: 'Device' },
    { id: 'status', label: 'Status' },
    { id: 'duration', label: 'Duration' },
    { id: 'started', label: 'Started' },
    { id: 'report', label: 'Report' },
    { id: 'logs', label: 'Logs' },
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
    return count;
  }, [hiddenColumns, showDetailedColumns]);

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
        for (const r of results) {
          if (r.script_name) scripts.add(r.script_name);
          if (r.host_name) targets.add(buildTargetKey(r.host_name, r.device_name));
        }
        setKnownScripts(Array.from(scripts).sort());
        setKnownTargets(Array.from(targets).sort());
      }
    } catch (err) {
      console.error('[@component:TestReports] Error loading script results:', err);
      setError(err instanceof Error ? err.message : 'Failed to load script results');
    } finally {
      setLoading(false);
    }
  }, [getAllScriptResults]);

  useEffect(() => {
    const filters: ScriptResultFilters = {};
    if (filterScript) filters.script_name = filterScript;
    if (filterTarget) filters.host_name = parseTargetKey(filterTarget).hostName;
    if (workspaceHostFilter) filters.host_filter = workspaceHostFilter;
    loadScriptResults(Object.keys(filters).length > 0 ? filters : undefined);
  }, [filterScript, filterTarget, workspaceHostFilter, loadScriptResults]);

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
    setFilterScript(null);
    setFilterTarget(null);
    setFilterCampaign(null);
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
    setFilterScript(null);
    setFilterTarget(null);
    setFilterCampaign(null);
    setSelectedFolder(null);
    initialLoadDone.current = false;
    campaignLoadDone.current = false;

    // Explicit reload so options repopulate from the new workspace even when no
    // filter was selected (a cleared filterTarget wouldn't retrigger the load
    // effect). Scope to the new workspace's hosts.
    loadScriptResults(workspaceHostFilter ? { host_filter: workspaceHostFilter } : undefined);
    void loadCampaignResults(browserTab !== 'campaigns');
  }, [activeWorkspace?.id, workspaceHostFilter, loadScriptResults, loadCampaignResults, browserTab]);

  // Auto-refresh data every 20s
  useEffect(() => {
    const interval = setInterval(() => {
      if (browserTab === 'campaigns') {
        void loadCampaignResults(true);
      } else {
        const filters: ScriptResultFilters = {};
        if (filterScript) filters.script_name = filterScript;
        if (filterTarget) filters.host_name = parseTargetKey(filterTarget).hostName;
        void loadScriptResults(Object.keys(filters).length > 0 ? filters : undefined);
      }
    }, 20_000);
    return () => clearInterval(interval);
  }, [browserTab, filterScript, filterTarget, loadCampaignResults, loadScriptResults]);

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

  // Calculate stats
  const totalReports = scriptResults.length;
  const passedReports = scriptResults.filter((result) => result.success).length;
  const successRate = totalReports > 0 ? ((passedReports / totalReports) * 100).toFixed(1) : 'N/A';

  // Calculate average duration
  const validDurations = scriptResults.filter((result) => result.execution_time_ms !== null);
  const avgDuration =
    validDurations.length > 0
      ? formatDuration(
          validDurations.reduce((sum, result) => sum + (result.execution_time_ms || 0), 0) /
            validDurations.length,
        )
      : 'N/A';

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

    // Folder filter
    if (selectedFolder) {
      results = results.filter((r) => {
        if (!r.script_name) return false;
        const stripped = r.script_name.replace(/^test_scripts\//, '');
        return stripped.startsWith(selectedFolder + '/');
      });
    }

    return results;
  }, [scriptResults, browserTab, selectedFolder, filterTarget]);

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
  function getExecutionStatus(result: ScriptResult): 'running' | 'passed' | 'failed' {
    // If success is true, it's definitely passed
    if (result.success) {
      return 'passed';
    }
    
    // If success is false, check if it's still running or actually failed
    // Logic: If started_at and completed_at are very close (< 5 seconds), it's likely still running
    // because update_script_execution_result hasn't been called yet
    const startTime = new Date(result.started_at).getTime();
    const completedTime = new Date(result.completed_at).getTime();
    const timeDiff = Math.abs(completedTime - startTime);
    
    // If less than 5 seconds difference AND no execution time recorded, likely still running
    if (timeDiff < 5000 && !result.execution_time_ms) {
      return 'running';
    }
    
    // Otherwise, it's actually failed
    return 'failed';
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

  // Loading state component
  const LoadingState = () => (
    <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
      <CircularProgress />
    </Box>
  );

  // Note: EmptyState component removed - now handled inline with dynamic colspan

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
        <Typography variant="h4">
          Test Reports
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Chip
            label="Tests"
            clickable
            color={browserTab === 'tests' ? 'primary' : 'default'}
            variant={browserTab === 'tests' ? 'filled' : 'outlined'}
            onClick={() => setBrowserTab('tests')}
          />
          <Chip
            label="Campaigns"
            clickable
            color={browserTab === 'campaigns' ? 'primary' : 'default'}
            variant={browserTab === 'campaigns' ? 'filled' : 'outlined'}
            onClick={() => setBrowserTab('campaigns')}
          />
        </Box>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Quick Stats */}
      <Box sx={{ mb: 1 }}>
        <Card>
          <CardContent sx={{ py: 0.5, '&:last-child': { pb: 0.5 } }}>
            <Box display="flex" alignItems="center" justifyContent="space-between">
              <Box display="flex" alignItems="center" gap={1}>
                <ReportsIcon color="primary" fontSize="small" />
                <Typography variant="body1" fontWeight="bold" sx={{ my: 0 }}>Quick Stats</Typography>
                <Tooltip title="Open Script Results Dashboard">
                  <Box
                    display="flex"
                    alignItems="center"
                    gap={0.5}
                    onClick={() => window.open(`${grafanaUrl}/d/2a3b060a-7820-4a6e-aa2a-adcbf5408bd3/script-results?orgId=1&from=now-30d&to=now&timezone=browser&var-user_interface=$__all&var-host=$__all&var-device_name=$__all&var-script_name=$__all`, '_blank')}
                    sx={{ cursor: 'pointer' }}
                  >
                    <Typography variant="body2" color="primary">Grafana</Typography>
                    <OpenInNew fontSize="small" color="primary" />
                  </Box>
                </Tooltip>
              </Box>

              <Box display="flex" alignItems="center" gap={4}>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">Success Rate</Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {successRate}%
                  </Typography>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">Avg Duration</Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {avgDuration}
                  </Typography>
                </Box>
              </Box>
            </Box>
          </CardContent>
        </Card>
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
                        InputLabelProps={{ shrink: true, sx: { backgroundColor: 'background.paper', px: 0.5 } }}
                      />
                    )}
                    slotProps={{ paper: { sx: { fontSize: '0.8rem' } } }}
                    sx={{ minWidth: 340, '& .MuiInputBase-root': { height: 32, fontSize: '0.8rem' } }}
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
                        InputLabelProps={{ shrink: true, sx: { backgroundColor: 'background.paper', px: 0.5 } }}
                      />
                    )}
                    slotProps={{ paper: { sx: { fontSize: '0.8rem' } } }}
                    sx={{ minWidth: 380, '& .MuiInputBase-root': { height: 32, fontSize: '0.8rem' } }}
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
                    fontSize: '0.875rem',
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
                      <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                        <TableCell colSpan={visibleCampaignColumnCount}>
                          <LoadingState />
                        </TableCell>
                      </TableRow>
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
                        const hasScripts = (result.script_results?.length ?? 0) > 0;
                        const isExpanded = expandedCampaignId === result.id;
                        return (
                          <React.Fragment key={result.id}>
                          <TableRow
                            sx={{
                              '&:hover': {
                                backgroundColor: 'rgba(0, 0, 0, 0.04) !important',
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
                                  <span>{result.campaign_name}</span>
                                </Tooltip>
                              </Box>
                            </TableCell>
                            {isCampaignColumnVisible('host') && (
                              <TableCell sx={{ py: 0.5, ...campaignResizeCols.bodyCellSx('host') }} title={formatTargetLabel(buildTargetKey(result.host_name, result.device_name))}>{formatTargetLabel(buildTargetKey(result.host_name, result.device_name))}</TableCell>
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
                              <Tooltip title={`${passedCount}/${scriptCount} passed`}>
                                <span>{passedCount}/{scriptCount}</span>
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
                                    <LinkIcon fontSize="small" />
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
                                    color="secondary"
                                    sx={{ p: 0.5 }}
                                  >
                                    <LinkIcon fontSize="small" />
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
                                backgroundColor: 'rgba(0, 0, 0, 0.04) !important',
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
                                          '&:hover': { bgcolor: 'rgba(0, 0, 0, 0.04)' },
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
                                          icon={script.success ? <PassIcon /> : <FailIcon />}
                                          label={script.success ? 'PASS' : 'FAIL'}
                                          color={script.success ? 'success' : 'error'}
                                          size="small"
                                          sx={{ height: '16px', fontSize: '0.6rem', flexShrink: 0 }}
                                        />
                                        <Typography variant="body2" sx={{ opacity: 0.5, flexShrink: 0 }}>•</Typography>
                                        <Typography variant="caption" sx={{ minWidth: 60, flexShrink: 0, opacity: 0.8 }}>
                                          {script.execution_time_ms ? formatDuration(script.execution_time_ms) : '-'}
                                        </Typography>
                                        <Box sx={{ ml: 'auto', display: 'flex', flexShrink: 0 }}>
                                          <Box sx={{ width: 55, px: 1, textAlign: 'center', boxSizing: 'border-box' }}>
                                            {script.html_report_r2_url ? (
                                              <Tooltip title="Open Report">
                                                <IconButton size="small" onClick={(e) => { e.stopPropagation(); handleOpenR2Url(script.html_report_r2_url!); }} color="primary" sx={{ p: 0.5 }}>
                                                  <LinkIcon fontSize="small" />
                                                </IconButton>
                                              </Tooltip>
                                            ) : null}
                                          </Box>
                                          <Box sx={{ width: 55, px: 1, textAlign: 'center', boxSizing: 'border-box' }}>
                                            {script.logs_r2_url ? (
                                              <Tooltip title="Open Logs">
                                                <IconButton size="small" onClick={(e) => { e.stopPropagation(); handleOpenR2Url(script.logs_r2_url!); }} color="secondary" sx={{ p: 0.5 }}>
                                                  <LinkIcon fontSize="small" />
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
          {/* ===== TESTS TABLE ===== */}
          <Box sx={{ display: browserTab === 'tests' ? 'block' : 'none' }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
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
                    InputLabelProps={{ shrink: true, sx: { backgroundColor: 'background.paper', px: 0.5 } }}
                  />
                )}
                slotProps={{ paper: { sx: { fontSize: '0.8rem' } } }}
                sx={{ minWidth: 340, '& .MuiInputBase-root': { height: 32, fontSize: '0.8rem' } }}
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
                    InputLabelProps={{ shrink: true, sx: { backgroundColor: 'background.paper', px: 0.5 } }}
                  />
                )}
                slotProps={{ paper: { sx: { fontSize: '0.8rem' } } }}
                sx={{ minWidth: 380, '& .MuiInputBase-root': { height: 32, fontSize: '0.8rem' } }}
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
                fontSize: '0.875rem',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }
            }}>
              <TableHead>
                <TableRow>
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
                  <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                    <TableCell colSpan={visibleColumnCount}>
                      <LoadingState />
                    </TableCell>
                  </TableRow>
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
                          backgroundColor: 'rgba(0, 0, 0, 0.04) !important',
                        },
                        opacity: result.discard ? 0.5 : 1,
                      }}
                    >
                      <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('script') }}>
                        <Tooltip title={result.script_name} placement="top-start">
                          <span>{getScriptLabel(result)}</span>
                        </Tooltip>
                      </TableCell>
                      {isColumnVisible('uiName') && (
                        <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('uiName') }}>{result.userinterface_name || 'N/A'}</TableCell>
                      )}
                      {isColumnVisible('host') && (
                        <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('host') }} title={formatTargetLabel(buildTargetKey(result.host_name, result.device_name))}>{formatTargetLabel(buildTargetKey(result.host_name, result.device_name))}</TableCell>
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
                        <TableCell sx={{ py: 0.5, ...resizeCols.bodyCellSx('report') }}>
                          {result.html_report_r2_url ? (
                            <Tooltip title="Open Report">
                              <IconButton
                                size="small"
                                onClick={() => handleOpenR2Url(result.html_report_r2_url!)}
                                color="primary"
                                sx={{ p: 0.5 }}
                              >
                                <LinkIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          ) : (
                            <Typography variant="body2" color="text.disabled">-</Typography>
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
                                color="secondary"
                                sx={{ p: 0.5 }}
                              >
                                <LinkIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          ) : (
                            <Typography variant="body2" color="text.disabled">-</Typography>
                          )}
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
                Analysis Type: {(selectedDiscardComment.result.check_type === 'ai' || selectedDiscardComment.result.check_type === 'ai_agent') ? 'AI Agent Analysis' : selectedDiscardComment.result.check_type === 'ai_and_human' ? 'AI & Human Review' : 'Manual Review'}
                {selectedDiscardComment.result.discard_type && ` • Category: ${selectedDiscardComment.result.discard_type}`}
              </Typography>
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
    </Box>
  );
};

export default TestReports;
